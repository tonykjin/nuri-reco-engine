"""Sample-day composer (Task 21; spec §5 timing, §7.4 foods, compose.yaml)."""

import json
from functools import cache
from pathlib import Path

import pytest

from nuri_reco import explain
from nuri_reco.compose import compose
from nuri_reco.engine import plan
from nuri_reco.foods import load_foods
from nuri_reco.kb import load_kb
from nuri_reco.models import DayType, PlanRequest, PlanResponse, SampleDay

PERSONAS = Path(__file__).parent / "personas"
FOODS = {f["key"]: f for f in load_foods()}


def request(name: str) -> PlanRequest:
    raw = json.loads((PERSONAS / f"{name}.json").read_text(encoding="utf-8"))
    raw.pop("expect")
    return PlanRequest.model_validate(raw)


@cache
def response(name: str) -> PlanResponse:
    return plan(request(name))


@cache
def day(name: str, day_type: DayType, phase: str | None = None) -> SampleDay:
    req = request(name)
    return compose(
        response(name),
        req.profile,
        req.preferences,
        req.constraints,
        load_kb(),
        load_foods(),
        day_type=day_type,
        phase=phase,
    )


def tolerance() -> float:
    return float((load_kb().compose.tolerance.model_extra or {})["pct"])


# --- Runbook Task 21: Maya and the marathoner's long day within ±10% ---


@pytest.mark.parametrize(("name", "day_type"), [("maya", "rest"), ("marathon_fatloss", "long")])
def test_day_lands_within_tolerance(name: str, day_type: DayType) -> None:
    sample = day(name, day_type)
    targets = sample.targets
    for macro in ("kcal", "protein_g"):
        actual, target = getattr(sample.nutrients, macro), getattr(targets, macro)
        assert abs(actual - target) / target * 100 <= tolerance(), (macro, actual, target)
    assert sample.within_tolerance, sample.deviation_pct


def test_marathon_long_day_has_a_low_fiber_pre_session_meal() -> None:
    sample, kb = day("marathon_fatloss", "long"), load_kb()
    pre = [m for m in sample.meals if m.slot == "pre_session"]
    assert len(pre) == 1
    p = kb.rules["FOOD.RANK.PRE_RACE"].model_extra or {}
    for item in pre[0].items:
        attrs, per_100g = FOODS[item.key]["attributes"], FOODS[item.key]["per_100g"]
        assert attrs["fiber_g_per_100kcal"] < p["high_fiber_g_per_100kcal"], item.name
        assert per_100g["fat_g"] * 9 / per_100g["energy_kcal"] * 100 <= p["high_fat_pct_energy"]
    session = kb.rules["COMPOSE.MEALS.SESSION"].model_extra or {}
    fiber = pre[0].nutrients.fiber_g
    assert fiber is not None and fiber <= session["pre_session_max_fiber_g"]
    assert "TIMING.PRE_SESSION_CARBS" in pre[0].rule_ids
    assert sum(1 for i in pre[0].items if i.role == "sweet") <= 1
    assert pre[0].carb_target_g is not None
    carbs = pre[0].carb_target_g
    assert carbs.min <= pre[0].nutrients.carb_g <= carbs.max


def test_rest_day_has_no_pre_session_meal() -> None:
    assert [m.slot for m in day("maya", "rest").meals] == ["breakfast", "lunch", "dinner", "snack"]


def test_marathoner_gets_no_peanut_foods() -> None:
    sample = day("marathon_fatloss", "long")
    for meal in sample.meals:
        for item in meal.items:
            assert "peanuts" not in FOODS[item.key]["allergens"], item.name
            assert "peanut" not in item.name.lower(), item.name


@pytest.mark.parametrize(
    ("name", "diet_tag"), [("vegan_muscle", "vegan"), ("marathon_fatloss", "pescatarian")]
)
def test_day_respects_the_diet(name: str, diet_tag: str) -> None:
    schedule = request(name).profile.training.weekly_schedule
    for day_type in set(schedule):
        for meal in day(name, day_type).meals:
            for item in meal.items:
                assert FOODS[item.key]["diet"][diet_tag], item.name


