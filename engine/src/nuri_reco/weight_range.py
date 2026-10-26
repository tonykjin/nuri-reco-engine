"""Target weight range: recommended range, milestone and target bounds (Task 25, spec §4.4b).

weight_range() is pure and deterministic: no I/O, no randomness. Safety runs first (invariant 1):
a blocked request returns no numbers, and a request that trips a number-hiding guardrail
(WEIGHT.RANGE.SLIDER hidden_when_rule_ids) returns status "hidden" with no numbers. Every
threshold comes from weight_range.yaml; the floor is the GUARD.ED_RISK goal BMI.
"""

import math
from typing import Any

from nuri_reco import explain, safety
from nuri_reco.kb import KnowledgeBase, Rule
from nuri_reco.models import PlanRequest
from nuri_reco.models.weight_range import (
    Milestone,
    RangeBasis,
    RecommendedRange,
    TargetBounds,
    WeightRangeResponse,
)

# Float slack when rounding a bound inward, so an exact 108.0 doesn't round up to 108.1.
_EPS = 1e-9


def _x(rule: Rule) -> dict[str, Any]:
    return rule.model_extra or {}


def _kg_at(bmi: float, height_cm: float) -> float:
    return bmi * (height_cm / 100) ** 2


def _up(kg: float, step: float) -> float:
    return round(math.ceil(kg / step - _EPS) * step, 10)


def _down(kg: float, step: float) -> float:
    return round(math.floor(kg / step + _EPS) * step, 10)


def _nearest(kg: float, step: float) -> float:
    return round(round(kg / step) * step, 10)


def _pct(value: float) -> str:
    return f"{value:g}"


def _finish(resp: WeightRangeResponse, kb: KnowledgeBase) -> WeightRangeResponse:
    return resp.model_copy(update={"citations": explain.collect_citations(resp, kb)})


def _recommended(req: PlanRequest, kb: KnowledgeBase, floor_kg: float) -> RecommendedRange:
    wr = kb.weight_range
    profile = req.profile
    step = _x(wr.slider)["round_kg"]
    basis: RangeBasis
    if profile.body_fat_pct is not None:
        rule, basis = wr.body_fat, "body_fat"
        band = _x(rule)["target_body_fat_pct"][profile.sex]
        ffm = profile.weight_kg * (1 - profile.body_fat_pct / 100)
        low = max(ffm / (1 - band["min"] / 100), floor_kg)
        high = max(ffm / (1 - band["max"] / 100), floor_kg)
        rule_ids = [rule.id, wr.slider.id, _x(wr.slider)["floor_from"]]
        why = explain.text(kb, rule.id, "why")
    else:
        older = profile.age >= _x(wr.older)["age_min"]
        rule, basis = (wr.older, "bmi_older") if older else (wr.bmi, "bmi")
        bmi = _x(rule)["bmi"]
        low, high = _kg_at(bmi["min"], profile.height_cm), _kg_at(bmi["max"], profile.height_cm)
        rule_ids = [rule.id]
        why = explain.text(kb, rule.id, "why", bmi_min=_pct(bmi["min"]), bmi_max=_pct(bmi["max"]))
    return RecommendedRange(
        min_kg=_up(low, step), max_kg=_down(high, step), basis=basis, rule_ids=rule_ids, why=why
    )


def _milestone(req: PlanRequest, kb: KnowledgeBase) -> Milestone | None:
    rule = kb.weight_range.milestone
    m = _x(rule)
    profile = req.profile
    fat_loss = any(g.type == "lose_fat" for g in req.goals)
    if not fat_loss or safety.bmi(profile.weight_kg, profile.height_cm) < m["bmi_min"]:
        return None
    step = _x(kb.weight_range.slider)["round_kg"]
    loss = m["loss_pct"]
    return Milestone(
        min_kg=_up(profile.weight_kg * (1 - loss["max"] / 100), step),
        max_kg=_down(profile.weight_kg * (1 - loss["min"] / 100), step),
        rule_ids=[rule.id],
        why=explain.text(kb, rule.id, "why", min_pct=_pct(loss["min"]), max_pct=_pct(loss["max"])),
    )


def weight_range(req: PlanRequest, kb: KnowledgeBase) -> WeightRangeResponse:
    """The recommended range, first milestone and slider bounds for the request's weight goals."""
    wr = kb.weight_range
    s = _x(wr.slider)

    result = safety.check(req, kb)
    if result.blocked:
        rule_ids = list(dict.fromkeys(r for b in result.blocks for r in b.rule_ids))
        resp = WeightRangeResponse(status="blocked", rule_ids=rule_ids, why=result.blocks[0].why)
        return _finish(resp, kb)
    hiding = [r for r in safety.fired(req, kb) if r in s["hidden_when_rule_ids"]]
    if hiding:
        why = f"{explain.text(kb, wr.slider.id, 'hidden')} {explain.text(kb, hiding[0], 'why')}"
        resp = WeightRangeResponse(status="hidden", rule_ids=[wr.slider.id, *hiding], why=why)
        return _finish(resp, kb)

    profile = req.profile
    current = profile.weight_kg
    step, round_kg = s["step_kg"], s["round_kg"]
    floor_rule = kb.rules[s["floor_from"]]
    floor_kg = _kg_at(_x(floor_rule)["triggers"]["goal_bmi_below"], profile.height_cm)
    recommended = _recommended(req, kb, floor_kg)
    milestone = _milestone(req, kb)

    goal_types = {g.type for g in req.goals}
    target_bounds: dict[str, TargetBounds] = {}
    at_floor = False
    if "lose_fat" in goal_types:
        low, high = _up(floor_kg, round_kg), _down(current, round_kg)
        if low >= high:
            at_floor = True
        else:
            pct = s["lose_fat"]["default_change_pct"]
            default = min(max(current * (1 - pct / 100), low), high)
            target_bounds["lose_fat"] = TargetBounds(
                min_kg=low,
                max_kg=high,
                step_kg=step,
                default_kg=_nearest(default, round_kg),
                rule_ids=[wr.slider.id, floor_rule.id],
                why=explain.text(kb, wr.slider.id, "lose_fat", pct=_pct(pct)),
            )
    if "gain_weight" in goal_types:
        g = s["gain_weight"]
        low = _up(current, round_kg)
        reach = current * (1 + g["max_above_current_pct"] / 100)
        high = _down(max(recommended.max_kg, reach), round_kg)
        default = min(max(current * (1 + g["default_change_pct"] / 100), low), high)
        target_bounds["gain_weight"] = TargetBounds(
            min_kg=low,
            max_kg=high,
            step_kg=step,
            default_kg=_nearest(default, round_kg),
            rule_ids=[wr.slider.id, *recommended.rule_ids[:1]],
            why=explain.text(kb, wr.slider.id, "gain_weight", pct=_pct(g["default_change_pct"])),
        )

    rule_ids = [*recommended.rule_ids, wr.slider.id]
    if milestone:
        rule_ids.append(milestone.rule_ids[0])
    if at_floor:
        rule_ids.append(floor_rule.id)
    resp = WeightRangeResponse(
        status="ok",
        current_kg=current,
        recommended=recommended,
        milestone=milestone,
        target_bounds=target_bounds,
        rule_ids=list(dict.fromkeys(rule_ids)),
        why=explain.text(kb, wr.slider.id, "at_floor") if at_floor else recommended.why,
    )
    return _finish(resp, kb)


__all__ = ["weight_range"]
