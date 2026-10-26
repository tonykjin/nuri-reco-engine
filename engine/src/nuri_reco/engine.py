"""The engine: PlanRequest -> PlanResponse (spec §10).

safety -> goals -> feasibility -> expenditure -> targets -> score_profile, then goal_summary
(spec §7b.6). trace=True records each stage and the rules it fired (Task 22).
Blocked requests stop after safety and carry no numbers. Pure apart from loading the packaged
knowledge base when none is passed.
"""

import datetime as dt
from collections import Counter
from typing import Any, Literal, overload

from nuri_reco import (
    expenditure,
    explain,
    feasibility,
    foods,
    goals,
    patterns,
    safety,
    score_profile,
    targets,
)
from nuri_reco.expenditure import AdaptiveExpenditure, ColdStartExpenditure, Expenditure
from nuri_reco.feasibility import FeasibilityResult
from nuri_reco.goals import PhasePlan, Resolution
from nuri_reco.kb import KnowledgeBase, Rule, load_kb
from nuri_reco.models import FoodContext, PlanRequest, TracedPlan
from nuri_reco.models.response import (
    Feasibility,
    FoodRecommendation,
    GoalResolution,
    GoalSummary,
    LoamScoreProfile,
    Pace,
    PatternRecommendation,
    Phase,
    PhaseTimeline,
    PlanResponse,
    PlanStatus,
    SafetyFinding,
)
from nuri_reco.safety import SafetyResult
from nuri_reco.trace import Tracer, rule_ids_of


def _x(rule: Rule) -> dict[str, Any]:
    return rule.model_extra or {}


def _planned_rate(phase: PhasePlan) -> float | None:
    """The phase's weekly loss rate: the user's choice, never above the phase cap."""
    chosen, cap = phase.rate_pct_bw_week, phase.max_rate_pct_bw
    if chosen is None or cap is None:
        return cap if chosen is None else chosen
    return min(chosen, cap)


def _dedupe(ids: list[str]) -> list[str]:
    return list(dict.fromkeys(ids))


def _date(d: dt.date) -> str:
    return f"{d.day} {d:%b %Y}"


# --- Feasibility across phases ---


class _Projection:
    """Feasibility for each deficit phase, carrying body weight from one phase to the next."""

    def __init__(self) -> None:
        self.by_phase: dict[str, FeasibilityResult] = {}
        self.deadline: FeasibilityResult | None = None
        self.reachable: dt.date | None = None
        self.weight_by_date: list[tuple[dt.date, float]] = []

    @property
    def first(self) -> FeasibilityResult | None:
        return next(iter(self.by_phase.values()), None)

    def weight_on(self, day: dt.date, start_kg: float) -> float:
        weight = start_kg
        for when, kg in self.weight_by_date:
            if when <= day:
                weight = kg
        return weight


def _project(
    phases: list[PhasePlan], request: PlanRequest, kb: KnowledgeBase
) -> tuple[list[PhasePlan], _Projection]:
    proj = _Projection()
    weight = request.profile.weight_kg
    out: list[PhasePlan] = []
    for phase in phases:
        prev = out[-1] if out else None
        if phase.start is None and prev is not None and prev.end is not None:
            phase = phase.model_copy(
                update={"start": prev.end}
            )  # sequenced: starts when the last ends
        goal_kg = phase.target_weight_kg
        if phase.energy != "deficit" or goal_kg is None or phase.start is None:
            out.append(phase)
            continue

        profile = request.profile.model_copy(update={"weight_kg": weight})
        result = feasibility.check(phase, profile, kb)
        proj.by_phase[phase.name] = result
        if phase.energy_owner == "deadline_event":
            proj.deadline = result
            proj.reachable = result.reachable_date
        if phase.end is None:
            proj.reachable = proj.reachable or result.reachable_date
            # A sequenced goal ends when it's reached; the next phase starts then.
            nxt = phases[phases.index(phase) + 1] if phase is not phases[-1] else None
            if nxt is not None and nxt.start is None and result.reachable_date:
                phase = phase.model_copy(update={"end": result.reachable_date})
        elif result.projected_kg is not None:  # dated phase: carry the weight to its end
            reached = result.status == "feasible"
            if reached and proj.reachable is None:
                proj.reachable = result.reachable_date
            # Feasible: the goal is reached within the phase; clamped: the projection at its end.
            weight = max(goal_kg, result.projected_kg)
            proj.weight_by_date.append((phase.end, weight))
        out.append(phase)
    return out, proj


# --- Warnings from combinations (e.g. vegan B12) ---