def test_protein_meals_reach_their_per_meal_target() -> None:
    sample = day("maya", "rest")
    per_meal = load_kb().rules["TIMING.PROTEIN_PER_MEAL"].model_extra or {}
    expected = 0.0 + per_meal["protein_g_per_kg_per_meal"] * request("maya").profile.weight_kg
    protein_meals = [m for m in sample.meals if m.protein_target_g is not None]
    assert len(protein_meals) >= per_meal["min_meals"]
    for meal in protein_meals:
        assert meal.protein_target_g == pytest.approx(expected, abs=0.1)
        assert meal.nutrients.protein_g >= meal.protein_target_g * (1 - tolerance() / 100)
        assert "TIMING.PROTEIN_PER_MEAL" in meal.rule_ids


def test_no_food_repeats_within_a_day() -> None:
    keys = [i.key for m in day("marathon_fatloss", "long").meals for i in m.items]
    assert len(keys) == len(set(keys))


def test_portions_stay_in_range() -> None:
    portions = load_kb().compose.portions.model_extra or {}
    for meal in day("marathon_fatloss", "long").meals:
        for item in meal.items:
            group = FOODS[item.key]["group"]
            bounds = portions["groups_g"].get(group, portions["default_g"])
            assert bounds["min"] <= item.grams <= bounds["max"], (item.name, item.grams)
            assert item.nutrients.kcal <= portions["max_item_kcal"] + 0.5


def test_totals_add_up() -> None:
    sample = day("maya", "rest")
    for macro in ("kcal", "protein_g", "carb_g", "fat_g"):
        meals = sum(getattr(m.nutrients, macro) for m in sample.meals)
        assert getattr(sample.nutrients, macro) == pytest.approx(meals, abs=0.5)
        dev = getattr(sample.nutrients, macro) - getattr(sample.targets, macro)
        assert sample.deviation_pct[macro] == pytest.approx(  # type: ignore[index]
            dev / getattr(sample.targets, macro) * 100, abs=0.1
        )


def test_missing_fiber_stays_missing() -> None:
    sample = day("maya", "rest")
    for meal in sample.meals:
        unknown = any(FOODS[i.key]["per_100g"]["fiber_g"] is None for i in meal.items)
        assert (meal.nutrients.fiber_g is None) == unknown
    if any(m.nutrients.fiber_g is None for m in sample.meals):
        assert sample.nutrients.fiber_g is None


def test_every_item_is_explained() -> None:
    kb = load_kb()
    sample = day("marathon_fatloss", "long")
    assert sample.provenance == "recommended" and sample.why
    for meal in sample.meals:
        assert meal.provenance == "recommended" and meal.why and meal.rule_ids
        for item in meal.items:
            assert item.provenance == "recommended" and item.why and item.rule_ids
    missing = [r for r in explain.rule_ids_in(sample) if not explain.has(kb, r, "rule")]
    assert missing == []
    assert explain.banned_phrases_in(sample, kb) == []


def test_is_deterministic() -> None:
    req = request("hybrid")
    args = (
        response("hybrid"),
        req.profile,
        req.preferences,
        req.constraints,
        load_kb(),
        load_foods(),
    )
    first = compose(*args, day_type="quality")
    assert compose(*args, day_type="quality") == first


@pytest.mark.parametrize(
    "name",
    [
        "maya",
        "marathon_fatloss",
        "hybrid",
        "vegan_muscle",
        "novice_recomp",
        "wedding_8wk",
        "glp1_t2d_strength",
    ],
)
def test_every_persona_day_lands_within_tolerance(name: str) -> None:
    resp = response(name)
    for phase in resp.phases:
        for day_type in phase.targets_by_day_type:
            sample = day(name, day_type, phase.name)
            assert sample.within_tolerance, (phase.name, day_type, sample.deviation_pct)


def test_phase_and_day_type_must_exist() -> None:
    req = request("maya")
    args = (
        response("maya"),
        req.profile,
        req.preferences,
        req.constraints,
        load_kb(),
        load_foods(),
    )
    with pytest.raises(ValueError, match="no phase named"):
        compose(*args, day_type="rest", phase="nope")
    with pytest.raises(ValueError, match="no targets for day type"):
        compose(*args, day_type="long")
