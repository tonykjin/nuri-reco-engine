"""Stage 6 food ranking (spec §7.4 pipeline, §7.2 weights, §9 constraints)."""

import itertools
import json
import statistics
from pathlib import Path
from typing import Any, get_args

import pytest

from nuri_reco.engine import plan
from nuri_reco.foods import _excluded_by_constraints, load_foods, rank
from nuri_reco.kb import load_kb
from nuri_reco.models import (
    Constraints,
    DayType,
    FoodContext,
    MealSlot,
    PantryItem,
    PlanRequest,
    Preferences,
    RemainingTargets,
)
from nuri_reco.models.response import PlanResponse

PERSONAS = Path(__file__).parent / "personas"
FOODS = load_foods()
BY_KEY = {f["key"]: f for f in FOODS}


def persona(name: str, **updates: Any) -> PlanRequest:
    raw = json.loads((PERSONAS / f"{name}.json").read_text(encoding="utf-8"))
    raw.pop("expect")
    for section, values in updates.items():
        raw.setdefault(section, {}).update(values)
    return PlanRequest.model_validate(raw)


def run(
    req: PlanRequest, context: FoodContext | None = None, limit: int | None = None
) -> list[str]:
    resp = plan(req, dry_run=True).model_copy(update={"patterns": plan(req).patterns})
    recs = rank(
        context or FoodContext(),
        resp,
        req.preferences,
        req.constraints,
        load_kb(),
        FOODS,
        limit=limit,
    )
    return [r.key for r in recs]


def fat_share(key: str) -> float:
    n = BY_KEY[key]["per_100g"]
    return n["fat_g"] * 9 / n["energy_kcal"] * 100 if n["energy_kcal"] else 0.0


# --- Hard filters: 100% allergen exclusion across every context ---

PEANUT_FOODS = {f["key"] for f in FOODS if "peanuts" in f["allergens"]}
CONTEXTS = [
    FoodContext(
        meal_slot=slot,
        day_type=day,
        pantry=[PantryItem(key="peanut_butter", ripeness="peak", peaks_tonight=True)]
        if pantry
        else [],
        remaining=RemainingTargets(kcal=250, protein_g=40, carb_g=80, fiber_g=10) if gaps else None,
    )
    for slot, day, pantry, gaps in itertools.product(
        get_args(MealSlot), get_args(DayType), (False, True), (False, True)
    )
]


def test_peanut_foods_exist() -> None:
    assert {"peanut_butter", "peanuts_dry_roasted", "trail_mix", "mixed_nuts"} <= PEANUT_FOODS


@pytest.mark.parametrize(
    "context",
    CONTEXTS,
    ids=lambda c: f"{c.meal_slot}-{c.day_type}-{len(c.pantry)}-{bool(c.remaining)}",
)
def test_peanut_allergy_never_sees_peanuts(context: FoodContext) -> None:
    req = persona("marathon_fatloss")
    assert req.constraints.allergens == ["peanuts"]
    got = run(req, context, limit=50)
    assert got and not set(got) & PEANUT_FOODS
    assert not [k for k in got if "peanut" in BY_KEY[k]["description"].lower()]


def test_allergen_filter_covers_the_whole_table() -> None:
    kb = load_kb()
    allowed = [
        f for f in FOODS if not _excluded_by_constraints(f, Constraints(allergens=["peanuts"]), kb)
    ]
    assert not {f["key"] for f in allowed} & PEANUT_FOODS
    assert len(allowed) == len(FOODS) - len(PEANUT_FOODS)


@pytest.mark.parametrize(
    ("constraints", "forbidden"),
    [
        (Constraints(celiac=True), lambda f: not f["diet"]["gluten_free"]),
        (Constraints(allergens=["gluten"]), lambda f: not f["diet"]["gluten_free"]),
        (Constraints(diet="vegan"), lambda f: not f["diet"]["vegan"]),
        (Constraints(diet="vegetarian"), lambda f: not f["diet"]["vegetarian"]),
        (
            Constraints(allergens=["shellfish", "tree nuts"]),
            lambda f: {"crustacean_shellfish", "tree_nuts"} & set(f["allergens"]),
        ),
        (
            Constraints(religious=["halal"]),
            lambda f: any(
                k in f["description"].lower() for k in ("pork", "ham", "bacon", "pepperoni")
            ),
        ),
        (Constraints(religious=["kosher"]), lambda f: f["group"] == "shellfish"),
        (
            Constraints(religious=["jain"]),
            lambda f: (
                any(k in f["description"].lower() for k in ("onion", "potato", "garlic"))
                or "egg" in f["allergens"]
            ),
        ),
        (
            Constraints(allergens=["kiwi"]),
            lambda f: "kiwi" in f["description"].lower(),
        ),  # unknown term: keyword fallback
    ],
)
def test_hard_constraints(constraints: Constraints, forbidden: Any) -> None:
    req = persona("maya").model_copy(update={"constraints": constraints})
    for slot in ("any", "breakfast", "snack"):
        got = run(req, FoodContext(meal_slot=slot), limit=60)
        assert got and not [k for k in got if forbidden(BY_KEY[k])], slot


# --- Pre-race ---


