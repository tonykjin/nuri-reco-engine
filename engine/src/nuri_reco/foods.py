"""Stage 6: food ranking (spec §7.4 pipeline, §7.2 weights, §9 hard constraints).

1. Hard filters: allergens (incl. derived ingredients), celiac, diet, religious; pre-race
   exclusions.
2. Pattern lens: boost the selected pattern's food groups.
3. Goal score: 7.2 weights for the phase's goal and meal slot, condition goals stacked in;
   attributes normalized 0-1 within the food's group.
4. Taste re-rank: only inside the top health-scored set, blended small, so taste is never the
   primary sort (PRD §7.3); neutral without taste data; dislikes down-weighted.
5. Context boosts: Virtual Pantry, NIR "peaks tonight", gaps in today's remaining targets.
6. Diversity: one food per base name, a cap per group.
7. Explain: why chips.

rank() is pure; every number comes from food_weights.yaml and constraints.yaml.
"""

import functools
import json
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from nuri_reco import explain
from nuri_reco.kb import KnowledgeBase, Rule
from nuri_reco.models import Constraints, FoodContext, Preferences
from nuri_reco.models.response import FoodRecommendation, Phase, PlanResponse

FOODS_JSON = Path(__file__).resolve().parents[2] / "data" / "foods.json"
Food = dict[str, Any]


@functools.cache
def load_foods(path: Path = FOODS_JSON) -> tuple[Food, ...]:
    """The engine's food table (built by data/build_foods.py)."""
    foods: list[Food] = json.loads(path.read_text(encoding="utf-8"))["foods"]
    return tuple(foods)


def _x(rule: Rule) -> dict[str, Any]:
    return rule.model_extra or {}


def _params(kb: KnowledgeBase) -> dict[str, dict[str, Any]]:
    return {r.id: _x(r) for r in kb.food_weights.ranking_params}


def _text(food: Food) -> str:
    return str(food["description"]).lower()


def _kcal(food: Food) -> float | None:
    kcal = food["per_100g"]["energy_kcal"]
    return None if kcal is None else float(kcal)


def _share_of_energy(food: Food, nutrient: str, kcal_per_g: float) -> float | None:
    kcal, grams = _kcal(food), food["per_100g"][nutrient]
    if kcal is None or grams is None:
        return None
    return 0.0 if kcal == 0 else float(grams) * kcal_per_g / kcal


# --- 1. Hard filters (§9) ---


def _excluded_by_constraints(food: Food, constraints: Constraints, kb: KnowledgeBase) -> list[str]:
    """Constraint rule ids that exclude the food (empty = allowed)."""
    rules = {r.id: _x(r) for r in kb.constraints.rules}
    allergens, celiac = rules["CONSTRAINT.ALLERGENS"], rules["CONSTRAINT.CELIAC"]
    tags, text, diet = set(food["allergens"]), _text(food), food["diet"]
    hits: list[str] = []

    needs_gluten_free = constraints.celiac
    for entry in constraints.allergens:
        term = entry.strip().lower()
        if term in celiac["allergen_aliases"]:
            needs_gluten_free = True
            continue
        tag = allergens["vocabulary"].get(term)
        if (tag is not None and tag in tags) or (tag is None and term in text):
            hits.append("CONSTRAINT.ALLERGENS")
    if needs_gluten_free and not diet[celiac["requires_diet_tag"]]:
        hits.append("CONSTRAINT.CELIAC")

    diet_tag = rules["CONSTRAINT.ETHICAL"]["diet_tags"].get((constraints.diet or "").lower())
    if diet_tag and not diet[diet_tag]:
        hits.append("CONSTRAINT.ETHICAL")

    religious = rules["CONSTRAINT.RELIGIOUS"]["rules"]
    for name in constraints.religious:
        rule = religious.get(name.strip().lower().replace(" ", "_"))
        if rule is None:
            continue
        if (
            (rule.get("require_diet_tag") and not diet[rule["require_diet_tag"]])
            or tags & set(rule.get("exclude_allergens", []))
            or food["group"] in rule.get("exclude_groups", [])
            or any(k in text for k in rule.get("exclude_keywords", []))
        ):
            hits.append("CONSTRAINT.RELIGIOUS")
    return hits


