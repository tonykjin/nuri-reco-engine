"""Stage 4 targets + cold-start expenditure."""

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest

from nuri_reco.expenditure import AdaptiveExpenditure, ColdStartExpenditure
from nuri_reco.goals import PhasePlan, resolve
from nuri_reco.kb import load_kb
from nuri_reco.models import DayType, Energy, PlanRequest, Profile
from nuri_reco.safety import check as safety_check
from nuri_reco.targets import Targets, TargetsConflict, compute, ramped

PERSONAS = Path(__file__).parent / "personas"
NOT_BLOCKED = [
    "maya",
    "novice_recomp",
    "marathon_fatloss",
    "wedding_8wk",
    "hybrid",
    "glp1_t2d_strength",
    "vegan_muscle",
]


def persona(name: str) -> PlanRequest:
    raw = json.loads((PERSONAS / f"{name}.json").read_text(encoding="utf-8"))
    raw.pop("expect")
    return PlanRequest.model_validate(raw)


def plan_targets(name: str) -> list[tuple[PhasePlan, Targets]]:
    kb = load_kb()
    req = persona(name)
    safety = safety_check(req, kb)
    phases = resolve(req, safety, kb).phases
    return [(p, compute(p, req.profile, kb, safety=safety)) for p in phases]


def profile(**overrides: Any) -> Profile:
    raw: dict[str, Any] = {
        "age": 30,
        "sex": "female",
        "height_cm": 168,
        "weight_kg": 70,
        "activity": "moderate",
        "training": {"resistance": True, "weekly_schedule": ["rest"] * 7},
    }
    raw.update(overrides)
    return Profile.model_validate(raw)


def phase(energy: Energy = "deficit", owner: str = "lose_fat", **extra: Any) -> PhasePlan:
    return PhasePlan(
        name="main",
        start=dt.date(2026, 10, 16),
        end=None,
        energy=energy,
        energy_owner=owner,
        rule_ids=["RESOLVER.ONE_ENERGY_GOAL"],
        why="w",
        **extra,
    )


# --- Expenditure ---


def test_mifflin_st_jeor_from_yaml() -> None:
    exp = ColdStartExpenditure(load_kb())
    maya = persona("maya").profile
    assert exp.rmr(maya) == 10 * 70 + 6.25 * 168 - 5 * 30 - 161 == 1439
    assert exp.tdee(maya) == pytest.approx(1439 * 1.55)
    assert exp.rmr(profile(sex="male")) == 1439 + 166


def test_unknown_activity_and_adaptive_without_logs() -> None:
    with pytest.raises(ValueError, match="unknown activity 'couch'"):
        ColdStartExpenditure(load_kb()).tdee(profile(activity="couch"))
    # Task 22 replaced the stub: with no logs, adaptive falls back to the cold-start estimate.
    adaptive = AdaptiveExpenditure(load_kb(), [])
    assert adaptive.method == "mifflin_st_jeor"
    assert adaptive.tdee(profile()) == ColdStartExpenditure(load_kb()).tdee(profile())


# --- Maya (PRD §8.1, re-baselined: Matrix F rate cap wins) ---


def test_maya() -> None:
    [(_, t)] = plan_targets("maya")
    [day] = t.by_day_type.values()
    # PRD: 1,800 / 140 / 185 / 55. The 0.5 %/week cap (BMI 24.8) limits the deficit to
    # 0.5% x 70 kg x 7,700 / 7 = 385 kcal, so the engine gives 1,845 / 140 / 194 / 56.
    assert day.kcal == pytest.approx(1845, rel=0.05)
    assert day.protein_g == pytest.approx(140, rel=0.05)
    assert day.carb_g == pytest.approx(194, rel=0.05)
    assert day.fat_g == pytest.approx(56, rel=0.05)
    # kcal, protein and fat stay within ±5% of the PRD's numbers too.
    assert day.kcal == pytest.approx(1800, rel=0.05)
    assert day.fat_g == pytest.approx(55, rel=0.05)
    assert t.energy_delta_kcal == pytest.approx(-385, abs=1)
    assert t.protein_g_per_kg == pytest.approx(2.0, abs=0.01)
    assert t.weight_basis == "actual" and t.weight_basis_kg == 70
    assert t.per_meal_protein_g == pytest.approx(35, abs=0.5) and t.meals_per_day == 4
    assert t.fiber_g_by_day_type["rest"] == pytest.approx(14 * day.kcal / 1000)