def _combo_warnings(resolution: Resolution, kb: KnowledgeBase) -> list[SafetyFinding]:
    findings = []
    for combo_id in resolution.combo_rule_ids:
        combo = kb.rules[combo_id]
        for rule in getattr(combo, "rules", []):
            if explain.has(kb, rule.id, "warning"):
                findings.append(
                    SafetyFinding(
                        rule_id=rule.id,
                        message=explain.text(kb, rule.id, "warning"),
                        rule_ids=[rule.id, combo_id],
                        why=explain.text(kb, rule.id, "why"),
                    )
                )
    return findings


# --- goal_summary (spec §7b.6) ---


def _event_name(request: PlanRequest) -> str:
    return next((g.event for g in request.goals if g.event), "event")


def _headline(
    request: PlanRequest,
    resolution: Resolution,
    phases: list[PhasePlan],
    proj: _Projection,
    kb: KnowledgeBase,
) -> str:
    values = {"event": _event_name(request)}
    for combo_id in resolution.combo_rule_ids:
        if explain.has(kb, combo_id, "headline"):
            return explain.text(kb, combo_id, "headline", **values)
        if explain.has(kb, combo_id, "headline_clamped"):  # deadline: clamped or feasible
            d = proj.deadline
            if d is None or d.projected_kg is None or d.reachable_date is None:
                continue
            key = "clamped" if d.status == "clamped" else "feasible"
            values |= {
                "projected_kg": f"{d.projected_kg:.1f}",
                "reachable_date": _date(d.reachable_date),
            }
            return explain.text(kb, combo_id, f"headline_{key}", **values)
        if explain.has(kb, combo_id, "headline_recomp"):  # recomp or sequenced
            key = "recomp" if any(p.energy_owner == "recomp" for p in phases) else "sequenced"
            return explain.text(kb, combo_id, f"headline_{key}", **values)
    owner = phases[0].energy_owner if phases else request.goals[0].type
    goal_rule = {g.type: g.id for g in kb.goals.goals}
    rule_id = goal_rule.get(owner, goal_rule["maintain"])
    if not explain.has(kb, rule_id, "headline"):
        rule_id = goal_rule["maintain"]
    return explain.text(kb, rule_id, "headline", **values)


def _display_owner(owner: str, goal_types: list[str], kb: KnowledgeBase) -> str:
    """The goal shown as primary: a modifier goal (deadline) shows the goal it modifies."""
    catalog = {g.type: g for g in kb.goals.goals}
    base = _x(catalog[owner]).get("modifier_of") if owner in catalog else None
    return base if base in goal_types else owner


def _resolved_as(
    goal_type: str,
    phases: list[PhasePlan],
    proj: _Projection,
    kb: KnowledgeBase,
    request: PlanRequest,
    primary_type: str | None,
) -> tuple[str, list[PhasePlan]]:
    ra = kb.summary.resolved_as.id

    def r(variant: str, **values: Any) -> str:
        return explain.text(kb, ra, variant, **values)

    merged = _x(kb.score_weights.stacking)["merged_into"]
    goal_types = [g.type for g in request.goals]
    owned = [p for p in phases if _display_owner(p.energy_owner, goal_types, kb) == goal_type]
    if not owned and any(goal_type in merged.get(p.energy_owner, []) for p in phases):
        merged_phases = [p for p in phases if p.energy_owner in merged]
        if goal_type == primary_type:
            detail, _ = _resolved_as(merged_phases[0].energy_owner, phases, proj, kb, request, None)
            return r("merged_primary", detail=detail), merged_phases
        return r("merged"), merged_phases
    if not owned and goal_type == "deadline_event" and proj.deadline is not None:
        d, event = (
            proj.deadline,
            next((g.event_date for g in request.goals if g.type == goal_type), None),
        )
        if event is not None and d.reachable_date is not None:
            if d.status == "clamped" and d.projected_kg is not None:
                text = r(
                    "deadline",
                    projected_kg=f"{d.projected_kg:.1f}",
                    event_date=_date(event),
                    reachable_date=_date(d.reachable_date),
                )
            else:
                text = r("deadline_feasible", event_date=_date(event))
            return text, [p for p in phases if p.energy_owner == goal_type]
    if not owned:
        return r("modifier"), []

    energy = owned[0].energy
    rate = ""
    deficit = [p for p in owned if p.energy == "deficit"]
    if deficit:
        planned = proj.by_phase.get(deficit[0].name)
        value = planned.rate_pct_bw_week if planned else _planned_rate(deficit[0])
        if value is not None:
            rate = r("rate_suffix", rate=f"{value:g}")

    sequenced = len(phases) > 1 and all("RESOLVER.CONTRADICTION" in p.rule_ids for p in phases)
    if sequenced:  # goals run one after another
        n = phases.index(owned[0]) + 1
        return r("sequenced", n=n, total=len(phases), energy=energy) + rate, owned
    same = [p for p in owned if p.energy == energy]
    if len(same) == len(phases):
        return r("all_phases", energy=energy) + rate, owned
    if len(same) < len(owned):
        # e.g. lose fat during the deadline phase, then step back to maintenance.
        names = " and ".join(p.name.replace("_", " ") for p in same)
        suffix = " phase" if len(same) == 1 else " phases"
        return r("some_phases", energy=energy, phases=names + suffix) + rate, owned
    idx = [phases.index(p) for p in owned]
    contiguous = idx == list(range(idx[0], idx[-1] + 1))
    if contiguous and idx[0] > 0 and owned[0].start is not None:
        text = r(
            "from_to",
            first=owned[0].name.replace("_", " "),
            start=owned[0].start.isoformat(),
            last=owned[-1].name.replace("_", " "),
        )
        return text, owned
    names = " and ".join(p.name.replace("_", " ") for p in owned)
    suffix = " phase" if len(owned) == 1 else " phases"
    return r("some_phases", energy=energy, phases=names + suffix) + rate, owned


