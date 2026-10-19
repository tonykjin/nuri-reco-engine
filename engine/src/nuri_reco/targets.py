"""Stage 4: energy and macro targets per day type (PRD §8.1, Loam Score page §3, spec §3/§5/§8).

Order: TDEE -> goal energy (deficit capped by the planned weekly rate) -> protein first (g/kg)
-> fat fraction (with a g/kg minimum) -> carbs fill, or Matrix C day-type tiers in endurance
phases with the weekly deficit weighted onto rest/easy days -> calorie floor. Pure; every number
comes from the knowledge base.
"""

import datetime as dt
from typing import Any, Literal

from pydantic import Field

from nuri_reco.expenditure import ColdStartExpenditure, Expenditure
from nuri_reco.goals import PhasePlan
from nuri_reco.kb import KnowledgeBase, Rule
from nuri_reco.models import DayTargets, DayType, Profile, StrictModel
from nuri_reco.models.response import MicronutrientTarget
from nuri_reco.safety import SafetyResult

KCAL_PER_G = {"protein": 4, "carb": 4, "fat": 9}


class TargetsConflict(ValueError):
    """The targets can't all be met (e.g. protein + fat leave no room for carbs)."""


class Targets(StrictModel):
    phase: str
    expenditure_method: str
    tdee_kcal: float
    # Average daily change vs the reference (negative = deficit). Non-endurance phases are
    # measured against TDEE; endurance phases are fueling-first (Matrix C) and measured against
    # the fully fueled week, since the cold-start TDEE doesn't model training sessions.
    energy_reference: Literal["tdee", "fueled_week"]
    energy_delta_kcal: float
    # What the goal asked for; larger than the actual delta when tier minimums limited the trim.
    planned_delta_kcal: float
    floor_kcal: float
    by_day_type: dict[DayType, DayTargets]
    fiber_g_by_day_type: dict[DayType, float]
    protein_g_per_kg: float
    weight_basis: str
    weight_basis_kg: float
    protein_capped: bool = False
    per_meal_protein_g: float
    meals_per_day: int
    micronutrients: list[MicronutrientTarget]
    rule_ids: list[str] = Field(min_length=1)


def _x(rule: Rule) -> dict[str, Any]:
    return rule.model_extra or {}


def _at(rng: dict[str, float], position: float) -> float:
    return float(rng["min"] + position * (rng["max"] - rng["min"]))


class _Inputs:
    def __init__(self, phase: PhasePlan, profile: Profile, kb: KnowledgeBase) -> None:
        self.phase = phase
        self.profile = profile
        self.kb = kb
        self.t = kb.targets
        self.catalog = {g.type: g for g in kb.goals.goals}
        self.rule_ids: list[str] = []

    def use(self, *rule_ids: str) -> None:
        self.rule_ids.extend(rule_ids)

    def goal_rule(self, goal_type: str, aspect: str) -> Rule | None:
        """The owner's Matrix A rule for an aspect, following `modifier_of` / `same_as` links."""
        goal = self.catalog.get(goal_type)
        if goal is None:
            return None
        rule = goal.rules[aspect]
        x = _x(rule)
        target = x.get("protein_from") or x.get("same_as")
        if target:
            return self.kb.rules[target]
        if "modifier_of" in _x(goal) and not set(x) - {"text", "rule_ids"}:
            return self.goal_rule(_x(goal)["modifier_of"], aspect)
        return rule