def test_maya_micronutrients() -> None:
    [(_, t)] = plan_targets("maya")
    micros = {m.id: m.target for m in t.micronutrients}
    # Spec §7b.5: iron 18 mg, calcium 1,000 mg, vit D 15 mcg, Mg 310 mg, K 2,600 mg,
    # B12 2.4 mcg, folate 400 mcg DFE (30-year-old woman).
    assert micros == {
        "iron": 18,
        "calcium": 1000,
        "vitamin_d": 15,
        "magnesium": 310,
        "potassium": 2600,
        "vitamin_b12": 2.4,
        "folate": 400,
    }


@pytest.mark.parametrize(
    ("overrides", "nutrient", "expected"),
    [
        ({"age": 55}, "iron", 8),
        ({"age": 55}, "calcium", 1200),
        ({"age": 75, "sex": "male"}, "vitamin_d", 20),
        ({"age": 60, "sex": "male"}, "calcium", 1000),
        ({"age": 40, "sex": "male"}, "magnesium", 420),
        ({"age": 16}, "magnesium", 310),  # adult table: youngest band
    ],
)
def test_micronutrients_by_age_and_sex(
    overrides: dict[str, Any], nutrient: str, expected: float
) -> None:
    t = compute(phase("maintenance", "maintain"), profile(**overrides), load_kb())
    assert {m.id: m.target for m in t.micronutrients}[nutrient] == expected


# --- Floors (Matrix F) ---


@pytest.mark.parametrize("name", NOT_BLOCKED)
def test_floors_never_breached(name: str) -> None:
    for p, t in plan_targets(name):
        assert t.floor_kcal >= 1200
        for day, targets in t.by_day_type.items():
            assert targets.kcal >= t.floor_kcal - 1e-6, (p.name, day)


def test_ea_floor_uses_ffm_when_body_fat_known() -> None:
    lean = profile(body_fat_pct=20, weight_kg=70)
    t = compute(phase(), lean, load_kb(), expenditure=_Fixed(1500))
    assert t.floor_kcal == pytest.approx(30 * 70 * 0.8)  # 1,680 > 1,200 sex floor
    assert t.by_day_type["rest"].kcal == pytest.approx(1680)


def test_floor_raises_low_targets() -> None:
    t = compute(phase(), profile(), load_kb(), expenditure=_Fixed(1300))
    assert t.by_day_type["rest"].kcal == 1200


# --- Marathoner (Matrix C, fueling-first) ---


def test_marathon_long_days_get_more_carbs() -> None:
    for p, t in plan_targets("marathon_fatloss"):
        days = t.by_day_type
        if "long" in days and p.name != "resume":
            assert days["long"].carb_g > days["rest"].carb_g, p.name


def test_marathon_base_deficit_only_on_rest_and_easy_days() -> None:
    by_phase = {p.name: t for p, t in plan_targets("marathon_fatloss")}
    base, build = by_phase["base"], by_phase["build"]
    w = 72
    assert base.energy_reference == "fueled_week" and base.energy_delta_kcal < 0
    # Quality and long days are fully fueled at the Matrix C midpoint (8 g/kg).
    for day in ("quality", "long"):
        assert base.by_day_type[day].carb_g == pytest.approx(8 * w)
    # Rest and easy days are trimmed, never below their tier minimum.
    assert base.by_day_type["rest"].carb_g < 4 * w
    assert base.by_day_type["rest"].carb_g >= 3 * w - 1e-6
    assert base.by_day_type["easy"].carb_g < 6 * w
    # Tier minimums limited the trim, and the result says so.
    assert base.planned_delta_kcal < base.energy_delta_kcal < 0
    # No deficit at maintenance.
    assert build.energy_delta_kcal == 0 and build.by_day_type["rest"].carb_g == pytest.approx(4 * w)


