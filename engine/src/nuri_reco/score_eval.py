"""Score a meal or day against a loam_score_profile (Task 23; Loam Score page §4, spec §7b.3).

Each component uses its page formula (adequacy, target range, moderation); the overall score is
the weighted mean over components with data, and coverage reports how much of the weight had
data. At meal level targets are scaled to the meal's share of the day's energy (EVAL.MEAL_SHARE).
Missing nutrients stay missing (invariant 7). Pure; every number comes from the knowledge base.
"""

from collections import Counter
from dataclasses import dataclass
from typing import Any

from nuri_reco import explain
from nuri_reco.kb import KnowledgeBase, Rule
from nuri_reco.models import (
    ComponentScore,
    DayType,
    LeftOut,
    PlanResponse,
    ScoredItem,
    ScoreEvaluation,
    ScoreItem,
    ScoreLevel,
    ScoreTarget,
)
from nuri_reco.models.response import PhaseScoreProfile, ScoreComponent


def _x(rule: Rule) -> dict[str, Any]:
    return rule.model_extra or {}


# --- Loam Score page §4 formulas, each 0-100 ---


def adequacy(actual: float, target: float) -> float:
    return 100 * min(actual / target, 1) if target > 0 else 100


def target_range(actual: float, low: float, high: float) -> float:
    if actual < low:
        return 100 * actual / low
    if actual <= high:
        return 100
    return 100 * high / actual


def moderation(actual: float, limit: float) -> float:
    return 100 if actual <= limit else 100 * limit / actual


def _score(kind: str, actual: float, t: ScoreTarget) -> float:
    if kind == "range" and t.low is not None and t.high is not None:
        return target_range(actual, t.low, t.high)
    if kind == "moderation" and t.max is not None:
        return moderation(actual, t.max)
    if t.min is not None:  # adequacy, and the produce pattern metric
        return adequacy(actual, t.min)
    raise ValueError(f"no target to score a {kind} component against")


def _scaled(t: ScoreTarget, share: float) -> ScoreTarget:
    def s(v: float | None) -> float | None:
        return None if v is None else v * share

    return ScoreTarget(unit=t.unit, low=s(t.low), high=s(t.high), min=s(t.min), max=s(t.max))


@dataclass
class _Part:
    """One scored part: a profile component, or one micronutrient of the panel."""

    id: str
    weight_key: str
    type: str
    target: ScoreTarget
    rule_ids: list[str]
    why: str
    weight: float = 0.0
    actual: float | None = None
    score: float | None = None


# --- Totals ---


class _Totals:
    """Nutrient sums over the items; None when any food lacks the value (invariant 7)."""

    def __init__(self, items: list[tuple[dict[str, Any], float]], kb: KnowledgeBase) -> None:
        self._items = items
        self._n = _x(kb.score_eval.nutrients)

    def field(self, name: str) -> float | None:
        total = 0.0
        for food, grams in self._items:
            value = food["per_100g"].get(name)
            if value is None:
                return None
            total += value * grams / 100
        return total

    def of(self, component: str) -> float | None:
        if component == "produce":
            groups = set(self._n["produce_groups"])
            return sum(g for f, g in self._items if f["group"] in groups)
        return self.field(self._n["fields"][component])


# --- Evaluation ---


def _phase(plan: PlanResponse, phase: str | None) -> PhaseScoreProfile:
    profiles = plan.loam_score_profile.by_phase
    if not profiles:
        raise ValueError("the plan has no Loam Score profile (blocked or awaiting goal order)")
    if phase is None:
        return profiles[0]
    for p in profiles:
        if p.phase == phase:
            return p
    raise ValueError(f"no phase named {phase!r}; expected one of {[p.phase for p in profiles]}")