def _goal_summary(
    request: PlanRequest,
    resolution: Resolution,
    phases: list[PhasePlan],
    proj: _Projection,
    kb: KnowledgeBase,
) -> GoalSummary:
    merged = _x(kb.score_weights.stacking)["merged_into"]
    ordered = sorted(request.goals, key=lambda g: g.priority)
    goal_types = [g.type for g in ordered]
    primary = _display_owner(phases[0].energy_owner, goal_types, kb) if phases else None
    primary_type = primary
    if primary in merged:
        primary_type = next((g.type for g in ordered if g.type in merged[primary]), primary)
    catalog = {x.type: x for x in kb.goals.goals}
    resolutions = []
    for g in ordered:
        text, owned = _resolved_as(g.type, phases, proj, kb, request, primary_type)
        combos = [
            c for c in resolution.combo_rule_ids if g.type in getattr(kb.rules[c], "goals", [])
        ]
        energy_rule = (
            catalog[g.type].rules["energy"].id if g.type in catalog else "RESOLVER.ONE_ENERGY_GOAL"
        )
        # "primary from peak (...)" cites the phase rule it starts with (spec §7b.6 example).
        phase_ids = [owned[0].rule_ids[0]] if owned and text.startswith("primary from") else []
        resolutions.append(
            GoalResolution(
                type=g.type,
                role="primary" if g.type == primary_type else "secondary",
                resolved_as=text,
                rule_ids=_dedupe([*combos, *phase_ids, energy_rule]),
                why=owned[0].why
                if owned
                else explain.text(kb, kb.summary.resolved_as.id, "modifier").capitalize() + ".",
            )
        )
    first = proj.first
    first_deficit = next((p for p in phases if p.energy == "deficit"), None)
    rate = first.rate_pct_bw_week if first else None
    if rate is None and first_deficit is not None:
        rate = _planned_rate(first_deficit)
    pace = Pace(
        rate_pct_bw_week=rate,
        projected_kg_at_event=_projected_at_event(request, proj),
        reachable_date=proj.reachable,
    )
    return GoalSummary(
        headline=_headline(request, resolution, phases, proj, kb), goals=resolutions, pace=pace
    )


def _projected_at_event(request: PlanRequest, proj: _Projection) -> float | None:
    if proj.deadline is not None:
        return None if proj.deadline.projected_kg is None else round(proj.deadline.projected_kg, 1)
    event = next((g.event_date for g in request.goals if g.event_date), None)
    if event is None or not proj.by_phase:
        return None
    return round(proj.weight_on(event, request.profile.weight_kg), 1)


# --- Short-circuit responses ---


def _empty_profile(rule_ids: list[str]) -> LoamScoreProfile:
    return LoamScoreProfile(by_phase=[], top_levers=[], weight_rule_ids=_dedupe(rule_ids))