def test_hybrid_carbs_by_day_type() -> None:
    [(_, t)] = plan_targets("hybrid")
    w = 80
    tiers: dict[DayType, tuple[int, int]] = {
        "rest": (3, 5),
        "easy": (5, 7),
        "quality": (6, 10),
        "long": (6, 10),
    }
    for day, (lo, hi) in tiers.items():
        assert lo * w <= t.by_day_type[day].carb_g <= hi * w


def test_strength_without_sessions_uses_tdee() -> None:
    [(_, t)] = plan_targets("glp1_t2d_strength")
    assert t.energy_reference == "tdee"
    assert t.by_day_type["rest"].kcal == pytest.approx(t.tdee_kcal)


# --- Protein positions and caps ---


def test_deadline_and_vegan_protein_at_top() -> None:
    [(_, wedding), _] = plan_targets("wedding_8wk")
    assert wedding.protein_g_per_kg == pytest.approx(1.6)  # top of 1.2-1.6 (no lifting)
    [(_, vegan)] = plan_targets("vegan_muscle")
    assert vegan.protein_g_per_kg == pytest.approx(2.2)  # top of 1.6-2.2


def test_ckd_cap_overrides_goal_protein() -> None:
    kb = load_kb()
    req = persona("maya")
    flags = req.profile.flags.model_copy(update={"ckd_stage": 3})
    req = req.model_copy(update={"profile": req.profile.model_copy(update={"flags": flags})})
    safety = safety_check(req, kb)
    t = compute(resolve(req, safety, kb).phases[0], req.profile, kb, safety=safety)
    assert t.protein_capped and t.protein_g_per_kg == 0.6
    assert "GUARD.CKD" in t.rule_ids


def test_surplus_and_maintenance() -> None:
    [(_, vegan)] = plan_targets("vegan_muscle")
    assert vegan.energy_delta_kcal == pytest.approx(0.15 * vegan.tdee_kcal)  # 10-20% midpoint
    t = compute(phase("maintenance", "maintain"), profile(), load_kb())
    assert t.energy_delta_kcal == 0


# --- Conflict, ramp, rule ids ---


def test_negative_carbs_raise_conflict() -> None:
    heavy = profile(weight_kg=150, height_cm=190)
    with pytest.raises(TargetsConflict, match="carbs would be -"):
        compute(phase(), heavy, load_kb(), expenditure=_Fixed(900))


def test_ramp_blends_between_phases() -> None:
    by_phase = {p.name: (p, t) for p, t in plan_targets("marathon_fatloss")}
    _, base = by_phase["base"]
    build_phase, build = by_phase["build"]
    assert build_phase.ramp_start and build_phase.ramp_end
    halfway = build_phase.ramp_start + (build_phase.ramp_end - build_phase.ramp_start) / 2
    mid = ramped(base, build, build_phase, halfway)["rest"].kcal
    lo, hi = sorted([base.by_day_type["rest"].kcal, build.by_day_type["rest"].kcal])
    assert lo < mid < hi
    assert ramped(base, build, build_phase, build_phase.ramp_end) == build.by_day_type


@pytest.mark.parametrize("name", NOT_BLOCKED)
def test_rule_ids_exist(name: str) -> None:
    rules = load_kb().rules
    for _, t in plan_targets(name):
        assert set(t.rule_ids) <= set(rules), set(t.rule_ids) - set(rules)
        assert {"ENERGY.MIFFLIN_ST_JEOR", "GUARD.CALORIE_FLOOR"} <= set(t.rule_ids)


class _Fixed:
    method = "fixed"
    rule_ids = ["ENERGY.MIFFLIN_ST_JEOR"]

    def __init__(self, tdee: float) -> None:
        self._tdee = tdee

    def tdee(self, profile: Profile) -> float:
        return self._tdee