def evaluate(
    plan: PlanResponse,
    items: list[ScoreItem],
    kb: KnowledgeBase,
    food_table: list[dict[str, Any]],
    *,
    level: ScoreLevel,
    day_type: DayType,
    phase: str | None = None,
) -> ScoreEvaluation:
    """The Loam Score of a meal or day for one phase and day type of the plan."""
    if not items:
        raise ValueError("at least one food is needed")
    profile = _phase(plan, phase)
    plan_phase = next(p for p in plan.phases if p.name == profile.phase)
    if day_type not in plan_phase.targets_by_day_type:
        known = list(plan_phase.targets_by_day_type)
        raise ValueError(f"no targets for day type {day_type!r}; expected one of {known}")
    foods = {f["key"]: f for f in food_table}
    unknown = [i.key for i in items if i.key not in foods]
    if unknown:
        raise ValueError(f"unknown food keys {unknown}")

    e = kb.score_eval
    totals = _Totals([(foods[i.key], i.grams) for i in items], kb)
    kcal = totals.field(_x(e.nutrients)["fields"]["energy"]) or 0.0
    day_kcal = plan_phase.targets_by_day_type[day_type].kcal
    if level == "meal" and kcal <= 0:
        raise ValueError("a meal needs some energy to be scored against a share of the day")
    share = kcal / day_kcal if level == "meal" else 1.0

    applies = _x(kb.score_weights.applies_to)[level]
    disables = _x(e.coverage)["disables"]
    off = {disables[d.id] for d in profile.disabled if d.id in disables}
    left_out: list[LeftOut] = []

    parts: list[_Part] = []
    by_key: dict[str, list[ScoreComponent]] = {}
    for c in profile.components:
        if c.weight_key and (c.day_type is None or c.day_type == day_type):
            by_key.setdefault(c.weight_key, []).append(c)
    micro = kb.rules["LS.MICRO"]
    for key in profile.weights_exact:
        if key not in applies:
            continue
        if key in off:
            left_out.append(LeftOut(id=key, reason="disabled"))
        elif key == "energy" and level == "meal":
            left_out.append(LeftOut(id=key, reason="not_at_meal_level"))
        elif key == "micro":
            why = explain.text(kb, micro.id, "why")
            for m in profile.micronutrients:
                target = ScoreTarget(min=m.target, unit=m.unit)
                parts.append(_Part(m.id, key, "adequacy", target, [micro.id], why))
        else:
            for c in by_key.get(key, []):
                parts.append(_Part(c.id, key, c.type, c.target, c.rule_ids, c.why))

    eval_ids = [e.formulas.id, e.coverage.id, e.nutrients.id]
    if level == "meal":
        eval_ids.insert(1, e.meal_share.id)
    per_key = Counter(p.weight_key for p in parts)
    for p in parts:
        p.weight = profile.weights_exact[p.weight_key] / per_key[p.weight_key]
        p.target = _scaled(p.target, share)
        p.actual = totals.of(p.id)
        if p.actual is None:
            p.why = explain.text(kb, e.coverage.id, "missing")
        else:
            p.score = _score(p.type, p.actual, p.target)

    available = sum(p.weight for p in parts if p.score is not None)
    total = sum(p.weight for p in parts)
    overall = (
        sum(p.weight * p.score for p in parts if p.score is not None) / available
        if available > 0
        else None
    )
    components = [
        ComponentScore(
            id=p.id,
            weight_key=p.weight_key,
            type=p.type,
            target=p.target,
            actual=p.actual,
            score=p.score,
            weight=p.weight,
            contribution=None if p.score is None else p.weight * p.score / available,
            available=p.score is not None,
            rule_ids=list(dict.fromkeys([*p.rule_ids, *eval_ids])),
            why=p.why,
        )
        for p in parts
    ]
    return ScoreEvaluation(
        level=level,
        phase=profile.phase,
        day_type=day_type,
        items=[
            ScoredItem(
                key=i.key,
                name=str(foods[i.key]["description"]),
                grams=i.grams,
                kcal=foods[i.key]["per_100g"]["energy_kcal"] * i.grams / 100,
            )
            for i in items
        ],
        energy_kcal=kcal,
        day_energy_kcal=day_kcal,
        energy_share=share,
        score=overall,
        coverage_pct=100 * available / total if total > 0 else 0.0,
        components=components,
        left_out=left_out,
        rule_ids=list(
            dict.fromkeys([*eval_ids, kb.score_weights.applies_to.id, *profile.weight_rule_ids])
        ),
        why=explain.text(kb, e.meal_share.id if level == "meal" else e.formulas.id, "why"),
    )
