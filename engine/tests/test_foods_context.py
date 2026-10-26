"""Food ranking by phase, day type and pantry (Task 24; spec §7.4, FOOD.RANK.DAY_TYPE)."""

import json
from functools import cache
from pathlib import Path
from typing import get_args

import pytest

from nuri_reco.engine import plan
from nuri_reco.foods import load_foods, rank
from nuri_reco.kb import load_kb
from nuri_reco.models import (
    DayType,
    FoodContext,
    FoodRecommendation,
    PlanRequest,
    PlanResponse,
)
from nuri_reco.models.food import MealSlot, PantryItem

PERSONAS = Path(__file__).parent / "personas"
BANANA = "bananas_ripe_and_slightly_ripe_raw"


def request(name: str) -> PlanRequest:
    raw = json.loads((PERSONAS / f"{name}.json").read_text(encoding="utf-8"))
    raw.pop("expect")
    return PlanRequest.model_validate(raw)


@cache
def response(name: str) -> PlanResponse:
    return plan(request(name))


def ranked(name: str, limit: int = 10, **context: object) -> list[FoodRecommendation]:
    req = request(name)
    return rank(
        FoodContext.model_validate(context),
        response(name),
        req.preferences,
        req.constraints,
        load_kb(),
        load_foods(),
        limit=limit,
    )


def keys(recs: list[FoodRecommendation]) -> list[str]:
    return [r.key for r in recs]


# --- Day type (runbook Task 24: "long" moves the marathoner toward fueling foods) ---


def test_hard_days_rank_with_the_fueling_row() -> None:
    rest = ranked("marathon_fatloss", day_type="rest")
    long = ranked("marathon_fatloss", day_type="long")
    assert keys(rest) != keys(long)
    assert all("FOOD.RANK.DAY_TYPE" in r.rule_ids for r in long)
    assert all("FOOD.W.ENDURANCE_DAILY" in r.rule_ids for r in long)
    assert all("FOOD.RANK.DAY_TYPE" not in r.rule_ids for r in rest)
    assert all("FOOD.W.FAT_LOSS" in r.rule_ids for r in rest)


def test_long_day_brings_in_carb_dense_foods() -> None:
    foods = {f["key"]: f for f in load_foods()}

    def carb_share(recs: list[FoodRecommendation]) -> float:
        per = [foods[r.key]["per_100g"] for r in recs]
        return sum(p["carb_g"] * 4 / p["energy_kcal"] for p in per) / len(per)

    rest = ranked("marathon_fatloss", day_type="rest")
    long = ranked("marathon_fatloss", day_type="long")
    assert carb_share(long) > carb_share(rest)


def test_without_an_endurance_goal_day_type_keeps_the_phase_row() -> None:
    assert keys(ranked("maya", day_type="quality")) == keys(ranked("maya", day_type="rest"))


def test_meal_slot_rows_still_come_first_on_hard_days() -> None:
    recs = ranked("marathon_fatloss", meal_slot="pre_race", day_type="long")
    assert all("FOOD.W.ENDURANCE_PRE_RACE" in r.rule_ids for r in recs)
    assert all("FOOD.RANK.DAY_TYPE" not in r.rule_ids for r in recs)


# --- Phase ---


def test_phase_selects_the_phase_goal_row() -> None:
    base = ranked("marathon_fatloss", day_type="rest", phase="base")
    peak = ranked("marathon_fatloss", day_type="rest", phase="peak")
    assert keys(base) == keys(ranked("marathon_fatloss", day_type="rest"))
    assert all("FOOD.W.FAT_LOSS" in r.rule_ids for r in base)
    assert all("FOOD.W.ENDURANCE_DAILY" in r.rule_ids for r in peak)


def test_unknown_phase_and_pantry_keys_are_errors() -> None:
    with pytest.raises(ValueError, match="no phase named"):
        ranked("maya", phase="nope")
    with pytest.raises(ValueError, match="unknown pantry food keys"):
        ranked("maya", pantry=[{"key": "banana"}])


# --- Pantry (runbook Task 24: "banana · peaks tonight" moves banana up) ---


@pytest.mark.parametrize("name", ["maya", "marathon_fatloss"])
def test_peaking_pantry_banana_moves_up(name: str) -> None:
    before = keys(ranked(name, limit=100))
    pantry = [PantryItem(key=BANANA, peaks_tonight=True)]
    after = ranked(name, limit=30, pantry=[p.model_dump() for p in pantry])
    assert BANANA in keys(after)
    assert BANANA not in before or keys(after).index(BANANA) < before.index(BANANA)
    banana = next(r for r in after if r.key == BANANA)
    assert {"in your pantry", "peaks tonight"} <= set(banana.reasons)


def test_ripeness_peak_counts_as_peaking() -> None:
    peak = ranked("maya", limit=30, pantry=[{"key": BANANA, "ripeness": "peak"}])
    ripe = ranked("maya", limit=100, pantry=[{"key": BANANA, "ripeness": "ripe"}])
    assert keys(peak).index(BANANA) < keys(ripe).index(BANANA)


# --- Allergens hold under every filter (runbook Task 24) ---


def test_peanut_allergy_holds_in_every_filter() -> None:
    foods = {f["key"]: f for f in load_foods()}
    for slot in get_args(MealSlot):
        for day in get_args(DayType):
            for r in ranked("marathon_fatloss", limit=100, meal_slot=slot, day_type=day):
                assert "peanuts" not in foods[r.key]["allergens"], (slot, day, r.name)
                assert "peanut" not in r.name.lower(), (slot, day, r.name)


def test_patterns_carry_their_display_names() -> None:
    names = {p.pattern: p.name for p in load_kb().patterns.patterns}
    pats = response("maya").patterns
    assert len(pats) == 3
    assert all(p.name == names[p.id] for p in pats)