def _excluded_pre_race(food: Food, p: dict[str, Any]) -> bool:
    """High-fiber or high-fat (or unknown) foods are out 1-4 h before and during a session."""
    kcal = _kcal(food)
    if kcal == 0:
        return False
    fiber = food["attributes"]["fiber_g_per_100kcal"]
    fat_share = _share_of_energy(food, "fat_g", 9)
    return (
        fiber is None
        or fiber >= p["high_fiber_g_per_100kcal"]
        or fat_share is None
        or fat_share * 100 > p["high_fat_pct_energy"]
    )


# --- 3. Goal score (§7.2) ---


def _attribute(food: Food, source: dict[str, Any]) -> float | None:
    field = source["field"]
    if field == "unsaturated_fat":
        fat, sat = food["per_100g"]["fat_g"], food["per_100g"]["sat_fat_g"]
        value = None if fat is None or sat is None else max(fat - sat, 0.0)
    elif field in ("nova", "group"):
        return None  # categorical, handled by the caller
    else:
        section, key = field.split(".")
        value = food[section][key]
    if value is None:
        return None
    if source.get("per_100kcal"):
        kcal = _kcal(food)
        return None if not kcal else float(value) / kcal * 100
    return float(value)


class _Normalizer:
    """Min-max per attribute within each food group (spec §7.2), blended with the range across all
    foods so the best food of a weak group doesn't score like the best food overall."""

    def __init__(self, foods: Sequence[Food], sources: dict[str, Any], group_share: float) -> None:
        self._share = group_share
        self._range: dict[tuple[str, str], tuple[float, float]] = {}
        for name, source in sources.items():
            if source["field"] in ("nova", "group"):
                continue
            by_group: dict[str, list[float]] = {}
            for f in foods:
                v = _attribute(f, source)
                if v is not None:
                    by_group.setdefault(f["group"], []).append(v)
            for group, values in by_group.items():
                self._range[(name, group)] = (min(values), max(values))
            every = [v for values in by_group.values() for v in values]
            if every:
                self._range[(name, "*")] = (min(every), max(every))

    def _scaled(self, name: str, group: str, value: float) -> float:
        low, high = self._range.get((name, group), (value, value))
        return 0.5 if high == low else min(max((value - low) / (high - low), 0.0), 1.0)

    def __call__(self, name: str, food: Food, value: float) -> float:
        within = self._scaled(name, food["group"], value)
        return self._share * within + (1 - self._share) * self._scaled(name, "*", value)


def _row_score(
    food: Food,
    up: list[dict[str, Any]],
    scoring: dict[str, Any],
    attrs: dict[str, Any],
    norm: _Normalizer,
) -> float | None:
    total = weight_sum = 0.0
    for item in up:
        name = item["attribute"]
        if name in attrs["neutral"]:
            continue
        w = scoring["strength"][item.get("strength", "")]
        if name == "nova":
            score = 1.0 if food["nova"] == item.get("value", 1) else 0.0
        elif name == "dash_groups":
            score = 1.0 if food["group"] in attrs["dash_groups"] else 0.0
        else:
            source = attrs["sources"].get(name)
            value = _attribute(food, source) if source else None
            if value is None:
                continue  # missing stays missing: skipped, never scored as 0
            score = norm(name, food, value)
            if item.get("direction") == "low":
                score = 1 - score
        total += w * score
        weight_sum += w
    return total / weight_sum if weight_sum else None


def _rows(
    plan: PlanResponse, context: FoodContext, kb: KnowledgeBase
) -> tuple[Rule | None, list[Rule], str | None, bool]:
    """The 7.2 rows for the context: meal-slot row first, then the day type's (FOOD.RANK.DAY_TYPE),
    then the phase goal's. The last value says whether the day type chose the row."""
    p = _params(kb)
    scoring, by_day = p["FOOD.RANK.SCORING"], p["FOOD.RANK.DAY_TYPE"]
    phase = _phase(plan, context.phase)
    goals = {g.type for g in plan.goal_summary.goals}
    row_id = scoring["slot_rows"].get(context.meal_slot)
    day_row = False
    if row_id is None and context.day_type in by_day["day_types"]:
        if goals & set(by_day["goal_types"]):
            row_id, day_row = by_day["row_rule_ids"][0], True
    if row_id is None and phase is not None:
        row_id = scoring["owner_rows"].get(phase.energy_owner)
    conditions = [
        kb.rules[scoring["condition_rows"][g]] for g in scoring["condition_goals"] if g in goals
    ]
    primary = kb.rules[row_id] if row_id else None
    return primary, conditions, phase.energy if phase else None, day_row