def _held_summary(
    request: PlanRequest,
    kb: KnowledgeBase,
    headline: str,
    resolved_as: str,
    rule_ids: list[str],
    why: str,
) -> GoalSummary:
    ordered = sorted(request.goals, key=lambda g: g.priority)
    return GoalSummary(
        headline=headline,
        goals=[
            GoalResolution(
                type=g.type,
                role="primary" if i == 0 else "secondary",
                resolved_as=resolved_as,
                rule_ids=rule_ids,
                why=why,
            )
            for i, g in enumerate(ordered)
        ],
        pace=Pace(),
    )


def _blocked(request: PlanRequest, result: SafetyResult, kb: KnowledgeBase) -> PlanResponse:
    rule_ids = _dedupe([r for b in result.blocks for r in b.rule_ids])
    summary = _held_summary(
        request,
        kb,
        explain.text(kb, kb.summary.headlines.id, "blocked"),
        explain.text(kb, kb.summary.resolved_as.id, "blocked"),
        rule_ids,
        result.blocks[0].why,
    )
    return _response("blocked", result.to_safety(), [], None, summary, _empty_profile(rule_ids), kb)


def _needs_ordering(
    request: PlanRequest, result: SafetyResult, resolution: Resolution, kb: KnowledgeBase
) -> PlanResponse:
    rule_ids = _dedupe(["RESOLVER.CONTRADICTION", *resolution.combo_rule_ids])
    summary = _held_summary(
        request,
        kb,
        explain.text(kb, kb.summary.headlines.id, "needs_ordering"),
        explain.text(kb, kb.summary.resolved_as.id, "awaiting_order"),
        rule_ids,
        resolution.ordering_question or "",
    )
    return _response(
        "needs_ordering", result.to_safety(), [], None, summary, _empty_profile(rule_ids), kb
    )


def _response(
    status: PlanStatus,
    safety_out: Any,
    phases: list[Phase],
    feas: Feasibility | None,
    summary: GoalSummary,
    profile: LoamScoreProfile,
    kb: KnowledgeBase,
    pattern_recs: list[PatternRecommendation] | None = None,
    food_recs: list[FoodRecommendation] | None = None,
) -> PlanResponse:
    resp = PlanResponse(
        status=status,
        safety=safety_out,
        phases=phases,
        feasibility=feas,
        patterns=pattern_recs or [],
        foods=food_recs or [],
        goal_summary=summary,
        loam_score_profile=profile,
    )
    return resp.model_copy(update={"citations": explain.collect_citations(resp, kb)})


# Kept for callers that import it from here.
all_rule_ids = explain.rule_ids_in


# --- The pipeline ---


@overload
def plan(
    request: PlanRequest,
    kb: KnowledgeBase | None = None,
    *,
    dry_run: bool = False,
    trace: Literal[False] = False,
) -> PlanResponse: ...


@overload
def plan(
    request: PlanRequest,
    kb: KnowledgeBase | None = None,
    *,
    dry_run: bool = False,
    trace: Literal[True],
) -> TracedPlan: ...


def plan(
    request: PlanRequest,
    kb: KnowledgeBase | None = None,
    *,
    dry_run: bool = False,
    trace: bool = False,
) -> PlanResponse | TracedPlan:
    """The full plan. dry_run skips patterns and foods (the onboarding pace slider, spec §10).
    trace=True also returns each stage and every rule it fired, in order (Task 22)."""
    kb = kb or load_kb()
    tracer = Tracer(kb) if trace else None
    resp = _plan(request, kb, dry_run, tracer)
    if tracer is None:
        return resp
    tracer.stage(
        "summary",
        rule_ids=rule_ids_of(resp.goal_summary),
        inputs={"status": resp.status},
        outputs={"goal_summary": resp.goal_summary, "citations": resp.citations},
    )
    return TracedPlan(plan=resp, trace=tracer.build())


def _expenditure_stage(exp: Expenditure, request: PlanRequest, kb: KnowledgeBase) -> dict[str, Any]:
    if isinstance(exp, AdaptiveExpenditure):
        return {"estimate": exp.estimate(request.profile)}
    cold = ColdStartExpenditure(kb)
    return {
        "method": exp.method,
        "rmr_kcal": cold.rmr(request.profile),
        "activity_factor": cold.activity_factor(request.profile),
        "tdee_kcal": exp.tdee(request.profile),
    }


