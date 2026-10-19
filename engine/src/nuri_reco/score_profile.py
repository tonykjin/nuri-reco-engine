"""Stage 4b: personal Loam Score profile (spec §7b, Matrix G).

For each phase: weights = 0.6 x primary row + 0.4 x mean(secondary rows), medical floors applied
and protected, the other components rescaled to 100; personal targets per component from the
Stage 4 targets and the Loam Score page formulas; disabled components; top levers. Pure; every
parameter comes from score_weights.yaml.
"""

from collections import Counter
from typing import Any

from nuri_reco.goals import PhasePlan
from nuri_reco.kb import KnowledgeBase, Rule
from nuri_reco.models import DayType, Profile
from nuri_reco.models.response import (
    DisabledComponent,
    LoamScoreProfile,
    MicronutrientTarget,
    PhaseScoreProfile,
    ScoreComponent,
    ScoreTarget,
    TopLever,
)
from nuri_reco.safety import SafetyResult
from nuri_reco.targets import Targets


def _x(rule: Rule) -> dict[str, Any]:
    return rule.model_extra or {}


def round_to_100(exact: dict[str, float]) -> dict[str, int]:
    """Whole-number weights summing to 100 (largest remainder), for display."""
    floors = {k: int(v) for k, v in exact.items()}
    short = 100 - sum(floors.values())
    by_remainder = sorted(exact, key=lambda k: (exact[k] - floors[k], exact[k]), reverse=True)
    for k in by_remainder[:short]:
        floors[k] += 1
    return floors


def phase_weights(
    primary: str, goal_types: list[str], kb: KnowledgeBase
) -> tuple[dict[str, float], list[str]]:
    """Spec §7b.2: stacked, floored weights for one phase, plus the rule ids used."""
    sw = kb.score_weights
    rows = {t: row for row in sw.rows for t in row.goal_types}
    fallback = rows["maintain"]
    primary_row = rows.get(primary, fallback)
    stacking = _x(sw.stacking)
    merged = set(stacking["merged_into"].get(primary, []))
    secondaries = [rows[t] for t in goal_types if t != primary and t not in merged and t in rows]

    rule_ids = [primary_row.id]
    weights = dict(primary_row.weights)
    if secondaries:
        p, s = stacking["primary_share"], stacking["secondary_share"]
        weights = {
            c: p * primary_row.weights[c]
            + s * sum(r.weights[c] for r in secondaries) / len(secondaries)
            for c in sw.components
        }
        rule_ids += [sw.stacking.id, *(r.id for r in secondaries)]

    protected: set[str] = set()
    for floor in sw.floors:
        if set(floor.goal_types) & set(goal_types):
            for component, minimum in _x(floor)["minimums"].items():
                weights[component] = max(weights[component], minimum)
                protected.add(component)
            rule_ids.append(floor.id)
    if protected:
        total = stacking["total"]
        floored = sum(weights[c] for c in protected)
        others = [c for c in sw.components if c not in protected]
        if floored > total:
            # The floors can't all hold: scale them to fit; nothing left for the rest.
            for c in sw.components:
                weights[c] = weights[c] * total / floored if c in protected else 0.0
            rule_ids.append(sw.floor_conflict.id)
        else:
            scale = (total - floored) / sum(weights[c] for c in others)
            for c in others:
                weights[c] *= scale
        rule_ids.append(sw.floor_rule.id)
    return weights, list(dict.fromkeys(rule_ids))


class _Builder:
    def __init__(self, kb: KnowledgeBase, profile: Profile, goal_types: list[str]) -> None:
        self.kb = kb
        self.profile = profile
        self.goal_types = goal_types
        self.targets = {r.id: r for r in kb.score_weights.component_targets}
        applies = _x(kb.score_weights.applies_to)
        self.applies = {
            c: [view for view in ("meal", "day", "week") if c in applies[view]]
            for c in kb.score_weights.components
        }

    def component(
        self,
        rule_id: str,
        id: str,
        target: ScoreTarget,
        day_type: DayType | None = None,
        extra_rule_ids: tuple[str, ...] = (),
    ) -> ScoreComponent:
        rule = self.targets[rule_id]
        x = _x(rule)
        return ScoreComponent(
            id=id,
            type=rule.score_type,
            target=target,
            applies_to=self.applies[rule.component],
            weight_key=rule.component,
            day_type=day_type,
            rule_ids=list(dict.fromkeys([rule.id, *extra_rule_ids])),
            why=x["why"],
        )

    def components(self, t: Targets) -> list[ScoreComponent]:
        out: list[ScoreComponent] = []
        x = {rid: _x(r) for rid, r in self.targets.items()}
        tiers = {d.day_type: d for d in self.kb.daytypes.day_types}
        w = t.weight_basis_kg

        lo, hi = t.protein_range_g_per_kg
        protein_rules = tuple(r for r in t.rule_ids if r.endswith(".PROTEIN") or r == "GUARD.CKD")
        out.append(
            self.component(
                "LS.PROTEIN",
                "protein",
                ScoreTarget(low=lo * w, high=hi * w, unit="g"),
                extra_rule_ids=protein_rules,
            )
        )
        for d, day in t.by_day_type.items():
            tol = x["LS.ENERGY"]["tolerance_pct"] / 100
            out.append(
                self.component(
                    "LS.ENERGY",
                    "energy",
                    ScoreTarget(low=day.kcal * (1 - tol), high=day.kcal * (1 + tol), unit="kcal"),
                    d,
                )
            )
            if t.energy_reference == "fueled_week":
                tier = _x(tiers[d])["carb_g_per_kg"]
                carb = ScoreTarget(low=tier["min"] * w, high=tier["max"] * w, unit="g")
                carb_rules: tuple[str, ...] = (tiers[d].id,)
            else:
                tol = x["LS.CARB"]["fill_tolerance_pct"] / 100
                carb = ScoreTarget(
                    low=day.carb_g * (1 - tol), high=day.carb_g * (1 + tol), unit="g"
                )
                carb_rules = ()
            out.append(self.component("LS.CARB", "carb", carb, d, carb_rules))
            out.append(
                self.component(
                    "LS.FIBER",
                    "fiber",
                    ScoreTarget(min=t.fiber_g_by_day_type[d], unit="g"),
                    d,
                    ("TARGETS.FIBER",),
                )
            )
            for rid, cid in (("LS.SATFAT", "sat_fat"), ("LS.FREESUGAR", "free_sugar")):
                limit = day.kcal * x[rid]["energy_share"] / x[rid]["kcal_per_g"]
                out.append(self.component(rid, cid, ScoreTarget(max=limit, unit="g"), d))

        sodium = x["LS.SODIUM"]
        hypertensive = set(sodium["hypertension_goal_types"]) & set(self.goal_types)
        out.append(
            self.component(
                "LS.SODIUM",
                "sodium",
                ScoreTarget(
                    max=sodium["hypertension_max_mg" if hypertensive else "max_mg"], unit="mg"
                ),
            )
        )
        produce = x["LS.PATTERN"]["produce_min_g_per_day"]
        out.append(self.component("LS.PATTERN", "produce", ScoreTarget(min=produce, unit="g")))
        return out

    def micronutrients(
        self, t: Targets, diet: str | None, ckd: bool
    ) -> tuple[list[MicronutrientTarget], list[DisabledComponent]]:
        micro = _x(self.targets["LS.MICRO"])
        flags = {f["nutrient"]: f["flag"] for f in micro["supplement_flags"] if f["diet"] == diet}
        disabled: list[DisabledComponent] = []
        drop: set[str] = set()
        if ckd:
            for d in micro["ckd_disables"]:
                drop.add(d["nutrient"])
                disabled.append(DisabledComponent(id=d["disabled_id"], reason=d["reason"]))
        panel = [
            m.model_copy(update={"flag": flags.get(m.id)})
            for m in t.micronutrients
            if m.id not in drop
        ]
        return panel, disabled