@pytest.mark.parametrize("slot", ["pre_race", "during"])
def test_pre_race_excludes_high_fiber_and_high_fat(slot: str) -> None:
    got = run(persona("marathon_fatloss"), FoodContext(meal_slot=slot, day_type="long"), limit=20)
    assert len(got) >= 10
    for key in got:
        a = BY_KEY[key]["attributes"]
        assert a["fiber_g_per_100kcal"] is not None and a["fiber_g_per_100kcal"] < 3, key
        assert fat_share(key) <= 30, key
    # Classic pre-race carbs are available.
    assert {"bagel_plain", "rice_white_cooked", "pretzels", "honey", "energy_gel"} & set(
        run(persona("marathon_fatloss"), FoodContext(meal_slot=slot), limit=60)
    )


# --- Goal score ---


def test_fat_loss_ranks_low_energy_density_and_high_protein_first() -> None:
    top = run(persona("maya"))[:5]
    ed = [BY_KEY[k]["attributes"]["energy_density_kcal_per_g"] for k in top]
    pd = [BY_KEY[k]["attributes"]["protein_g_per_100kcal"] or 0 for k in top]
    all_ed = [
        f["attributes"]["energy_density_kcal_per_g"]
        for f in FOODS
        if f["attributes"]["energy_density_kcal_per_g"]
    ]
    all_pd = [
        f["attributes"]["protein_g_per_100kcal"]
        for f in FOODS
        if f["attributes"]["protein_g_per_100kcal"]
    ]
    assert max(ed) < 1.5 and statistics.median(ed) < statistics.median(all_ed)
    assert statistics.median(pd) > statistics.median(all_pd)
    assert BY_KEY[top[0]]["attributes"]["protein_g_per_100kcal"] >= 10


def test_fat_loss_penalizes_liquid_calories_and_dense_foods() -> None:
    got = run(persona("maya"), limit=60)
    assert not {
        "cola",
        "orange_juice_no_pulp_not_fortified_from_concentrate_refriger",
        "oil_olive_extra_virgin",
    } & set(got)


def test_muscle_gain_favours_protein_and_leucine() -> None:
    top = run(persona("novice_recomp"))[:5]
    assert all((BY_KEY[k]["per_100g"]["protein_g"] or 0) >= 10 for k in top), top


# --- Context boosts ---


def test_pantry_item_at_peak_ripeness_moves_up() -> None:
    req = persona("maya")
    before = run(req, limit=200)
    pear = "pears_raw_bartlett"
    assert pear in before and before.index(pear) > 10
    pantry = FoodContext(pantry=[PantryItem(key=pear, ripeness="peak", peaks_tonight=True)])
    after = run(req, pantry, limit=200)
    assert after.index(pear) < before.index(pear)
    plain = run(req, FoodContext(pantry=[PantryItem(key=pear)]), limit=200)
    assert after.index(pear) <= plain.index(pear) <= before.index(pear)


def test_protein_gap_lifts_protein_dense_foods() -> None:
    req = persona("glp1_t2d_strength")
    base = run(req, limit=10)
    gap = run(req, FoodContext(remaining=RemainingTargets(protein_g=60)), limit=10)

    def pd(keys: list[str]) -> float:
        return statistics.mean(BY_KEY[k]["attributes"]["protein_g_per_100kcal"] or 0 for k in keys)

    assert pd(gap) > pd(base)


# --- Taste re-rank stays inside the health-scored set ---


def test_taste_never_pulls_in_unhealthy_foods() -> None:
    sweet = persona("maya", preferences={"taste": {"sweetness": 1.0, "richness": 1.0}})
    got = run(sweet)
    assert not {
        "gummy_candy",
        "cola",
        "doughnut",
        "cookies_chocolate_chip",
        "ice_cream_vanilla",
    } & set(got)
    neutral = set(run(persona("maya"), limit=50))
    assert set(got) <= neutral  # re-ranked within the health set only


def test_taste_reorders_within_the_set() -> None:
    umami = run(persona("maya", preferences={"taste": {"umami": 1.0}}))
    sweet = run(persona("maya", preferences={"taste": {"sweetness": 1.0}}))
    assert umami != sweet


def test_dislikes_push_foods_down() -> None:
    base = run(persona("maya"))
    assert "fish_pollock_raw" in base
    assert "fish_pollock_raw" not in run(persona("maya", preferences={"dislikes": ["pollock"]}))


# --- Output, diversity, engine wiring ---


def test_recommendations_have_chips_rule_ids_and_provenance() -> None:
    resp: PlanResponse = plan(persona("maya"))
    assert len(resp.foods) == 10
    rules = set(load_kb().rules)
    for f in resp.foods:
        assert f.why and f.provenance == "recommended" and 0 <= f.score <= 1
        assert set(f.rule_ids) <= rules, set(f.rule_ids) - rules
        assert f.key in BY_KEY and f.fdc_id == BY_KEY[f.key]["fdc_id"]
    assert any("g protein per 100 kcal" in f.why for f in resp.foods)


def test_diversity_one_per_base_name_and_group_cap() -> None:
    got = run(persona("maya"), limit=10)
    groups = [BY_KEY[k]["group"] for k in got]
    assert max(groups.count(g) for g in groups) <= 3
    assert sum(1 for k in got if k.startswith("apples_")) <= 1


def test_no_zero_calorie_items() -> None:
    assert not {"water_tap", "coffee_brewed", "tea_black"} & set(run(persona("maya"), limit=100))


def test_dry_run_and_blocked_have_no_foods() -> None:
    assert plan(persona("maya"), dry_run=True).foods == []
    assert plan(persona("under18")).foods == []


def test_rank_is_deterministic() -> None:
    assert run(persona("marathon_fatloss")) == run(persona("marathon_fatloss"))


def test_preferences_default() -> None:
    assert Preferences().taste == {}
