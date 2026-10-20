"""The engine: PlanRequest -> PlanResponse (spec §10).

safety -> goals -> feasibility -> targets -> score_profile, then goal_summary (spec §7b.6).
Blocked requests stop after safety and carry no numbers. Pure apart from loading the packaged
knowledge base when none is passed.
"""

import datetime as dt
from typing import Any

from nuri_reco import feasibility, goals, patterns, safety, score_profile, targets
from nuri_reco.feasibility import FeasibilityResult
from nuri_reco.goals import PhasePlan, Resolution
from nuri_reco.kb import KnowledgeBase, Rule, load_kb
from nuri_reco.models import PlanRequest
from nuri_reco.models.response import (
    Feasibility,
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


def _x(rule: Rule) -> dict[str, Any]:
    return rule.model_extra or {}


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
            copy = _x(rule).get("copy", {})
            if "warning" in copy:
                findings.append(
                    SafetyFinding(
                        rule_id=rule.id,
                        message=copy["warning"],
                        rule_ids=[rule.id, combo_id],
                        why=copy["why"],
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
    h = _x(kb.summary.headlines)
    values = {"event": _event_name(request)}
    for combo_id in resolution.combo_rule_ids:
        template = h["combos"].get(combo_id)
        if template is None:
            continue
        if isinstance(template, dict):
            if combo_id == "COMBO.LOSEFAT_DEADLINE":
                d = proj.deadline
                if d is None or d.projected_kg is None or d.reachable_date is None:
                    continue
                key = "clamped" if d.status == "clamped" else "feasible"
                values |= {
                    "projected_kg": f"{d.projected_kg:.1f}",
                    "reachable_date": _date(d.reachable_date),
                }
            else:
                key = "recomp" if any(p.energy_owner == "recomp" for p in phases) else "sequenced"
            template = template[key]
        return str(template).format(**values)
    owner = phases[0].energy_owner if phases else request.goals[0].type
    return str(h["goals"].get(owner, h["goals"]["maintain"])).format(**values)


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
    r = _x(kb.summary.resolved_as)
    merged = _x(kb.score_weights.stacking)["merged_into"]
    goal_types = [g.type for g in request.goals]
    owned = [p for p in phases if _display_owner(p.energy_owner, goal_types, kb) == goal_type]
    if not owned and any(goal_type in merged.get(p.energy_owner, []) for p in phases):
        merged_phases = [p for p in phases if p.energy_owner in merged]
        if goal_type == primary_type:
            detail, _ = _resolved_as(merged_phases[0].energy_owner, phases, proj, kb, request, None)
            return str(r["merged_primary"]).format(detail=detail), merged_phases
        return str(r["merged"]), merged_phases
    if not owned and goal_type == "deadline_event" and proj.deadline is not None:
        d, event = (
            proj.deadline,
            next((g.event_date for g in request.goals if g.type == goal_type), None),
        )
        if event is not None and d.reachable_date is not None:
            if d.status == "clamped" and d.projected_kg is not None:
                text = str(r["deadline"]).format(
                    projected_kg=f"{d.projected_kg:.1f}",
                    event_date=_date(event),
                    reachable_date=_date(d.reachable_date),
                )
            else:
                text = str(r["deadline_feasible"]).format(event_date=_date(event))
            return text, [p for p in phases if p.energy_owner == goal_type]
    if not owned:
        return str(r["modifier"]), []

    energy = owned[0].energy
    rate = ""
    deficit = [p for p in owned if p.energy == "deficit"]
    if deficit:
        planned = proj.by_phase.get(deficit[0].name)
        value = planned.rate_pct_bw_week if planned else deficit[0].max_rate_pct_bw
        if value is not None:
            rate = str(r["rate_suffix"]).format(rate=f"{value:g}")

    sequenced = len(phases) > 1 and all("RESOLVER.CONTRADICTION" in p.rule_ids for p in phases)
    if sequenced:  # goals run one after another
        n = phases.index(owned[0]) + 1
        return str(r["sequenced"]).format(n=n, total=len(phases), energy=energy) + rate, owned
    same = [p for p in owned if p.energy == energy]
    if len(same) == len(phases):
        return str(r["all_phases"]).format(energy=energy) + rate, owned
    if len(same) < len(owned):
        # e.g. lose fat during the deadline phase, then step back to maintenance.
        names = " and ".join(p.name.replace("_", " ") for p in same)
        suffix = " phase" if len(same) == 1 else " phases"
        return str(r["some_phases"]).format(energy=energy, phases=names + suffix) + rate, owned
    idx = [phases.index(p) for p in owned]
    contiguous = idx == list(range(idx[0], idx[-1] + 1))
    if contiguous and idx[0] > 0 and owned[0].start is not None:
        text = str(r["from_to"]).format(
            first=owned[0].name.replace("_", " "),
            start=owned[0].start.isoformat(),
            last=owned[-1].name.replace("_", " "),
        )
        return text, owned
    names = " and ".join(p.name.replace("_", " ") for p in owned)
    suffix = " phase" if len(owned) == 1 else " phases"
    return str(r["some_phases"]).format(energy=energy, phases=names + suffix) + rate, owned


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
                else str(_x(kb.summary.resolved_as)["modifier"]).capitalize() + ".",
            )
        )
    first = proj.first
    first_deficit = next((p for p in phases if p.energy == "deficit"), None)
    rate = first.rate_pct_bw_week if first else None
    if rate is None and first_deficit is not None:
        rate = first_deficit.max_rate_pct_bw
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
    h = _x(kb.summary.headlines)
    summary = _held_summary(
        request,
        kb,
        h["blocked"],
        _x(kb.summary.resolved_as)["blocked"],
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
        _x(kb.summary.headlines)["needs_ordering"],
        _x(kb.summary.resolved_as)["awaiting_order"],
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
) -> PlanResponse:
    resp = PlanResponse(
        status=status,
        safety=safety_out,
        phases=phases,
        feasibility=feas,
        patterns=pattern_recs or [],
        goal_summary=summary,
        loam_score_profile=profile,
    )
    cited = [
        cid for rid in all_rule_ids(resp) if rid in kb.rules for cid in kb.rules[rid].citation_ids
    ]
    return resp.model_copy(update={"citations": _dedupe(cited)})


def all_rule_ids(resp: PlanResponse) -> list[str]:
    """Every rule id the response cites, in order of appearance."""
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("rule_ids", "weight_rule_ids") and isinstance(value, list):
                    found.extend(value)
                elif key == "rule_id" and isinstance(value, str):
                    found.append(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(resp.model_dump())
    return _dedupe(found)


# --- The pipeline ---


def plan(
    request: PlanRequest, kb: KnowledgeBase | None = None, *, dry_run: bool = False
) -> PlanResponse:
    """The full plan. dry_run skips patterns and foods (the onboarding pace slider, spec §10)."""
    kb = kb or load_kb()
    result = safety.check(request, kb)
    if result.blocked:
        return _blocked(request, result, kb)

    resolution = goals.resolve(request, result, kb)
    if resolution.status == "needs_ordering":
        return _needs_ordering(request, result, resolution, kb)

    phases, proj = _project(resolution.phases, request, kb)
    phase_targets = [targets.compute(p, request.profile, kb, safety=result) for p in phases]
    profile = score_profile.build(
        phases,
        phase_targets,
        request.profile,
        kb,
        goal_types=[g.type for g in request.goals],
        diet=request.constraints.diet,
        safety=result,
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
    return _response(status, safety_out, api_phases, feas, summary, profile, kb, recs)