def _protein(inp: _Inputs, safety: SafetyResult | None) -> tuple[float, bool]:
    """g/kg: a position in the owner's Matrix A range (spec §3), CKD cap overrides."""
    owner = inp.phase.energy_owner
    rule = inp.goal_rule(owner, "protein") or inp.goal_rule("maintain", "protein")
    if rule is None or not _range_keys(rule):
        rule = inp.catalog["maintain"].rules["protein"]
    x = _x(rule)
    resistance = inp.profile.training.resistance
    if resistance and "resistance_g_per_kg" in x:
        rng = x["resistance_g_per_kg"]
    elif "no_resistance_g_per_kg" in x:
        rng = x["no_resistance_g_per_kg"]
    elif "g_per_kg" in x:
        rng = x["g_per_kg"]
    else:
        rng = {"min": x["min_g_per_kg"], "max": x["min_g_per_kg"]}

    pos_rule = _x(inp.t.protein_position)
    # The owner's own rule (not the one it links to) says e.g. "Top of the lose-fat range".
    owner_goal = inp.catalog.get(owner)
    positions = [_x(owner_goal.rules["protein"]).get("position_in_range")] if owner_goal else []
    positions += [_x(inp.kb.rules[r]).get("position_in_range") for r in inp.phase.modifier_rule_ids]
    top = any(p in ("top", "upper") for p in positions)
    g_per_kg = _at(rng, pos_rule["top_position"] if top else pos_rule["range_position"])
    inp.use(rule.id, inp.t.protein_position.id)

    if safety and safety.protein_cap and g_per_kg > safety.protein_cap.max_g_per_kg:
        inp.use(safety.protein_cap.rule_id)
        return safety.protein_cap.max_g_per_kg, True
    return g_per_kg, False


def _range_keys(rule: Rule) -> bool:
    x = _x(rule)
    return any(
        k in x
        for k in ("resistance_g_per_kg", "no_resistance_g_per_kg", "g_per_kg", "min_g_per_kg")
    )


def _energy_delta(inp: _Inputs, tdee: float) -> float:
    """Average daily kcal vs TDEE for the phase's energy direction."""
    phase, profile = inp.phase, inp.profile
    position = _x(inp.t.energy_position)["range_position"]
    energy_rule = inp.goal_rule(phase.energy_owner, "energy")
    x = _x(energy_rule) if energy_rule else {}
    if phase.energy == "maintenance":
        return 0.0
    inp.use(inp.t.energy_position.id, *([energy_rule.id] if energy_rule else []))

    if phase.energy == "deficit":
        if "deficit_pct_tdee" not in x:
            x = _x(inp.catalog["lose_fat"].rules["energy"])
        deficit = _at(x["deficit_pct_tdee"], position) / 100 * tdee
        if "deficit_max_kcal_per_day" in x:
            deficit = min(deficit, x["deficit_max_kcal_per_day"])
        rate = phase.max_rate_pct_bw
        if phase.rate_pct_bw_week is not None:
            rate = min(phase.rate_pct_bw_week, rate) if rate is not None else phase.rate_pct_bw_week
        if rate is not None:
            kcal_per_kg = _x(inp.t.kcal_per_kg)["kcal_per_kg"]
            deficit = min(deficit, rate / 100 * profile.weight_kg * kcal_per_kg / 7)
            inp.use(inp.t.kcal_per_kg.id)
        return -deficit

    # Surplus.
    if "surplus_pct_tdee" in x:
        pct = x["surplus_pct_tdee"]
        band = (
            pct["advanced"]
            if profile.training.experience == "advanced"
            else pct["novice_intermediate"]
        )
        return _at(band, position) / 100 * tdee
    if "surplus_kcal_per_day" in x:
        return _at(x["surplus_kcal_per_day"], position)
    raise TargetsConflict(f"no surplus rule for goal {phase.energy_owner!r}")


def _floor(inp: _Inputs, safety: SafetyResult | None) -> float:
    """max(sex floor, EA floor), never under the absolute minimum (Matrix F calorie floor)."""
    rule = inp.kb.rules["GUARD.CALORIE_FLOOR"]
    x = _x(rule)
    floor = safety.calorie_floor.sex_floor_kcal if safety else x["sex_floor_kcal"][inp.profile.sex]
    bf = inp.profile.body_fat_pct
    if bf is not None:
        # Exercise kcal aren't modelled yet, so the EA floor is per kg of FFM only.
        ffm = inp.profile.weight_kg * (1 - bf / 100)
        floor = max(floor, x["ea_floor_kcal_per_kg_ffm"] * ffm)
    inp.use(rule.id)
    return float(max(floor, x["absolute_min_kcal_per_day"]))


