"""Build engine/data/foods.json from USDA FoodData Central (runbook Task 12, spec §7.1/§7.3/§9).

    uv run python data/build_foods.py              # download if needed, then build
    uv run python data/build_foods.py --offline    # use the cache only

Downloads the Foundation and SR Legacy CSV releases (~10 MB zipped, ~72 MB unzipped) into the
gitignored data/.cache/, plus the few Branded products named in food_list.yaml from the FDC API
(key in FDC_API_KEY, DEMO_KEY otherwise). Writes foods.json: per-100 g nutrients (missing stay
null), Matrix E 7.1 attributes, NRF9.3, GI/GL, NOVA, allergens (top 9, incl. derived ingredients)
and diet tags. Deterministic: same inputs, same file.
"""

import argparse
import csv
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

import yaml

DATA = Path(__file__).resolve().parent
CACHE = DATA / ".cache"
FDC_DOWNLOADS = "https://fdc.nal.usda.gov/fdc-datasets/"
FDC_API = "https://api.nal.usda.gov/fdc/v1/foods"
NEEDED_CSVS = ("food.csv", "food_nutrient.csv")

# FDC nutrient ids per output field. The first id with a value wins (energy: Atwater specific,
# then general, then the legacy 1008 that SR Legacy uses).
NUTRIENTS: dict[str, tuple[int, ...]] = {
    "energy_kcal": (2048, 2047, 1008),
    "protein_g": (1003,),
    "fat_g": (1004,),
    "carb_g": (1005,),
    "fiber_g": (1079,),
    "sugars_g": (2000, 1063),
    "added_sugars_g": (1235,),
    "sat_fat_g": (1258,),
    "sodium_mg": (1093,),
    "potassium_mg": (1092,),
    "iron_mg": (1089,),
    "calcium_mg": (1087,),
    "vitamin_d_ug": (1114,),
    "magnesium_mg": (1090,),
    "b12_ug": (1178,),
    "folate_dfe_ug": (1190,),
    "leucine_g": (1213,),
    "vitamin_a_rae_ug": (1106,),
    "vitamin_c_mg": (1162,),
    "vitamin_e_mg": (1109,),
}
FOOD_FOLATE, FOLIC_ACID = 1187, 1186


def load_yaml(name: str) -> Any:
    return yaml.safe_load((DATA / name).read_text(encoding="utf-8"))


# --- Downloads ---


def dataset_dir(release: str, offline: bool) -> Path:
    """Unzipped CSV folder for an FDC release, downloading it on first use."""
    target = CACHE / release
    if all((target / name).exists() for name in NEEDED_CSVS):
        return target
    archive = CACHE / f"{release}.zip"
    if not archive.exists():
        if offline:
            raise SystemExit(f"{archive.name} isn't cached; run without --offline")
        CACHE.mkdir(parents=True, exist_ok=True)
        print(f"downloading {archive.name} ...")
        urllib.request.urlretrieve(FDC_DOWNLOADS + archive.name, archive)
    with zipfile.ZipFile(archive) as zf:
        for member in zf.namelist():
            if Path(member).name in NEEDED_CSVS:
                (target / Path(member).name).parent.mkdir(parents=True, exist_ok=True)
                (target / Path(member).name).write_bytes(zf.read(member))
    return target


