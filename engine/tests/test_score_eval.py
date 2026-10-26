"""Score evaluation (Task 23; Loam Score page §4-5, spec §7b.3, score_eval.yaml)."""

import copy
import json
from collections import Counter
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from nuri_reco import explain
from nuri_reco.engine import plan
from nuri_reco.foods import load_foods
from nuri_reco.kb import load_kb
from nuri_reco.models import PlanRequest, PlanResponse, ScoreEvaluation, ScoreItem, ScoreLevel
from nuri_reco.score_eval import adequacy, evaluate, moderation, target_range

PERSONAS = Path(__file__).parent / "personas"
APPLE = [ScoreItem(key="apple", grams=182)]
CHICKEN_MEAL = [
    ScoreItem(key="chicken_breast_roasted", grams=150),
    ScoreItem(key="rice_white_cooked", grams=200),
    ScoreItem(key="broccoli_boiled", grams=100),
]


def request(name: str) -> PlanRequest:
    raw = json.loads((PERSONAS / f"{name}.json").read_text(encoding="utf-8"))
    raw.pop("expect")
    return PlanRequest.model_validate(raw)


@cache
def response(name: str) -> PlanResponse:
    return plan(request(name), dry_run=True)


def common_day(name: str) -> Any:
    return Counter(request(name).profile.training.weekly_schedule).most_common(1)[0][0]


def score(
    name: str,
    items: list[ScoreItem],
    level: ScoreLevel = "meal",
    table: list[dict[str, Any]] | None = None,
) -> ScoreEvaluation:
    return evaluate(
        response(name),
        items,
        load_kb(),
        table if table is not None else load_foods(),
        level=level,
        day_type=common_day(name),
    )


def part(ev: ScoreEvaluation, id: str) -> Any:
    return next(c for c in ev.components if c.id == id)


# --- Loam Score page §4 formulas ---


def test_formulas() -> None:
    assert adequacy(10, 25) == 40 and adequacy(30, 25) == 100
    assert target_range(50, 100, 150) == 50
    assert target_range(120, 100, 150) == 100
    assert target_range(300, 100, 150) == 50
    assert moderation(10, 20) == 100 and moderation(40, 20) == 50


# --- Runbook Task 23: the apple at meal level ---


def test_apple_is_not_penalized_for_missing_a_days_protein() -> None:
    meal, day = score("maya", APPLE), score("maya", APPLE, level="day")
    protein = part(meal, "protein")
    day_range = next(c for c in response("maya").loam_score_profile.by_phase[0].components)
    assert day_range.id == "protein" and day_range.target.low is not None
    # The apple's protein is judged against its calorie share of the day, not 112-154 g.
    assert protein.target.low == pytest.approx(day_range.target.low * meal.energy_share)
    assert meal.energy_share < 0.1
    assert protein.score > part(day, "protein").score
    # Its fiber and moderation get full credit, and energy isn't scored at meal level.
    assert part(meal, "fiber").score == 100
    assert part(meal, "sodium").score == 100
    assert {(o.id, o.reason) for o in meal.left_out} == {("energy", "not_at_meal_level")}
    assert meal.score is not None and day.score is not None and meal.score > day.score


def test_meal_level_uses_only_meal_components() -> None:
    applies = load_kb().score_weights.applies_to.model_extra or {}
    meal, day = score("maya", CHICKEN_MEAL), score("maya", CHICKEN_MEAL, level="day")
    assert {c.weight_key for c in meal.components} <= set(applies["meal"]) - {"energy"}
    assert {c.weight_key for c in day.components} == set(applies["day"])
    assert {"iron", "produce"} <= {c.id for c in day.components}
    assert not {"iron", "produce"} & {c.id for c in meal.components}


# --- Runbook Task 23: missing data lowers coverage, not the score ---