def _fat_fraction(inp: _Inputs) -> tuple[float, float]:
    fat = _x(inp.t.fat)
    rule = inp.goal_rule(inp.phase.energy_owner, "carbs_fat")
    rng = _x(rule).get("fat_pct_kcal") if rule else None
    inp.use(inp.t.fat.id, *([rule.id] if rule and rng else []))
    fraction = _at(rng or fat["default_fat_pct_kcal"], fat["range_position"]) / 100
    return fraction, fat["fat_min_g_per_kg"] * inp.profile.weight_kg


def _macros_from_energy(
    kcal: float, protein_g: float, fat_frac: float, fat_min_g: float
) -> DayTargets:
    fat_g = max(kcal * fat_frac / KCAL_PER_G["fat"], fat_min_g)
    carb_g = (kcal - KCAL_PER_G["protein"] * protein_g - KCAL_PER_G["fat"] * fat_g) / KCAL_PER_G[
        "carb"
    ]
    if carb_g < 0:
        raise TargetsConflict(
            f"{kcal:.0f} kcal can't hold {protein_g:.0f} g protein and {fat_g:.0f} g fat "
            f"(carbs would be {carb_g:.0f} g)"
        )
    return DayTargets(kcal=kcal, protein_g=protein_g, carb_g=carb_g, fat_g=fat_g)


def _kcal(protein_g: float, carb_g: float, fat_g: float) -> float:
    return (
        KCAL_PER_G["protein"] * protein_g + KCAL_PER_G["carb"] * carb_g + KCAL_PER_G["fat"] * fat_g
    )


def _tiered(
    inp: _Inputs,
    day_types: list[DayType],
    protein_g: float,
    fat_frac: float,
    fat_min_g: float,
    delta: float,
    floor: float,
) -> tuple[dict[DayType, DayTargets], float]:
    """Matrix C carbs per day type; a weekly deficit lands on rest/easy days, weighted.

    Returns the day targets and the fully fueled week's average kcal (before any deficit)."""
    w = inp.profile.weight_kg
    position = _x(inp.t.carb_tiers)["range_position"]
    tiers = {d.day_type: d for d in inp.kb.daytypes.day_types}
    out: dict[DayType, DayTargets] = {}
    for d in day_types:
        tier = _x(tiers[d])["carb_g_per_kg"]
        carb_g = _at(tier, position) * w
        kcal = (KCAL_PER_G["protein"] * protein_g + KCAL_PER_G["carb"] * carb_g) / (1 - fat_frac)
        fat_g = max(kcal * fat_frac / KCAL_PER_G["fat"], fat_min_g)
        out[d] = DayTargets(
            kcal=_kcal(protein_g, carb_g, fat_g), protein_g=protein_g, carb_g=carb_g, fat_g=fat_g
        )
        inp.use(tiers[d].id)
    inp.use(inp.t.carb_tiers.id)
    fueled_avg = _weekly_avg(out, inp.profile.training.weekly_schedule)

    if delta < 0:
        weights = _x(inp.t.deficit_split)["weights"]
        schedule = inp.profile.training.weekly_schedule
        total_weight = sum(weights.get(d, 0) for d in schedule)
        if total_weight:
            weekly = -delta * 7
            inp.use(inp.t.deficit_split.id)
            for d, targets in out.items():
                share = weekly * weights.get(d, 0) / total_weight
                carb_min = _x(tiers[d])["carb_g_per_kg"]["min"] * w
                carb_g = max(targets.carb_g - share / KCAL_PER_G["carb"], carb_min)
                out[d] = targets.model_copy(
                    update={"carb_g": carb_g, "kcal": _kcal(protein_g, carb_g, targets.fat_g)}
                )

    for d, targets in out.items():
        if targets.kcal < floor:
            carb_g = targets.carb_g + (floor - targets.kcal) / KCAL_PER_G["carb"]
            out[d] = targets.model_copy(update={"carb_g": carb_g, "kcal": floor})
    return out, fueled_avg


def _weekly_avg(by_day: dict[DayType, DayTargets], schedule: list[DayType]) -> float:
    return sum(by_day[d].kcal for d in schedule) / len(schedule)


