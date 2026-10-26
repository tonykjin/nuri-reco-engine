"""Meal pattern (Task 27; spec §5 TIMING.MEAL_PATTERN, COMPOSE.MEAL_SLOTS and slot weights)."""

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.main import app
from nuri_reco import compose, explain, foods
from nuri_reco.compose import _meals, _slots, _template
from nuri_reco.engine import plan
from nuri_reco.kb import load_kb
from nuri_reco.models import DayType, PlanRequest, PlanResponse, SampleDay
from nuri_reco.targets import MealChoice

PERSONAS = Path(__file__).parent / "personas"
client = TestClient(app, raise_server_exceptions=False)


def raw(name: str, meals: int | None = None, snacks: int | None = None) -> dict[str, Any]:
    body: dict[str, Any] = json.loads((PERSONAS / f"{name}.json").read_text(encoding="utf-8"))
    body.pop("expect")
    body["preferences"].update(meals_per_day=meals, snacks_per_day=snacks)
    return body


def request(name: str, meals: int | None = None, snacks: int | None = None) -> PlanRequest:
    return PlanRequest.model_validate(raw(name, meals, snacks))


def day(req: PlanRequest, day_type: DayType, full: PlanResponse | None = None) -> SampleDay:
    full = full or plan(req)
    kb = load_kb()
    return compose.compose(
        full,
        req.profile,
        req.preferences,
        req.constraints,
        kb,
        foods.load_foods(),
        day_type=day_type,
    )


def strip_pattern_ids(d: SampleDay) -> dict[str, Any]:
    """A sample day without the rule ids a user-chosen pattern adds (they're the only change)."""
    extra = {"COMPOSE.MEAL_SLOTS", "TIMING.MEAL_PATTERN"}
    out = d.model_dump(mode="json")
    out["rule_ids"] = [r for r in out["rule_ids"] if r not in extra]
    for meal in out["meals"]:
        meal["rule_ids"] = [r for r in meal["rule_ids"] if r not in extra]
    return out


# --- Default pattern: nothing changes ---


@pytest.mark.parametrize("name", ["maya", "marathon_fatloss", "hybrid"])
def test_default_is_3_meals_and_1_snack_and_matches_asking_for_it(name: str) -> None:
    default, explicit = request(name), request(name, 3, 1)
    p_default, p_explicit = plan(default), plan(explicit)
    mp = p_default.phases[0].meal_pattern
    assert (mp.meals, mp.snacks, mp.source) == (3, 1, "default")
    assert p_explicit.phases[0].meal_pattern.source == "user"
    for d in dict.fromkeys(default.profile.training.weekly_schedule):
        assert strip_pattern_ids(day(default, d, p_default)) == strip_pattern_ids(
            day(explicit, d, p_explicit)
        )


def test_default_day_cites_no_pattern_rules() -> None:
    d = day(request("maya"), "rest")
    assert "COMPOSE.MEAL_SLOTS" not in d.rule_ids
    assert [m.slot for m in d.meals] == ["breakfast", "lunch", "dinner", "snack"]


def test_default_shares_are_todays_template_shares() -> None:
    kb = load_kb()
    profile = request("maya").profile
    default = MealChoice(meals=3, snacks=1, source="default")
    for day_type, shares in [("rest", [25, 30, 30, 15]), ("long", [20, 25, 15, 30, 10])]:
        template = _template(kb, day_type)
        meals = _meals(template, _slots(template, default, kb), profile, 140, kb)
        assert [m.kcal_share for m in meals] == [s / 100 for s in shares]


# --- Protein follows the pattern; the daily target never moves ---


def test_three_meals_spread_the_same_daily_protein_wider() -> None:
    default, three = plan(request("maya")), plan(request("maya", 3, 0))
    assert three.phases[0].targets_by_day_type == default.phases[0].targets_by_day_type
    daily = three.phases[0].targets_by_day_type["rest"].protein_g
    mp = three.phases[0].meal_pattern
    assert daily == pytest.approx(140, abs=0.5)  # Maya: 70 kg x 2.0 g/kg
    assert mp.per_meal_protein_g == round(daily / 3, 1) == 46.7
    assert {"TIMING.MEAL_PATTERN", "TIMING.PROTEIN_PER_MEAL"} <= set(mp.rule_ids)
    kb = load_kb()
    assert explain.text(kb, "TIMING.MEAL_PATTERN", "snack_nudge") in mp.why
    assert "3 meals: about 47 g each" in mp.why


def test_four_occasions_under_40_g_get_no_nudge() -> None:
    mp = plan(request("maya", 3, 1)).phases[0].meal_pattern
    assert explain.text(load_kb(), "TIMING.MEAL_PATTERN", "snack_nudge") not in mp.why
    assert "3 meals and 1 snack" in mp.why