def _phase(plan: PlanResponse, name: str | None) -> Phase | None:
    if name is None:
        return plan.phases[0] if plan.phases else None
    for phase in plan.phases:
        if phase.name == name:
            return phase
    raise ValueError(f"no phase named {name!r}; expected one of {[p.name for p in plan.phases]}")


def _penalties(
    food: Food, primary: Rule | None, conditions: list[Rule], p: dict[str, Any]
) -> float:
    text, kcal, penalty = _text(food), _kcal(food) or 0.0, 0.0
    ed = food["attributes"]["energy_density_kcal_per_g"]
    if primary is not None and primary.id == "FOOD.W.FAT_LOSS":
        if ed is not None and ed > _x(primary)["measured_portions_ed_above"]:
            penalty += p["high_energy_density_penalty"]
        if food["group"] in p["liquid_groups"] and kcal > 0:
            penalty += p["liquid_calories_penalty"]
    ids = {c.id for c in conditions}
    if "FOOD.W.T2D" in ids and any(
        k in text for k in p["sugary_drink_keywords"] + p["refined_grain_keywords"]
    ):
        penalty += p["t2d_penalty"]
    if "FOOD.W.GLP1" in ids and any(k in text for k in p["glp1_keywords"]):
        penalty += p["glp1_penalty"]
    return penalty


# --- 4. Taste (PRD taste dimensions, proxies) ---


def _taste(food: Food, prefs: dict[str, float], t: dict[str, Any]) -> float:
    if not prefs:
        return float(t["neutral"])
    text = _text(food)
    proxies: dict[str, float | None] = {
        "sweetness": _share_of_energy(food, "sugars_g", 4),
        "richness": _share_of_energy(food, "fat_g", 9),
        "umami": 1.0
        if food["group"] in t["umami_groups"] or any(k in text for k in t["umami_keywords"])
        else 0.0,
        "bitterness": 1.0 if any(k in text for k in t["bitter_keywords"]) else 0.0,
    }
    diffs = [
        abs(v - min(proxies[d] or 0.0, 1.0)) for d, v in prefs.items() if proxies.get(d) is not None
    ]
    return 1 - sum(diffs) / len(diffs) if diffs else float(t["neutral"])


# --- 7. Explain ---


def _chips(kb: KnowledgeBase, food: Food, slot: str, c: dict[str, Any]) -> list[str]:
    a, chips = food["attributes"], []

    def chip(variant: str, **values: Any) -> str:
        return explain.text(kb, "FOOD.RANK.CHIPS", variant, **values)

    if slot in ("pre_race", "during"):
        chips.append(chip("fueling"))
    if (a["protein_g_per_100kcal"] or 0) >= c["protein_min"]:
        chips.append(chip("protein", value=a["protein_g_per_100kcal"]))
    if (a["fiber_g_per_100kcal"] or 0) >= c["fiber_min"]:
        chips.append(chip("fiber", value=a["fiber_g_per_100kcal"]))
    ed = a["energy_density_kcal_per_g"]
    if ed is not None and 0 < ed < c["low_energy_density_below"]:
        chips.append(chip("low_energy_density"))
    if a["gi"] is not None and a["gi"] <= c["low_gi_max"]:
        chips.append(chip("low_gi"))
    return chips[: c["max_chips"]]


def _pattern_name(kb: KnowledgeBase, pattern: str) -> str:
    """The pattern's display name (patterns.yaml), e.g. low_gi -> Low-GI / low-GL."""
    names = {p.pattern: p.name for p in kb.patterns.patterns}
    return names.get(pattern, pattern.replace("_", " "))