def _micronutrients(inp: _Inputs) -> list[MicronutrientTarget]:
    profile = inp.profile
    out = []
    for n in inp.kb.micronutrients.nutrients:
        rows = [r for r in n.values if r["sex"] in (profile.sex, "any")]
        youngest = min(r.get("age_min", 0) for r in rows)
        age = max(profile.age, youngest)  # adult table: younger users get the youngest adult band
        row = next(r for r in rows if r.get("age_min", 0) <= age <= r.get("age_max", float("inf")))
        out.append(
            MicronutrientTarget(id=n.nutrient, target=row["amount"], unit=n.unit, window=n.window)
        )
        inp.use(n.id)
    return out


def compute(
    phase: PhasePlan,
    profile: Profile,
    kb: KnowledgeBase,
    *,
    safety: SafetyResult | None = None,
    expenditure: Expenditure | None = None,
) -> Targets:
    """Daily targets for each day type in the profile's weekly schedule during this phase."""
    inp = _Inputs(phase, profile, kb)
    exp = expenditure or ColdStartExpenditure(kb)
    tdee = exp.tdee(profile)
    inp.use(kb.targets.mifflin_st_jeor.id, kb.targets.activity_factors.id)

    g_per_kg, capped = _protein(inp, safety)
    protein_g = g_per_kg * profile.weight_kg
    delta = _energy_delta(inp, tdee)
    floor = _floor(inp, safety)
    fat_frac, fat_min_g = _fat_fraction(inp)
    day_types: list[DayType] = list(dict.fromkeys(profile.training.weekly_schedule))

    tiers = _x(kb.targets.carb_tiers)
    event_phases = {p.name for p in kb.phases.phases}
    trains = bool(set(day_types) & set(tiers["training_day_types"]))
    if trains and (phase.name in event_phases or phase.energy_owner in tiers["owner_goal_types"]):
        by_day, fueled_avg = _tiered(inp, day_types, protein_g, fat_frac, fat_min_g, delta, floor)
        reference: Literal["tdee", "fueled_week"] = "fueled_week"
        actual_delta = _weekly_avg(by_day, profile.training.weekly_schedule) - fueled_avg
    else:
        kcal = max(tdee + delta, floor)
        day = _macros_from_energy(kcal, protein_g, fat_frac, fat_min_g)
        by_day = {d: day for d in day_types}
        reference, actual_delta = "tdee", kcal - tdee

    fiber = _x(kb.targets.fiber)
    meal = _x(kb.rules["TIMING.PROTEIN_PER_MEAL"])
    meals = int(meal["min_meals"])
    inp.use(kb.targets.fiber.id, "TIMING.PROTEIN_PER_MEAL")
    return Targets(
        phase=phase.name,
        expenditure_method=exp.method,
        tdee_kcal=tdee,
        energy_reference=reference,
        energy_delta_kcal=actual_delta,
        planned_delta_kcal=delta,
        floor_kcal=floor,
        by_day_type=by_day,
        fiber_g_by_day_type={
            d: max(fiber["min_g_per_day"], fiber["g_per_1000_kcal"] * t.kcal / 1000)
            for d, t in by_day.items()
        },
        protein_g_per_kg=g_per_kg,
        weight_basis=_x(kb.targets.protein_position)["weight_basis"],
        weight_basis_kg=profile.weight_kg,
        protein_capped=capped,
        per_meal_protein_g=max(
            protein_g / meals, meal["protein_g_per_kg_per_meal"] * profile.weight_kg
        ),
        meals_per_day=meals,
        micronutrients=_micronutrients(inp),
        rule_ids=list(dict.fromkeys(inp.rule_ids)),
    )


def ramped(prev: Targets, nxt: Targets, phase: PhasePlan, on: dt.date) -> dict[DayType, DayTargets]:
    """Targets on a given day: linear blend from the previous phase during the ramp window."""
    if not (phase.ramp_start and phase.ramp_end and phase.ramp_start <= on < phase.ramp_end):
        return nxt.by_day_type
    t = (on - phase.ramp_start) / (phase.ramp_end - phase.ramp_start)
    out: dict[DayType, DayTargets] = {}
    for d, new in nxt.by_day_type.items():
        old = prev.by_day_type.get(d, new)
        out[d] = DayTargets(
            **{
                k: getattr(old, k) + t * (getattr(new, k) - getattr(old, k))
                for k in ("kcal", "protein_g", "carb_g", "fat_g")
            }
        )
    return out