def _levers(
    weights: dict[str, float], primary: str, t: Targets, profile: Profile, kb: KnowledgeBase
) -> list[TopLever]:
    """Spec §7b.4: lever = weight x shortfall prior, top N, one templated sentence each."""
    priors = _x(kb.score_weights.priors)
    rows = {g: row for row in kb.score_weights.rows for g in row.goal_types}
    row = rows.get(primary, rows["maintain"])
    prior = dict(priors["priors"])
    if row.weights["protein"] <= priors["low_protein_weight_max"]:
        prior["protein"] = priors["low_protein_prior"]
    order = kb.score_weights.components
    ranked = sorted(order, key=lambda c: (-weights[c] * prior[c], order.index(c)))

    common_day = Counter(profile.training.weekly_schedule).most_common(1)[0][0]
    day = t.by_day_type[common_day]
    values = {
        "kcal": round(day.kcal / 10) * 10,
        "protein_per_meal_g": round(t.per_meal_protein_g),
        "meals": t.meals_per_day,
        "fiber_g": round(t.fiber_g_by_day_type[common_day]),
        "produce_g": _x(kb.rules["LS.PATTERN"])["produce_min_g_per_day"],
    }
    templates = _x(kb.score_weights.levers)["templates"]
    return [
        TopLever(component=c, text=templates[c]["first" if i == 0 else "next"].format(**values))
        for i, c in enumerate(ranked[: priors["top_n"]])
    ]


def build(
    phases: list[PhasePlan],
    targets: list[Targets],
    profile: Profile,
    kb: KnowledgeBase,
    *,
    goal_types: list[str],
    diet: str | None = None,
    safety: SafetyResult | None = None,
) -> LoamScoreProfile:
    """Score configuration for each phase. `targets[i]` are the Stage 4 targets of `phases[i]`;
    `goal_types` are the request's goals (secondaries for stacking, condition floors)."""
    if len(phases) != len(targets):
        raise ValueError("one Targets per phase is required")
    builder = _Builder(kb, profile, goal_types)
    by_phase: list[PhaseScoreProfile] = []
    all_rule_ids: list[str] = []
    rd_set = set(_x(kb.rules["LS.CARB"])["rd_set_goal_types"]) & set(goal_types)
    # CKD: potassium credit off (spec §7b.3). Safety's CKD rule decides; without a safety
    # result, fall back to the profile flag.
    ckd = "GUARD.CKD" in safety.rd_gated_rule_ids if safety else profile.flags.ckd_stage is not None

    for phase, t in zip(phases, targets, strict=True):
        exact, rule_ids = phase_weights(phase.energy_owner, goal_types, kb)
        panel, disabled = builder.micronutrients(t, diet, ckd)
        if rd_set:
            disabled.append(DisabledComponent(id="carb_auto_target", reason="rd_set"))
        by_phase.append(
            PhaseScoreProfile(
                phase=phase.name,
                primary=phase.energy_owner,
                weights=round_to_100(exact),
                weights_exact=exact,
                weight_rule_ids=rule_ids,
                components=builder.components(t),
                micronutrients=panel,
                disabled=disabled,
            )
        )
        all_rule_ids += rule_ids

    first = by_phase[0] if by_phase else None
    levers = (
        _levers(first.weights_exact, phases[0].energy_owner, targets[0], profile, kb)
        if first
        else []
    )
    return LoamScoreProfile(
        by_phase=by_phase,
        top_levers=levers,
        weight_rule_ids=list(dict.fromkeys(all_rule_ids)) or [kb.score_weights.stacking.id],
    )
