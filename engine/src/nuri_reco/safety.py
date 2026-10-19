"""Stage 1: safety guardrails (spec §8 Matrix F; §4.1 tier 1 overrides everything).

check() is pure and deterministic: no I/O, no randomness. Every threshold, vocabulary entry and
piece of copy comes from guardrails.yaml; this module only decides when each rule's trigger fires.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import Field

from nuri_reco.kb import KnowledgeBase, Rule
from nuri_reco.models import PlanRequest, StrictModel
from nuri_reco.models.response import Referral, Safety, SafetyFinding

RestrictionKind = Literal[
    "exclude_patterns",  # pattern ids the plan must not offer
    "remove",  # things taken out of the plan (e.g. the deficit) without blocking it
    "rd_approval_required",  # changes that need an RD first
    "keep_consistent",  # nutrients to keep steady day to day
    "never_advise",  # advice the plan must never give
    "offer",  # UI modes to offer (e.g. number hiding)
]


class Restriction(StrictModel):
    rule_id: str
    kind: RestrictionKind
    items: list[str] = Field(min_length=1)


class CalorieFloor(StrictModel):
    rule_id: str
    sex_floor_kcal: float
    ea_floor_kcal_per_kg_ffm: float
    ea_floor_adds_exercise_kcal: bool
    absolute_min_kcal_per_day: float


class LossRateCap(StrictModel):
    rule_id: str
    max_loss_pct_bw_per_week: float


class ProteinCap(StrictModel):
    rule_id: str
    min_g_per_kg: float
    max_g_per_kg: float


class SafetyResult(StrictModel):
    blocks: list[SafetyFinding] = Field(default_factory=list)
    warnings: list[SafetyFinding] = Field(default_factory=list)
    referrals: list[Referral] = Field(default_factory=list)
    # Rule ids that put the plan on hold for RD review.
    rd_gated_rule_ids: list[str] = Field(default_factory=list)
    calorie_floor: CalorieFloor
    max_loss_rate: LossRateCap | None = None
    protein_cap: ProteinCap | None = None
    restrictions: list[Restriction] = Field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return bool(self.blocks)

    @property
    def rd_gated(self) -> bool:
        return bool(self.rd_gated_rule_ids)

    def restricted(self, kind: RestrictionKind) -> list[str]:
        return [item for r in self.restrictions if r.kind == kind for item in r.items]

    @property
    def excluded_pattern_ids(self) -> list[str]:
        return self.restricted("exclude_patterns")

    def to_safety(self) -> Safety:
        return Safety(blocks=self.blocks, warnings=self.warnings, referrals=self.referrals)


@dataclass(frozen=True)
class _Context:
    request: PlanRequest
    kb: KnowledgeBase
    bmi: float
    goal_bmi: float | None
    goal_types: frozenset[str]
    medications: frozenset[str]
    conditions: frozenset[str]
    deficit_requested: bool
    weight_loss_target: bool
    deadline_requested: bool


def _extra(rule: Rule) -> dict[str, Any]:
    return rule.model_extra or {}


def _bmi(weight_kg: float, height_cm: float) -> float:
    return weight_kg / (height_cm / 100) ** 2


def _context(request: PlanRequest, kb: KnowledgeBase) -> _Context:
    profile = request.profile
    goal_types = frozenset(g.type for g in request.goals)
    deficit_types = {
        g.type for g in kb.goals.goals if _extra(g.rules["energy"]).get("direction") == "deficit"
    }
    modifier_types = {g.type for g in kb.goals.goals if "modifier_of" in _extra(g)}
    targets = [g.target_weight_kg for g in request.goals if g.target_weight_kg is not None]
    return _Context(
        request=request,
        kb=kb,
        bmi=_bmi(profile.weight_kg, profile.height_cm),
        goal_bmi=_bmi(min(targets), profile.height_cm) if targets else None,
        goal_types=goal_types,
        medications=frozenset(m.lower() for m in profile.flags.medications),
        conditions=frozenset(c.lower() for c in profile.flags.conditions),
        deficit_requested=bool(goal_types & (deficit_types | modifier_types)),
        weight_loss_target=any(t < profile.weight_kg for t in targets),
        deadline_requested=bool(goal_types & modifier_types),
    )


# --- Triggers: when does each guardrail apply? ---


def _has_medication(ctx: _Context, rule: Rule) -> bool:
    return bool(ctx.medications & set(_extra(rule)["medications"]))


def _condition_present(ctx: _Context, name: str) -> bool:
    spec = _extra(ctx.kb.rules["GUARD.CONDITION_GOALS"])["conditions"][name]
    matched = (
        bool(ctx.goal_types & set(spec.get("goal_types", [])))
        or bool(ctx.conditions & set(spec.get("conditions", [])))
        or bool(ctx.medications & set(spec.get("medications", [])))
        or (spec.get("ckd_stage", False) and ctx.request.profile.flags.ckd_stage is not None)
    )
    required_meds = set(spec.get("with_medications", []))
    return matched and (not required_meds or bool(ctx.medications & required_meds))


def _ed_risk(ctx: _Context, rule: Rule) -> bool:
    triggers = _extra(rule)["triggers"]
    flags = ctx.request.profile.flags
    return (
        (flags.scoff_score is not None and flags.scoff_score >= triggers["scoff_min"])
        or (triggers.get("ed_history", False) and flags.ed_history)
        or (ctx.goal_bmi is not None and ctx.goal_bmi < triggers["goal_bmi_below"])
        # "Repeated rapid-loss requests" needs request history; the engine is stateless.
    )


def _low_ea(ctx: _Context, rule: Rule) -> bool:
    # The numeric EA trigger is enforced by the calorie floor when targets are set (Stage 4);
    # here only the self-reported symptoms can fire.
    symptoms = set(_extra(rule)["triggers"]["reported_symptoms"])
    return bool(symptoms & set(ctx.request.profile.flags.reported_symptoms))


TRIGGERS: dict[str, Callable[[_Context, Rule], bool]] = {
    "GUARD.CALORIE_FLOOR": lambda ctx, rule: True,
    "GUARD.MAX_LOSS_RATE": lambda ctx, rule: ctx.deficit_requested,
    "GUARD.UNDER_18": lambda ctx, rule: ctx.request.profile.age < _extra(rule)["age_below"],
    "GUARD.PREGNANCY": lambda ctx, rule: any(
        getattr(ctx.request.profile.flags, flag) for flag in _extra(rule)["flags"]
    ),
    "GUARD.ED_RISK": _ed_risk,
    "GUARD.LOW_EA": _low_ea,
    "GUARD.CKD": lambda ctx, rule: ctx.request.profile.flags.ckd_stage is not None,
    "GUARD.SGLT2": _has_medication,
    "GUARD.INSULIN_SU": _has_medication,
    "GUARD.WARFARIN": _has_medication,
    "GUARD.CONDITION_GOALS": lambda ctx, rule: any(
        _condition_present(ctx, name) for name in _extra(rule)["conditions"]
    ),
    # Applies to output copy, not to the request: see claims_violations().
    "GUARD.CLAIMS": lambda ctx, rule: False,
    "GUARD.PEAK_WEEK": lambda ctx, rule: ctx.deadline_requested,
}


# --- Effects: what a triggered guardrail does (all read from the rule) ---


def _requested(ctx: _Context, item: str) -> bool:
    return {
        "deficit": ctx.deficit_requested,
        "weight_loss_targets": ctx.weight_loss_target,
        "aesthetic_modes": ctx.deadline_requested,
    }[item]


def _blocking_combos(kb: KnowledgeBase, rule_id: str) -> list[str]:
    return [
        c.id
        for c in kb.combos.combinations
        if _extra(c).get("blocked") and rule_id in _extra(c).get("guardrail_rule_ids", [])
    ]


def _finding(rule: Rule, message: str, rule_ids: list[str] | None = None) -> SafetyFinding:
    return SafetyFinding(
        rule_id=rule.id,
        message=message,
        rule_ids=rule_ids or [rule.id],
        why=_extra(rule)["copy"]["why"],
    )


def _protein_cap(ctx: _Context, rule: Rule) -> ProteinCap | None:
    caps = _extra(rule)["protein_cap_g_per_kg"]
    stage = ctx.request.profile.flags.ckd_stage
    if stage is None or not caps["stages"]["min"] <= stage <= caps["stages"]["max"]:
        return None
    cap = caps["with_diabetes"] if _condition_present(ctx, "t2d") else caps["no_diabetes"]
    return ProteinCap(rule_id=rule.id, min_g_per_kg=cap["min"], max_g_per_kg=cap["max"])


def loss_rate_band(bmi: float, kb: KnowledgeBase) -> LossRateCap:
    """Matrix F max loss rate for a BMI (GUARD.MAX_LOSS_RATE bands)."""
    rule = kb.rules["GUARD.MAX_LOSS_RATE"]
    # Lean-athlete status isn't modelled yet, so the band comes from BMI alone.
    for band in _extra(rule)["bands"]:
        if band.get("bmi_min", float("-inf")) <= bmi < band.get("bmi_below", float("inf")):
            return LossRateCap(
                rule_id=rule.id, max_loss_pct_bw_per_week=band["max_loss_pct_bw_per_week"]
            )
    raise ValueError(f"{rule.id}: no band covers BMI {bmi:.1f}")


def bmi(weight_kg: float, height_cm: float) -> float:
    return _bmi(weight_kg, height_cm)


def _calorie_floor(ctx: _Context, rule: Rule) -> CalorieFloor:
    e = _extra(rule)
    return CalorieFloor(
        rule_id=rule.id,
        sex_floor_kcal=e["sex_floor_kcal"][ctx.request.profile.sex],
        ea_floor_kcal_per_kg_ffm=e["ea_floor_kcal_per_kg_ffm"],
        ea_floor_adds_exercise_kcal=e["ea_floor_adds_exercise_kcal"],
        absolute_min_kcal_per_day=e["absolute_min_kcal_per_day"],
    )


RESTRICTION_FIELDS: dict[str, RestrictionKind] = {
    "exclude_pattern_ids": "exclude_patterns",
    "blocks_without_rd": "rd_approval_required",
    "keep_consistent": "keep_consistent",
    "never": "never_advise",
    "offer": "offer",
}


def check(request: PlanRequest, kb: KnowledgeBase) -> SafetyResult:
    """Evaluate every Matrix F guardrail against the request, in guardrails.yaml order."""
    ctx = _context(request, kb)
    blocks: list[SafetyFinding] = []
    warnings: list[SafetyFinding] = []
    referrals: list[Referral] = []
    rd_gated: list[str] = []
    restrictions: list[Restriction] = []
    calorie_floor: CalorieFloor | None = None
    max_loss_rate: LossRateCap | None = None
    protein_cap: ProteinCap | None = None

    for rule in kb.guardrails.guardrails:
        trigger = TRIGGERS.get(rule.id)
        if trigger is None:
            raise ValueError(f"guardrail {rule.id} has no trigger in safety.TRIGGERS")
        if not trigger(ctx, rule):
            continue
        e = _extra(rule)
        copy = e.get("copy", {})

        blocked = [item for item in e.get("blocks", []) if _requested(ctx, item)]
        if blocked:
            blocks.append(_finding(rule, copy["block"], [rule.id, *_blocking_combos(kb, rule.id)]))

        removed = [item for item in e.get("removes", []) if _requested(ctx, item)]
        if removed:
            restrictions.append(Restriction(rule_id=rule.id, kind="remove", items=removed))

        # A rule that removes something only warns when it actually removed it.
        if "warning" in copy and (removed or "removes" not in e):
            warnings.append(_finding(rule, copy["warning"]))
        if "referral" in copy:
            referral = _finding(rule, copy["referral"])
            referrals.append(Referral(**referral.model_dump(), to=e["referral_to"]))

        for field, kind in RESTRICTION_FIELDS.items():
            if e.get(field):
                restrictions.append(Restriction(rule_id=rule.id, kind=kind, items=e[field]))

        if e.get("rd_gated") or rule.id == "GUARD.CONDITION_GOALS":
            rd_gated.append(rule.id)
        if "protein_cap_g_per_kg" in e:
            protein_cap = _protein_cap(ctx, rule)
        if "sex_floor_kcal" in e:
            calorie_floor = _calorie_floor(ctx, rule)
        if "bands" in e:
            max_loss_rate = loss_rate_band(ctx.bmi, kb)

    if calorie_floor is None:
        raise ValueError("guardrails.yaml has no calorie floor rule")
    return SafetyResult(
        blocks=blocks,
        warnings=warnings,
        referrals=referrals,
        rd_gated_rule_ids=rd_gated,
        calorie_floor=calorie_floor,
        max_loss_rate=max_loss_rate,
        protein_cap=protein_cap,
        restrictions=restrictions,
    )


def claims_violations(text: str, kb: KnowledgeBase) -> list[str]:
    """Forbidden claim phrases (GUARD.CLAIMS) found in user-facing copy."""
    phrases = _extra(kb.rules["GUARD.CLAIMS"])["forbidden_phrases"]
    return [p for p in phrases if re.search(rf"\b{re.escape(p)}\b", text, flags=re.IGNORECASE)]