def base_name(food: Food, heads: list[str]) -> str:
    words = [w.strip().lower() for w in str(food["description"]).split(",")]
    return " ".join(words[:2]) if words[0] in heads and len(words) > 1 else words[0]


def rank(
    context: FoodContext,
    plan: PlanResponse,
    preferences: Preferences,
    constraints: Constraints,
    kb: KnowledgeBase,
    foods: Sequence[Food],
    *,
    limit: int | None = None,
) -> list[FoodRecommendation]:
    """The top foods for this plan and context, each with why chips, rule_ids and provenance.
    `limit` overrides the default top N (food_weights.yaml)."""
    p = _params(kb)
    scoring, attrs, pen = (
        p["FOOD.RANK.SCORING"],
        p["FOOD.RANK.ATTRIBUTES"],
        p["FOOD.RANK.PENALTIES"],
    )
    lens_p, taste_p, ctx_p = (
        p["FOOD.RANK.PATTERN_LENS_GROUPS"],
        p["FOOD.RANK.TASTE"],
        p["FOOD.RANK.CONTEXT"],
    )
    div_p, chips_p = p["FOOD.RANK.DIVERSITY_RULES"], p["FOOD.RANK.CHIPS"]
    pre_race = context.meal_slot in ("pre_race", "during")

    known = {f["key"] for f in foods}
    unknown = [item.key for item in context.pantry if item.key not in known]
    if unknown:
        raise ValueError(f"unknown pantry food keys {unknown}")

    # 1. Hard filters.
    candidates: list[Food] = []
    constraint_ids: set[str] = set()
    for f in foods:
        kcal = _kcal(f)
        if kcal is None or kcal < scoring["min_kcal_per_100g"]:
            continue  # not a food to recommend (water, coffee, tea) or energy unknown
        hits = _excluded_by_constraints(f, constraints, kb)
        constraint_ids |= set(hits)
        if not hits and not (pre_race and _excluded_pre_race(f, p["FOOD.RANK.PRE_RACE"])):
            candidates.append(f)

    # 2-3. Goal score with the pattern lens and down-weights.
    primary, conditions, energy, day_row = _rows(plan, context, kb)
    up = list(_x(primary)["up"]) if primary else list(scoring["default_up"])
    if primary is not None and primary.id == "FOOD.W.MUSCLE" and energy == "surplus":
        up.append({"attribute": "energy_density", "strength": ""})  # ED flips positive in a surplus
    norm = _Normalizer(foods, attrs["sources"], scoring["group_share"])
    lens = (
        {g: lens_p["top_boost"] for g in lens_p["groups"].get(plan.patterns[0].id, [])}
        if plan.patterns
        else {}
    )
    for alt in plan.patterns[1:]:
        for g in lens_p["groups"].get(alt.id, []):
            lens.setdefault(g, lens_p["alternate_boost"])

    health: dict[str, float] = {}
    for f in candidates:
        goal = _row_score(f, up, scoring, attrs, norm) or 0.0
        cond_scores = [
            s
            for c in conditions
            if (s := _row_score(f, _x(c)["up"], scoring, attrs, norm)) is not None
        ]
        if cond_scores:
            share = scoring["condition_share"]
            goal = (1 - share) * goal + share * sum(cond_scores) / len(cond_scores)
        health[f["key"]] = (
            goal + lens.get(f["group"], 0.0) - _penalties(f, primary, conditions, pen)
        )

    # 4. Taste re-rank inside the health-scored set only (never the first sort).
    prefs = {k: v for k, v in preferences.taste.items()}
    top_health = set(sorted(health, key=lambda k: (-health[k], k))[: taste_p["health_set"]])
    dislikes = [d.lower() for d in preferences.dislikes]
    blend = taste_p["blend"]
    final: dict[str, float] = {}
    by_key = {f["key"]: f for f in candidates}
    for key, h in health.items():
        f = by_key[key]
        taste = _taste(f, prefs, taste_p) if key in top_health else taste_p["neutral"]
        score = (1 - blend) * h + blend * taste
        if any(d in _text(f) for d in dislikes):
            score -= taste_p["dislike_penalty"]
        final[key] = score

    # 5. Context boosts.
    pantry = {item.key: item for item in context.pantry}
    rem = context.remaining
    boosted: set[str] = set()
    for key in final:
        f, bonus = by_key[key], 0.0
        if key in pantry:
            bonus += ctx_p["pantry_boost"]
            if pantry[key].peaks_tonight or pantry[key].ripeness == "peak":
                bonus += ctx_p["peak_boost"]
        if rem is not None:
            gaps = ctx_p["gap_minimums"]
            for field, attr in (
                ("protein_g", "protein_density"),
                ("fiber_g", "fiber_density"),
                ("carb_g", "carb_density"),
            ):
                remaining = getattr(rem, field)
                value = _attribute(f, attrs["sources"][attr])
                if remaining is not None and remaining >= gaps[field] and value is not None:
                    bonus += ctx_p["gap_boost"] * norm(attr, f, value)
            ed = f["attributes"]["energy_density_kcal_per_g"]
            if rem.kcal is not None and rem.kcal <= ctx_p["low_kcal_remaining"] and ed is not None:
                bonus += ctx_p["gap_boost"] * (1 - norm("energy_density", f, ed))
        if bonus:
            final[key] += bonus
            boosted.add(key)

    # 6. Diversity, then 7. explain.
    ordered = sorted(final, key=lambda k: (-final[k], k))
    seen_names: set[str] = set()
    per_group: Counter[str] = Counter()
    out: list[FoodRecommendation] = []
    top_n = limit or div_p["top_n"]
    # The group cap is per top-N list; longer lists get proportionally more per group.
    group_cap = div_p["max_per_group"] * max(1, -(-top_n // div_p["top_n"]))
    row_ids = [r.id for r in ([primary] if primary else []) + conditions]
    for key in ordered:
        f = by_key[key]
        name = base_name(f, div_p["two_word_heads"])
        if name in seen_names or per_group[f["group"]] >= group_cap:
            continue
        seen_names.add(name)
        per_group[f["group"]] += 1
        chips = _chips(kb, f, context.meal_slot, chips_p)
        rule_ids = [
            "FOOD.RANK.HARD_FILTERS",
            *sorted(constraint_ids),
            "FOOD.RANK.GOAL_SCORE",
            "FOOD.RANK.SCORING",
            *(["FOOD.RANK.DAY_TYPE"] if day_row else []),
            *row_ids,
        ]
        if pre_race:
            rule_ids.append("FOOD.RANK.PRE_RACE")
        if f["group"] in lens and plan.patterns:
            chips.append(
                explain.text(
                    kb, "FOOD.RANK.CHIPS", "pattern", pattern=_pattern_name(kb, plan.patterns[0].id)
                )
            )
            rule_ids += ["FOOD.RANK.PATTERN_LENS", "FOOD.RANK.PATTERN_LENS_GROUPS"]
        if prefs:
            rule_ids += ["FOOD.RANK.TASTE_RERANK", "FOOD.RANK.TASTE"]
        if key in pantry:
            chips.append(explain.text(kb, "FOOD.RANK.CHIPS", "pantry"))
            if pantry[key].peaks_tonight or pantry[key].ripeness == "peak":
                chips.append(explain.text(kb, "FOOD.RANK.CHIPS", "peak"))
        if key in boosted:
            rule_ids += ["FOOD.RANK.CONTEXT_BOOSTS", "FOOD.RANK.CONTEXT"]
        rule_ids += [
            "FOOD.RANK.DIVERSITY",
            "FOOD.RANK.DIVERSITY_RULES",
            "FOOD.RANK.EXPLAIN",
            "FOOD.RANK.CHIPS",
        ]
        out.append(
            FoodRecommendation(
                key=key,
                fdc_id=f["fdc_id"],
                name=f["description"],
                score=round(min(max(final[key], 0.0), 1.0), 3),
                why=" · ".join(chips) if chips else explain.text(kb, "FOOD.RANK.CHIPS", "why"),
                reasons=chips,
                rule_ids=list(dict.fromkeys(rule_ids)),
            )
        )
        if len(out) == top_n:
            break
    return out