def test_glp1_with_two_meals_points_to_small_protein_first_portions() -> None:
    kb = load_kb()
    two = plan(request("glp1_t2d_strength", 2, 0)).phases[0].meal_pattern
    assert "GOAL.GLP1.FOODS" in two.rule_ids
    assert explain.text(kb, "TIMING.MEAL_PATTERN", "glp1_nudge") in two.why
    three = plan(request("glp1_t2d_strength", 3, 0)).phases[0].meal_pattern
    assert "GOAL.GLP1.FOODS" not in three.rule_ids


def test_one_meal_lever_copy_is_singular() -> None:
    resp = plan(request("novice_recomp", 1, 0))
    protein = next(lv for lv in resp.loam_score_profile.top_levers if lv.component == "protein")
    assert "at your one meal" in protein.text
    assert "1 meals" not in protein.text
    assert "1 meal: about" in resp.phases[0].meal_pattern.why


# --- Composer slots ---


def test_two_meals_two_snacks_on_a_rest_day() -> None:
    d = day(request("maya", 2, 2), "rest")
    assert [m.slot for m in d.meals] == ["lunch", "dinner", "snack", "snack"]
    assert {"COMPOSE.MEAL_SLOTS", "TIMING.MEAL_PATTERN"} <= set(d.rule_ids)
    kb = load_kb()
    choice = MealChoice(meals=2, snacks=2, source="user")
    template = _template(kb, "rest")
    meals = _meals(template, _slots(template, choice, kb), request("maya").profile, 140, kb)
    assert sum(m.kcal_share for m in meals) == pytest.approx(1)
    assert [round(m.kcal_share * 90) for m in meals] == [30, 30, 15, 15]


def test_session_day_adds_the_pre_session_meal_before_dinner() -> None:
    d = day(request("marathon_fatloss", 3, 0), "long")
    assert [m.slot for m in d.meals] == ["breakfast", "lunch", "pre_session", "dinner"]


def test_four_meals_add_an_extra_meal_ranked_like_lunch() -> None:
    d = day(request("maya", 4, 0), "rest")
    assert [m.slot for m in d.meals] == ["breakfast", "lunch", "extra_meal", "dinner"]


def test_past_four_occasions_the_daily_protein_is_split() -> None:
    kb = load_kb()
    profile = request("maya").profile  # 70 kg: the dose is 28 g
    template = _template(kb, "rest")
    seven = _meals(template, _slots(template, MealChoice(4, 3, "user"), kb), profile, 140, kb)
    assert all(m.protein_target == pytest.approx(20) for m in seven)  # 140 g / 7 < 28 g
    four = _meals(template, _slots(template, MealChoice(3, 1, "user"), kb), profile, 100, kb)
    assert all(m.protein_target == pytest.approx(28) for m in four)  # up to 4: the full dose


@pytest.mark.parametrize("pattern", [(1, 0), (2, 0), (2, 2), (3, 0), (4, 3)])
@pytest.mark.parametrize(
    ("name", "day_type"),
    [("maya", "rest"), ("marathon_fatloss", "rest"), ("marathon_fatloss", "long")],
)
def test_patterns_stay_within_tolerance(
    name: str, day_type: DayType, pattern: tuple[int, int]
) -> None:
    d = day(request(name, *pattern), day_type)
    assert d.within_tolerance, d.deviation_pct


# --- Validation ---


@pytest.mark.parametrize(
    ("meals", "snacks", "field"),
    [
        (5, None, "meals_per_day"),
        (0, None, "meals_per_day"),
        (None, -1, "snacks_per_day"),
        (3, 4, "snacks_per_day"),
    ],
)
def test_counts_outside_the_rule_are_rejected(
    meals: int | None, snacks: int | None, field: str
) -> None:
    with pytest.raises(ValueError, match=field):
        plan(request("maya", meals, snacks))
    resp = client.post("/v1/plan", json=raw("maya", meals, snacks))
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_request"
    assert field in resp.json()["error"]["message"]


def test_a_blocked_plan_still_rejects_a_bad_count() -> None:
    with pytest.raises(ValueError, match="meals_per_day"):
        plan(request("under18", 9, None))


# --- API ---


def test_recommendations_day_honors_the_pattern() -> None:
    resp = client.post(
        "/v1/recommendations/day", json={"request": raw("maya", 2, 0), "day_type": "rest"}
    )
    assert resp.status_code == 200, resp.text
    assert [m["slot"] for m in resp.json()["day"]["meals"]] == ["lunch", "dinner"]


def test_plan_exposes_the_meal_pattern() -> None:
    resp = client.post("/v1/plan", json=raw("maya", 2, 1))
    assert resp.status_code == 200, resp.text
    mp = resp.json()["phases"][0]["meal_pattern"]
    assert (mp["meals"], mp["snacks"], mp["source"]) == (2, 1, "user")
    assert mp["provenance"] == "recommended"