def read_csv_dataset(
    folder: Path, fdc_ids: set[int]
) -> tuple[dict[int, str], dict[int, dict[int, float]]]:
    descriptions: dict[int, str] = {}
    with open(folder / "food.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            fid = int(row["fdc_id"])
            if fid in fdc_ids:
                descriptions[fid] = row["description"]
    amounts: dict[int, dict[int, float]] = {fid: {} for fid in descriptions}
    with open(folder / "food_nutrient.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            fid = int(row["fdc_id"])
            if fid in amounts and row["amount"] not in ("", None):
                amounts[fid][int(row["nutrient_id"])] = float(row["amount"])
    return descriptions, amounts


def fetch_branded(fdc_ids: list[int], offline: bool) -> dict[int, dict[str, Any]]:
    """Branded products from the FDC API (one batched request), cached as JSON."""
    if not fdc_ids:
        return {}
    cache = CACHE / f"branded_{'_'.join(map(str, sorted(fdc_ids)))}.json"
    if not cache.exists():
        if offline:
            raise SystemExit(f"{cache.name} isn't cached; run without --offline")
        key = os.environ.get("FDC_API_KEY", "DEMO_KEY")
        query = urllib.parse.urlencode(
            {"fdcIds": ",".join(map(str, fdc_ids)), "format": "full", "api_key": key}
        )
        print(f"fetching {len(fdc_ids)} branded foods from the FDC API ...")
        try:
            with urllib.request.urlopen(f"{FDC_API}?{query}", timeout=60) as resp:
                CACHE.mkdir(parents=True, exist_ok=True)
                cache.write_bytes(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                raise SystemExit(
                    "FDC API rate limit reached. Get a free key at https://api.data.gov/signup/ "
                    "and set FDC_API_KEY (DEMO_KEY allows only a few requests a day)."
                ) from e
            raise
    foods = json.loads(cache.read_text(encoding="utf-8"))
    return {int(f["fdcId"]): f for f in foods}


def branded_amounts(food: dict[str, Any]) -> dict[int, float]:
    """Branded foodNutrients amounts are per 100 g."""
    out: dict[int, float] = {}
    for n in food.get("foodNutrients", []):
        nid = (n.get("nutrient") or {}).get("id")
        if nid is not None and n.get("amount") is not None:
            out[int(nid)] = float(n["amount"])
    return out


# --- Per-food computation ---


def per_100g(amounts: dict[int, float]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for field, ids in NUTRIENTS.items():
        out[field] = next((amounts[i] for i in ids if i in amounts), None)
    if out["folate_dfe_ug"] is None and FOOD_FOLATE in amounts and FOLIC_ACID in amounts:
        out["folate_dfe_ug"] = amounts[FOOD_FOLATE] + 1.7 * amounts[FOLIC_ACID]
    # Carbohydrate "by difference" (100 - water - protein - fat - ash) can come out slightly
    # negative for meat and fish (measurement noise, e.g. -0.7 g); it means none.
    if out["carb_g"] is not None and out["carb_g"] < 0:
        out["carb_g"] = 0.0
    return out


def merged_100g(
    primary: dict[int, float], fallback: dict[int, float] | None, fallback_label: str
) -> tuple[dict[str, float | None], dict[str, str]]:
    """Primary record's values; nutrients it doesn't report come from the fallback record."""
    values = per_100g(primary)
    filled: dict[str, str] = {}
    if fallback is not None:
        backup = per_100g(fallback)
        for field, value in values.items():
            if value is None and backup[field] is not None:
                values[field] = backup[field]
                filled[field] = fallback_label
    return values, filled


def ratio(value: float | None, kcal: float | None, per: float = 100) -> float | None:
    if value is None or not kcal:
        return None
    return value / kcal * per


def nrf93(n: dict[str, float | None], nova: int, cfg: dict[str, Any]) -> float | None:
    kcal = n["energy_kcal"]
    if not kcal:
        return None
    cap = cfg["cap_percent_dv"]
    encourage = [
        min(v / dv * 100, cap)
        for field, dv in cfg["encourage"].items()
        if (v := ratio(n[field], kcal)) is not None
    ]
    if len(encourage) < cfg["min_encourage_available"]:
        return None
    limits = dict(n)
    if limits["added_sugars_g"] is None:
        limits["added_sugars_g"] = (
            0.0 if nova in cfg["added_sugars_zero_for_nova"] else n["sugars_g"]
        )
    limit = [ratio(limits[field], kcal) for field in cfg["limit"]]
    if any(v is None for v in limit):
        return None
    return sum(encourage) - sum(
        v / mrv * 100 for v, mrv in zip(limit, cfg["limit"].values(), strict=True) if v is not None
    )


def words(text: str, keywords: list[str], excepts: list[str]) -> bool:
    for phrase in excepts:
        text = text.replace(phrase, " ")
    return any(re.search(rf"\b{re.escape(k)}(?:s|es)?\b", text) for k in keywords)


def allergens(text: str, contains: list[str], rules: dict[str, Any]) -> list[str]:
    found = {name for name, r in rules.items() if words(text, r["keywords"], r["except"])}
    return sorted(found | set(contains))


def diet_tags(
    group: str, text: str, tags: list[str], explicit_gf: bool | None, rules: dict[str, Any]
) -> dict[str, bool]:
    meat = group in rules["meat_groups"] or words(text, rules["meat_keywords"], [])
    seafood = group in rules["seafood_groups"] or bool(set(tags) & set(rules["seafood_allergens"]))
    animal_product = bool(set(tags) & set(rules["non_vegan_allergens"])) or words(
        text, rules["non_vegan_keywords"], []
    )
    gluten = bool(set(tags) & set(rules["gluten_allergens"])) or words(
        text, rules["gluten_keywords"], ["buckwheat"]
    )
    return {
        "vegan": not (meat or seafood or animal_product),
        "vegetarian": not (meat or seafood),
        "pescatarian": not meat,
        "gluten_free": (not gluten) if explicit_gf is None else explicit_gf,
    }


def r(value: float | None, digits: int = 3) -> float | None:
    return None if value is None else round(value, digits)


def build(offline: bool, skip_branded: bool = False) -> dict[str, Any]:
    food_list = load_yaml("food_list.yaml")
    allergen_rules = load_yaml("allergens.yaml")
    nrf_cfg = load_yaml("nrf93.yaml")
    gi_rows = {row["key"]: row for row in load_yaml("gi_table.yaml")["rows"]}
    foods = food_list["foods"]
    if skip_branded:  # development only: the committed foods.json must include them
        foods = [f for f in foods if f["source"] != "branded"]

    sources: dict[str, tuple[dict[int, str], dict[int, dict[int, float]]]] = {}
    for source, release in food_list["datasets"].items():
        ids = {f["fdc_id"] for f in foods if f["source"] == source}
        if source == "sr_legacy":
            ids |= {f["fallback_fdc_id"] for f in foods if "fallback_fdc_id" in f}
        sources[source] = read_csv_dataset(dataset_dir(release, offline), ids)
    branded = fetch_branded([f["fdc_id"] for f in foods if f["source"] == "branded"], offline)

    unknown_gi = set(gi_rows) - {f["key"] for f in foods}
    if unknown_gi:
        raise SystemExit(f"gi_table.yaml rows for unknown foods: {sorted(unknown_gi)}")

    out = []
    for f in foods:
        ingredients = ""
        if f["source"] == "branded":
            if f["fdc_id"] not in branded:
                raise SystemExit(
                    f"{f['key']}: branded fdc_id {f['fdc_id']} not returned by the API"
                )
            amounts = branded_amounts(branded[f["fdc_id"]])
            ingredients = branded[f["fdc_id"]].get("ingredients") or ""
        else:
            descriptions, all_amounts = sources[f["source"]]
            if f["fdc_id"] not in descriptions:
                raise SystemExit(f"{f['key']}: fdc_id {f['fdc_id']} not in {f['source']}")
            amounts = all_amounts[f["fdc_id"]]
        fallback = None
        if "fallback_fdc_id" in f:
            sr_descriptions, sr_amounts = sources["sr_legacy"]
            if f["fallback_fdc_id"] not in sr_descriptions:
                raise SystemExit(
                    f"{f['key']}: fallback_fdc_id {f['fallback_fdc_id']} not in sr_legacy"
                )
            fallback = sr_amounts[f["fallback_fdc_id"]]
        n, filled = merged_100g(amounts, fallback, f"sr_legacy:{f.get('fallback_fdc_id')}")
        kcal = n["energy_kcal"]
        text = f"{f['description']} {ingredients}".lower()
        tags = allergens(text, f.get("contains", []), allergen_rules["allergens"])

        gi = gi_rows.get(f["key"])
        available_carb = None if n["carb_g"] is None else max(n["carb_g"] - (n["fiber_g"] or 0), 0)
        out.append(
            {
                "key": f["key"],
                "fdc_id": f["fdc_id"],
                "source": f["source"],
                "description": f["description"],
                "group": f["group"],
                "nova": f["nova"],
                "per_100g": {k: r(v) for k, v in n.items()},
                # Nutrients not in the primary record, taken from the fallback record.
                "nutrient_sources": dict(sorted(filled.items())),
                "attributes": {
                    "energy_density_kcal_per_g": r(None if kcal is None else kcal / 100),
                    "protein_g_per_100kcal": r(ratio(n["protein_g"], kcal)),
                    "fiber_g_per_100kcal": r(ratio(n["fiber_g"], kcal)),
                    "nrf93": r(nrf93(n, f["nova"], nrf_cfg), 1),
                    "gi": gi["gi"] if gi else None,
                    "gl_per_100g": r(gi["gi"] * available_carb / 100, 1)
                    if gi and available_carb is not None
                    else None,
                    "gi_source": gi["source"] if gi else None,
                    "gi_verify": gi["verify"] if gi else None,
                },
                "allergens": tags,
                "diet": diet_tags(
                    f["group"], text, tags, f.get("gluten_free"), allergen_rules["diet"]
                ),
            }
        )
    out.sort(key=lambda food: food["key"])
    return {
        "meta": {
            "generated_by": "engine/data/build_foods.py",
            "datasets": food_list["datasets"],
            "branded_fdc_ids": sorted(f["fdc_id"] for f in foods if f["source"] == "branded"),
            "count": len(out),
            "units": "per 100 g edible portion; null = not reported (never 0)",
        },
        "seed_terms": food_list["seed_terms"],
        "foods": out,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--offline", action="store_true", help="use cached downloads only")
    parser.add_argument("--out", type=Path, default=DATA / "foods.json")
    parser.add_argument(
        "--skip-branded", action="store_true", help="development only: leave out API-fetched foods"
    )
    args = parser.parse_args(argv)
    table = build(args.offline, args.skip_branded)
    args.out.write_text(json.dumps(table, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {table['meta']['count']} foods to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