def test_missing_data_lowers_coverage_not_score() -> None:
    table = load_foods()
    gap = copy.deepcopy(table)
    for f in gap:
        if f["key"] == "broccoli_boiled":
            f["per_100g"]["fiber_g"] = None
    known, missing = (
        score("maya", CHICKEN_MEAL, table=table),
        score("maya", CHICKEN_MEAL, table=gap),
    )
    fiber = part(missing, "fiber")
    assert fiber.actual is None and fiber.score is None and not fiber.available
    assert missing.coverage_pct < known.coverage_pct
    # The score is the weighted mean of the parts that have data...
    others = [c for c in known.components if c.id != "fiber" and c.score is not None]
    mean = sum(c.weight * c.score for c in others) / sum(c.weight for c in others)
    assert missing.score == pytest.approx(mean)
    # ...not what it would be if the missing fiber counted as 0.
    zero = [*others, part(known, "fiber").model_copy(update={"score": 0.0})]
    as_zero = sum(c.weight * c.score for c in zero) / sum(c.weight for c in zero)
    assert missing.score > as_zero


def test_free_sugar_without_data_is_left_out() -> None:
    ev = score("maya", APPLE)
    sugar = part(ev, "free_sugar")
    assert sugar.actual is None and not sugar.available
    assert sugar.why == explain.text(load_kb(), "EVAL.COVERAGE", "missing")
    assert ev.coverage_pct < 100


# --- Runbook Task 23: the same meal scores differently per profile ---


def test_same_meal_scores_differently_for_maya_and_the_marathoner() -> None:
    maya, runner = score("maya", CHICKEN_MEAL), score("marathon_fatloss", CHICKEN_MEAL)
    assert maya.score != runner.score
    assert part(maya, "carb").weight != part(runner, "carb").weight


# --- Shape and invariants ---


@pytest.mark.parametrize("level", ["meal", "day"])
def test_contributions_add_up_to_the_score(level: ScoreLevel) -> None:
    ev = score("hybrid", CHICKEN_MEAL, level)
    assert ev.score is not None
    assert sum(c.contribution or 0 for c in ev.components) == pytest.approx(ev.score)
    weights = response("hybrid").loam_score_profile.by_phase[0].weights_exact
    by_key: dict[str, float] = {}
    for c in ev.components:
        by_key[c.weight_key] = by_key.get(c.weight_key, 0) + c.weight
    assert by_key == pytest.approx({k: weights[k] for k in by_key})


def test_rd_set_carbs_are_left_out_for_t2d() -> None:
    ev = score("glp1_t2d_strength", CHICKEN_MEAL)
    assert ("carb", "disabled") in {(o.id, o.reason) for o in ev.left_out}
    assert "carb" not in {c.weight_key for c in ev.components}


def test_every_part_is_explained() -> None:
    kb = load_kb()
    ev = score("marathon_fatloss", CHICKEN_MEAL, level="day")
    assert ev.provenance == "recommended" and ev.why and ev.rule_ids
    for c in ev.components:
        assert c.provenance == "recommended" and c.why and c.rule_ids
    missing = [r for r in explain.rule_ids_in(ev) if not explain.has(kb, r, "rule")]
    assert missing == []
    assert explain.banned_phrases_in(ev, kb) == []


def test_is_deterministic() -> None:
    assert score("vegan_muscle", CHICKEN_MEAL) == score("vegan_muscle", CHICKEN_MEAL)


def test_errors() -> None:
    args = (response("maya"), APPLE, load_kb(), load_foods())
    with pytest.raises(ValueError, match="unknown food keys"):
        evaluate(
            response("maya"),
            [ScoreItem(key="nope", grams=1)],
            load_kb(),
            load_foods(),
            level="meal",
            day_type="rest",
        )
    with pytest.raises(ValueError, match="no targets for day type"):
        evaluate(*args, level="meal", day_type="long")
    with pytest.raises(ValueError, match="no phase named"):
        evaluate(*args, level="meal", day_type="rest", phase="nope")
    with pytest.raises(ValueError, match="no Loam Score profile"):
        evaluate(
            plan(request("pregnant")), APPLE, load_kb(), load_foods(), level="meal", day_type="rest"
        )
