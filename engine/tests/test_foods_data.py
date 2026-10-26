"""Spot checks on the committed food table (engine/data/foods.json, runbook Task 12).

Runs on the committed file only: no download, so CI stays offline.
"""

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from nuri_reco.kb import load_kb

DATA = Path(__file__).resolve().parents[1] / "data"
TABLE: dict[str, Any] = json.loads((DATA / "foods.json").read_text(encoding="utf-8"))
FOODS: dict[str, dict[str, Any]] = {f["key"]: f for f in TABLE["foods"]}
TOP_9 = {
    "milk",
    "egg",
    "fish",
    "crustacean_shellfish",
    "tree_nuts",
    "peanuts",
    "wheat",
    "soy",
    "sesame",
}


def per100(key: str, field: str) -> Any:
    return FOODS[key]["per_100g"][field]


# --- Size and coverage ---


def test_food_count() -> None:
    assert 300 <= len(FOODS) <= 500
    assert TABLE["meta"]["count"] == len(FOODS) == len(TABLE["foods"])


def test_keys_unique_and_sorted() -> None:
    keys = [f["key"] for f in TABLE["foods"]]
    assert keys == sorted(set(keys))


def test_every_seed_food_is_present() -> None:
    """Every food named in spec §7.3 (knowledge FOOD.SEED.*) maps to foods in the table."""
    seed_terms: dict[str, list[str]] = TABLE["seed_terms"]
    lists = (
        "foods",
        "energy_dense_add_ons",
        "daily",
        "pre_race",
        "during",
        "protein_forward",
        "other",
    )
    for rule in load_kb().food_weights.seed_foods:
        x = rule.model_extra or {}
        for term in (t for name in lists for t in x.get(name, [])):
            assert seed_terms.get(term), f"{rule.id}: no foods for {term!r}"
            missing = [k for k in seed_terms[term] if k not in FOODS]
            assert not missing, f"{term!r}: unknown keys {missing}"


def test_table_matches_food_list() -> None:
    food_list = yaml.safe_load((DATA / "food_list.yaml").read_text(encoding="utf-8"))
    assert {f["key"] for f in food_list["foods"]} == set(FOODS)
    assert TABLE["meta"]["datasets"] == food_list["datasets"]


def test_branded_foods_included() -> None:
    for key in ("energy_gel", "energy_chews", "skyr_plain"):
        assert FOODS[key]["source"] == "branded"
        assert per100(key, "energy_kcal") is not None


def test_committed_file_is_small() -> None:
    # The raw USDA downloads (~72 MB) are cached and gitignored; only this table is committed.
    assert (DATA / "foods.json").stat().st_size < 2_000_000


# --- Runbook spot checks ---


def test_chicken_breast_protein() -> None:
    assert per100("chicken_breast_roasted", "protein_g") == pytest.approx(31, abs=1)


def test_apple_fiber() -> None:
    assert per100("apple", "fiber_g") == pytest.approx(2.4, abs=0.1)


@pytest.mark.parametrize(
    ("key", "allergen"),
    [
        ("peanut_butter", "peanuts"),
        ("whey_protein_isolate", "milk"),  # derived ingredient: whey -> milk
        ("tahini", "sesame"),  # derived ingredient: tahini -> sesame
        ("hummus", "sesame"),
        ("skyr_plain", "milk"),
        ("tofu_firm", "soy"),
        ("shrimp_cooked", "crustacean_shellfish"),
        ("salmon_cooked", "fish"),
        ("bagel_plain", "wheat"),
        ("eggs_grade_a_large_egg_whole", "egg"),
        ("nuts_almonds_whole_raw", "tree_nuts"),
        ("trail_mix", "peanuts"),
        ("oil_peanut", "peanuts"),  # tagged despite the FDA refined-oil exemption (Task 21)
    ],
)
def test_allergen_tags(key: str, allergen: str) -> None:
    assert allergen in FOODS[key]["allergens"]


