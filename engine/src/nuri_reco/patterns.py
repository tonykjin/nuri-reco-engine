"""Stage 5: diet-pattern ranking (spec §6, Matrix D selection algorithm).

1. Eligible: patterns whose best-fit goals meet the plan's goals (or that the user asked for),
   minus Matrix F exclusions and hard constraints (diet). MIND is never offered.
2. Evidence prior: evidence grade and AHA tier.
3. Adherence: Matrix D baseline adjusted for cuisines, current diet, taste, budget, cooking time,
   dislikes and pattern_pref. Weighted highest.
4. Rank (first-line patterns for a goal go first) and explain: top pattern + up to 2 alternates.

Pure; every parameter comes from patterns.yaml.
"""

from typing import Any

from nuri_reco.kb import KnowledgeBase, PatternRule, Rule
from nuri_reco.models import Constraints, Preferences
from nuri_reco.models.response import PatternRecommendation, PlanResponse
from nuri_reco.safety import SafetyResult


def _x(rule: Rule) -> dict[str, Any]:
    return rule.model_extra or {}


def _evidence(pattern: PatternRule, diet: str | None, params: dict[str, Any]) -> float:
    x = _x(pattern)
    grade = params["grade"][x["evidence_grade"]]
    tier_raw = x.get("aha_tier")
    if tier_raw is None:
        tier = params["tier_unrated"]
    elif isinstance(tier_raw, list):
        tier = sum(params["tier"][t] for t in tier_raw) / len(tier_raw)
    elif isinstance(tier_raw, dict):
        # Vegetarian/vegan: lacto-ovo tier 1, vegan tier 2.
        key = diet if diet in tier_raw else next(iter(tier_raw))
        tier = params["tier"][tier_raw[key]]
    else:
        tier = params["tier"][tier_raw]
    return float(params["grade_share"] * grade + params["tier_share"] * tier)


def _adherence(
    pattern: str, preferences: Preferences, constraints: Constraints, p: dict[str, Any]
) -> tuple[float, list[str]]:
    """Adherence score and the reasons (copy keys) that raised it."""
    score = p["baseline"][pattern]
    reasons: list[str] = []
    cuisines = {c.lower() for c in preferences.cuisines}
    if cuisines & set(p["cuisines"].get(pattern, [])):
        score += p["cuisine_match"]
        reasons.append("cuisine")
    if constraints.diet and constraints.diet in p["follows"].get(pattern, []):
        score += p["diet_match"]
        reasons.append("follows")
    if preferences.pattern_pref == pattern:
        score += p["pattern_pref"]
        reasons.append("pattern_pref")
    tags = set(p["taste_tags"].get(pattern, []))
    liked = [d for d, v in preferences.taste.items() if v >= p["taste_threshold"] and d in tags]
    score += min(p["taste_match"] * len(liked), p["taste_match_max"])
    if (preferences.budget or "").lower() == "low" and pattern in p["costly"]:
        score -= p["budget_penalty"]
    if (
        preferences.cook_time_min is not None
        and preferences.cook_time_min <= p["quick_cook_minutes"]
    ):
        if pattern in p["cook_heavy"]:
            score -= p["cook_time_penalty"]
    dislikes = [d.lower() for d in preferences.dislikes]
    hits = sum(
        1
        for food in p["signature_foods"].get(pattern, [])
        if any(food in d or d in food for d in dislikes)
    )
    score -= min(p["dislike_penalty"] * hits, p["dislike_penalty_max"])
    return max(score, 0.0), reasons


def rank(
    plan: PlanResponse,
    preferences: Preferences,
    constraints: Constraints,
    safety: SafetyResult,
    kb: KnowledgeBase,
) -> list[PatternRecommendation]:
    """Top diet pattern and up to two alternates for this plan, each with rule_ids and a why."""
    rules = {r.id: _x(r) for r in kb.patterns.selection}
    goal_map = rules["PATTERN.SELECT.GOAL_MAP"]["goals"]
    diet_fit = rules["PATTERN.SELECT.DIET_FIT"]
    matrix_f = rules["PATTERN.SELECT.MATRIX_F"]
    first_line_rule = rules["PATTERN.SELECT.FIRST_LINE"]
    weights = rules["PATTERN.SCORE.WEIGHTS"]
    evidence_params = rules["PATTERN.SCORE.EVIDENCE"]
    adherence_params = rules["PATTERN.SCORE.ADHERENCE"]
    alternates = rules["PATTERN.SELECT.RANK_EXPLAIN"]["alternates"]["max"]

    goals = {g.type for g in plan.goal_summary.goals}
    excluded = set(safety.excluded_pattern_ids)
    if "carb_restriction" in safety.restricted("rd_approval_required"):
        excluded |= {
            p.id for p in kb.patterns.patterns if p.pattern in matrix_f["carb_restricting_patterns"]
        }
    plant_only = constraints.diet in diet_fit["plant_based_diets"]
    first_line = {pat for g in goals for pat in first_line_rule["first_line"].get(g, [])}

    scored: list[tuple[bool, float, int, PatternRule, list[str]]] = []
    for order, pattern in enumerate(kb.patterns.patterns):
        if not pattern.offered or pattern.id in excluded:
            continue
        asked = preferences.pattern_pref == pattern.pattern
        follows = constraints.diet in adherence_params["follows"].get(pattern.pattern, [])
        if not (goals & set(goal_map.get(pattern.pattern, [])) or asked or follows):
            continue
        if plant_only and pattern.pattern not in diet_fit["plant_based_patterns"]:
            continue
        evidence = _evidence(pattern, constraints.diet, evidence_params)
        adherence, reasons = _adherence(pattern.pattern, preferences, constraints, adherence_params)
        raw = weights["evidence"] * evidence + weights["adherence"] * adherence
        scored.append((pattern.pattern in first_line, raw, order, pattern, reasons))

    scored.sort(key=lambda s: (not s[0], -s[1], s[2]))
    copy = _x(kb.rules["PATTERN.SCORE.ADHERENCE"]).get("copy", {})
    out = []
    for is_first_line, raw, _, pattern, reasons in scored[: 1 + alternates]:
        why = [_x(pattern)["why"]]
        rule_ids = [
            pattern.id,
            "PATTERN.SELECT.ELIGIBLE",
            "PATTERN.SELECT.GOAL_MAP",
            "PATTERN.SCORE.WEIGHTS",
        ]
        if is_first_line:
            why.insert(0, first_line_rule["copy"]["why"])
            rule_ids.append("PATTERN.SELECT.FIRST_LINE")
        why += [copy[r] for r in reasons if r in copy]
        if plant_only:
            rule_ids.append("PATTERN.SELECT.DIET_FIT")
        out.append(
            PatternRecommendation(
                id=pattern.pattern,
                score=round(min(raw, 1.0), 3),
                rule_ids=rule_ids,
                why=" ".join(why),
            )
        )
    return out