def _plan(
    request: PlanRequest, kb: KnowledgeBase, dry_run: bool, tracer: Tracer | None
) -> PlanResponse:
    result = safety.check(request, kb)
    if tracer:
        tracer.stage(
            "safety",
            rule_ids=rule_ids_of(result),
            inputs={
                "profile": request.profile,
                "goals": request.goals,
                "constraints": request.constraints,
            },
            outputs={"blocked": result.blocked, "rd_gated": result.rd_gated, "result": result},
        )
    if result.blocked:
        return _blocked(request, result, kb)

    resolution = goals.resolve(request, result, kb)
    if tracer:
        tracer.stage(
            "goals",
            rule_ids=rule_ids_of(resolution),
            inputs={"goals": request.goals, "sequence_confirmed": request.sequence_confirmed},
            outputs={"resolution": resolution},
        )
    if resolution.status == "needs_ordering":
        return _needs_ordering(request, result, resolution, kb)

    phases, proj = _project(resolution.phases, request, kb)
    if tracer:
        tracer.stage(
            "feasibility",
            rule_ids=rule_ids_of(list(proj.by_phase.values())),
            inputs={"start_weight_kg": request.profile.weight_kg},
            outputs={
                "by_phase": proj.by_phase,
                "deadline_phase": next(
                    (n for n, r in proj.by_phase.items() if r is proj.deadline), None
                ),
                "reachable_date": proj.reachable,
            },
        )
    exp = expenditure.for_request(request, kb)
    if tracer:
        tracer.stage(
            "expenditure",
            rule_ids=exp.rule_ids,
            inputs={"history_days": len(request.history), "as_of": request.as_of},
            outputs=_expenditure_stage(exp, request, kb),
        )
    phase_targets = [
        targets.compute(p, request.profile, kb, safety=result, expenditure=exp) for p in phases
    ]
    if tracer:
        tracer.stage(
            "targets",
            rule_ids=[],
            children=[
                tracer.node(
                    "targets",
                    rule_ids=t.rule_ids,
                    inputs={"phase": p, "tdee_kcal": t.tdee_kcal},
                    outputs={"targets": t},
                )
                for p, t in zip(phases, phase_targets, strict=True)
            ],
        )
    profile = score_profile.build(
        phases,
        phase_targets,
        request.profile,
        kb,
        goal_types=[g.type for g in request.goals],
        diet=request.constraints.diet,
        safety=result,
    )
    if tracer:
        tracer.stage(
            "score_profile",
            rule_ids=rule_ids_of(profile),
            inputs={
                "goal_types": [g.type for g in request.goals],
                "diet": request.constraints.diet,
            },
            outputs={"loam_score_profile": profile},
        )
    api_phases = [
        Phase(
            **p.model_dump(include=set(PhaseTimeline.model_fields) - {"rule_ids"}),
            rule_ids=_dedupe([*p.rule_ids, *p.modifier_rule_ids, *t.rule_ids]),
            targets_by_day_type=t.by_day_type,
        )
        for p, t in zip(phases, phase_targets, strict=True)
    ]

    feas: Feasibility | None = None
    if proj.deadline is not None:
        feas = proj.deadline.to_api()
    elif proj.by_phase:
        feas = Feasibility(
            status="feasible",
            projected_kg_at_event=_projected_at_event(request, proj),
            reachable_date=proj.reachable,
        )

    status: PlanStatus = "ok"
    if result.rd_gated:
        status = "rd_review"
    elif proj.deadline is not None and proj.deadline.status == "clamped":
        status = "clamped"

    safety_out = result.to_safety()
    safety_out = safety_out.model_copy(
        update={"warnings": [*safety_out.warnings, *_combo_warnings(resolution, kb)]}
    )
    summary = _goal_summary(request, resolution, phases, proj, kb)
    resp = _response(status, safety_out, api_phases, feas, summary, profile, kb)
    if dry_run:
        return resp
    recs = patterns.rank(resp, request.preferences, request.constraints, result, kb)
    if tracer:
        tracer.stage(
            "patterns",
            rule_ids=rule_ids_of(recs),
            inputs={"preferences": request.preferences, "diet": request.constraints.diet},
            outputs={"patterns": recs},
        )
    resp = _response(status, safety_out, api_phases, feas, summary, profile, kb, recs)
    # Default context for the plan: the user's most common day type, any meal.
    day = Counter(request.profile.training.weekly_schedule).most_common(1)[0][0]
    food_recs = foods.rank(
        FoodContext(day_type=day),
        resp,
        request.preferences,
        request.constraints,
        kb,
        foods.load_foods(),
    )
    if tracer:
        tracer.stage(
            "foods",
            rule_ids=rule_ids_of(food_recs),
            inputs={"context": FoodContext(day_type=day), "constraints": request.constraints},
            outputs={"foods": food_recs},
        )
    return _response(status, safety_out, api_phases, feas, summary, profile, kb, recs, food_recs)