@pytest.mark.parametrize(
    ("key", "not_allergen"),
    [
        ("peanut_butter", "milk"),  # "butter" in a nut butter isn't dairy
        ("almond_milk_unsweetened_plain_refrigerated", "milk"),
        ("eggplant_raw", "egg"),
        ("squash_winter_butternut_raw", "milk"),
        ("oil_soybean", "soy"),
        ("buckwheat_whole_grain", "wheat"),
    ],
)
def test_no_false_allergens(key: str, not_allergen: str) -> None:
    assert not_allergen not in FOODS[key]["allergens"]


# --- Missing data stays missing ---


def test_missing_nutrients_are_null_not_zero() -> None:
    fields = set(next(iter(FOODS.values()))["per_100g"])
    for f in FOODS.values():
        assert set(f["per_100g"]) == fields
        for value in f["per_100g"].values():
            assert value is None or (isinstance(value, int | float) and value >= 0)
    for field in ("leucine_g", "vitamin_d_ug"):
        assert any(f["per_100g"][field] is None for f in FOODS.values()), field


def test_fallback_values_are_labelled() -> None:
    for f in FOODS.values():
        for field, source in f["nutrient_sources"].items():
            assert f["per_100g"][field] is not None
            assert source.startswith("sr_legacy:")


# --- Derived attributes ---


@pytest.mark.parametrize("key", sorted(FOODS))
def test_derived_attributes(key: str) -> None:
    f = FOODS[key]
    n, a = f["per_100g"], f["attributes"]
    kcal = n["energy_kcal"]
    if kcal is None:
        assert a["energy_density_kcal_per_g"] is None
        return
    assert a["energy_density_kcal_per_g"] == pytest.approx(kcal / 100, abs=1e-3)
    if kcal and n["protein_g"] is not None:
        assert a["protein_g_per_100kcal"] == pytest.approx(n["protein_g"] / kcal * 100, abs=1e-2)
    if kcal and n["fiber_g"] is not None:
        assert a["fiber_g_per_100kcal"] == pytest.approx(n["fiber_g"] / kcal * 100, abs=1e-2)
    assert f["nova"] in (1, 2, 3, 4)
    assert set(f["allergens"]) <= TOP_9
    d = f["diet"]
    assert (not d["vegan"] or d["vegetarian"]) and (not d["vegetarian"] or d["pescatarian"])


def test_gi_and_gl() -> None:
    rice = FOODS["rice_white_cooked"]["attributes"]
    assert rice["gi"] == 73 and rice["gi_verify"] is True
    carbs = per100("rice_white_cooked", "carb_g") - (per100("rice_white_cooked", "fiber_g") or 0)
    assert rice["gl_per_100g"] == pytest.approx(73 * carbs / 100, abs=0.1)
    assert FOODS["chicken_breast_roasted"]["attributes"]["gi"] is None


def test_nrf93_ranks_nutrient_dense_foods_higher() -> None:
    nrf = {
        k: FOODS[k]["attributes"]["nrf93"]
        for k in ("spinach_raw", "broccoli_raw", "cola", "gummy_candy")
    }
    assert all(v is not None for v in nrf.values()), nrf
    assert min(nrf["spinach_raw"], nrf["broccoli_raw"]) > max(nrf["cola"], nrf["gummy_candy"])


# --- Diet tags ---


@pytest.mark.parametrize(
    ("key", "vegan", "vegetarian", "pescatarian", "gluten_free"),
    [
        ("tofu_firm", True, True, True, True),
        ("honey", False, True, True, True),
        ("salmon_cooked", False, False, True, True),
        ("chicken_breast_roasted", False, False, False, True),
        ("broth_chicken", False, False, False, True),
        ("pizza_cheese", False, True, True, False),
        ("oatmeal_cooked", True, True, True, False),  # non-certified oats (spec §9)
        ("corn_flakes", True, True, True, False),  # malt flavoring
        ("rice_white_cooked", True, True, True, True),
    ],
)
def test_diet_tags(
    key: str, vegan: bool, vegetarian: bool, pescatarian: bool, gluten_free: bool
) -> None:
    assert FOODS[key]["diet"] == {
        "vegan": vegan,
        "vegetarian": vegetarian,
        "pescatarian": pescatarian,
        "gluten_free": gluten_free,
    }
