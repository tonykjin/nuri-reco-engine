"""Stage 2: resolve goals into phases (spec §4.1 priority, §4.2 combinations, §4.3 timeline).

resolve() is pure. Tier membership, combinations, phase boundaries, ramp lengths, rate caps and
copy all come from combos.yaml, phases.yaml and goals.yaml.
"""

import datetime as dt
from typing import Any, Literal

from pydantic import Field

from nuri_reco.kb import ComboRule, KnowledgeBase, PhaseRule, Rule
from nuri_reco.models import DayType, Energy, PlanRequest, StrictModel
from nuri_reco.models.response import PhaseTimeline
from nuri_reco.safety import SafetyResult

# Phase names the resolver creates besides the event phases in phases.yaml.
RESOLVER_PHASE_NAMES = frozenset({"main", "resume", "deadline", "step_back"})
ENERGY_ORDER: dict[Energy, int] = {"deficit": 0, "maintenance": 1, "surplus": 2}
ResolutionStatus = Literal["ok", "needs_ordering", "blocked"]
# (owner goal type, energy, why, rule_ids) for one sequenced phase.
_Step = tuple[str, Energy, str, list[str]]


class PhasePlan(PhaseTimeline):
    # Day types that take the deficit (e.g. rest/easy for lose fat + marathon).
    deficit_day_types: list[DayType] = Field(default_factory=list)
    # Build phase: maintenance, with a small deficit on rest days at most.
    allow_rest_day_deficit: bool = False
    # Weight goal for deficit phases and the user-chosen rate, read by feasibility (spec §4.4).
    target_weight_kg: float | None = None
    rate_pct_bw_week: float | None = None
    # Modifier rules that apply in this phase (protein position, vegan nutrients, ...).
    modifier_rule_ids: list[str] = Field(default_factory=list)


class Resolution(StrictModel):
    status: ResolutionStatus
    phases: list[PhasePlan] = Field(default_factory=list)
    combo_rule_ids: list[str] = Field(default_factory=list)
    # needs_ordering: the goals that conflict and the question to ask.
    conflicting_goals: list[str] = Field(default_factory=list)
    ordering_question: str | None = None


def _x(rule: Rule) -> dict[str, Any]:
    return rule.model_extra or {}


def _unquote(text: str) -> str:
    return text.strip().strip('"')


class _Goals:
    """Read-only lookups over the knowledge base for one request."""

    def __init__(self, request: PlanRequest, kb: KnowledgeBase) -> None:
        self.request = request
        self.kb = kb
        self.goals = sorted(request.goals, key=lambda g: g.priority)
        self.types = [g.type for g in self.goals]
        self.catalog = {g.type: g for g in kb.goals.goals}
        self.tiers = {t: tier for tier in kb.combos.tiers for t in _x(tier).get("goal_types", [])}
        self.tier_rule = _x(kb.combos.tier_rule)

    def direction(self, goal_type: str) -> Energy | None:
        goal = self.catalog.get(goal_type)
        if goal is None:
            return None
        if "modifier_of" in _x(goal):
            return self.direction(_x(goal)["modifier_of"])
        direction: Energy | None = _x(goal.rules["energy"]).get("direction")
        return direction

    def energy_rule_id(self, goal_type: str) -> list[str]:
        goal = self.catalog.get(goal_type)
        return [goal.rules["energy"].id] if goal else []

    def tier(self, goal_type: str) -> Rule | None:
        return self.tiers.get(goal_type)

    def tier_number(self, goal_type: str) -> int:
        """Lower wins; goals with no tier sort last (stable on priority)."""
        tier = self.tier(goal_type)
        return int(_x(tier)["tier"]) if tier else len(self.kb.combos.tiers) + 1

    def goal(self, goal_type: str) -> Any:
        return next(g for g in self.goals if g.type == goal_type)

    def combos(self) -> list[ComboRule]:
        types = set(self.types)
        diet = self.request.constraints.diet
        return [
            c
            for c in self.kb.combos.combinations
            if set(c.goals) <= types and _x(c).get("diet", diet) == diet
        ]

    def recomp_eligible(self) -> bool:
        """Spec §4.2: recomp needs resistance training; trained *and* lean users cut then bulk."""
        profile = self.request.profile
        if not profile.training.resistance:
            return False
        trained = profile.training.experience in ("intermediate", "advanced")
        cutoff = _x(self.kb.rules["COMBO.LOSEFAT_MUSCLE.LEAN_CUTOFF"])["lean_body_fat_pct_below"]
        lean = profile.body_fat_pct is not None and profile.body_fat_pct < cutoff[profile.sex]
        return not (trained and lean)


def _phase(
    name: str,
    start: dt.date | None,
    end: dt.date | None,
    energy: Energy,
    owner: str,
    rule_ids: list[str],
    why: str,
    **extra: Any,
) -> PhasePlan:
    return PhasePlan(
        name=name,
        start=start,
        end=end,
        energy=energy,
        energy_owner=owner,
        rule_ids=list(dict.fromkeys(rule_ids)),
        why=why,
        **extra,
    )


def _energy_copy(kb: KnowledgeBase, energy: Energy) -> str:
    copy: dict[str, str] = _x(kb.rules["RESOLVER.ONE_ENERGY_GOAL"])["copy"]
    return copy[energy]


def _event_timeline(
    g: _Goals,
    event_date: dt.date,
    body_owner: str | None,
    body_energy: Energy | None,
    base_rule_ids: list[str],
    combo_ids: list[str],
) -> list[PhasePlan]:
    """Phases counted back from the event (spec §4.3), clipped to start at as_of."""
    as_of = g.request.as_of
    combos = {c.id: c for c in g.combos()}
    endurance_combo = (
        _x(combos["COMBO.LOSEFAT_ENDURANCE"]) if "COMBO.LOSEFAT_ENDURANCE" in combos else {}
    )
    phases: list[PhasePlan] = []
    prev_end: dt.date | None = None
    for p in g.kb.phases.phases:
        x = _x(p)
        if "weeks_before_event" in x:
            w = x["weeks_before_event"]
            start = event_date - dt.timedelta(weeks=w["max"]) if w["max"] is not None else as_of
            end = event_date - dt.timedelta(weeks=w["min"])
        elif "days_before_event" in x:
            start = event_date - dt.timedelta(days=x["days_before_event"])
            end = event_date + dt.timedelta(days=1)  # race day belongs to race week
        else:
            start = prev_end or event_date + dt.timedelta(days=1)
            end = start + dt.timedelta(weeks=x["weeks_after_event"]["max"])
        prev_end = end
        start = max(start, as_of)
        if end <= start:
            continue
        phases.append(
            _timeline_phase(
                g, p, start, end, body_owner, body_energy, base_rule_ids, combo_ids, endurance_combo
            )
        )

    if body_owner and body_energy and phases and phases[-1].name == "recovery":
        recovery = g.kb.rules["PHASE.RECOVERY"]
        phases.append(
            _phase(
                "resume",
                phases[-1].end,
                None,
                body_energy,
                body_owner,
                ["RESOLVER.TIMELINE", recovery.id, *base_rule_ids, *combo_ids],
                _x(recovery)["resume_why"],
            )
        )
    return phases


def _timeline_phase(
    g: _Goals,
    p: PhaseRule,
    start: dt.date,
    end: dt.date,
    body_owner: str | None,
    body_energy: Energy | None,
    base_rule_ids: list[str],
    combo_ids: list[str],
    endurance_combo: dict[str, Any],
) -> PhasePlan:
    x = _x(p)
    rule_ids = [p.id, "RESOLVER.TIMELINE", *combo_ids]
    if p.name == "base" and body_owner and body_energy:
        extra: dict[str, Any] = {}
        if body_energy == "deficit":
            extra["deficit_day_types"] = endurance_combo.get("deficit_day_types", [])
            cap = endurance_combo.get("max_loss_pct_bw_per_week")
            if cap is not None:
                extra["max_rate_pct_bw"] = cap
        return _phase(
            p.name,
            start,
            end,
            body_energy,
            body_owner,
            [*rule_ids, *base_rule_ids],
            x["why"],
            **extra,
        )
    energy: Energy = x.get("energy_direction", "maintenance")
    return _phase(
        p.name,
        start,
        end,
        energy,
        "endurance_event",
        [*rule_ids, *g.energy_rule_id("endurance_event")],
        x["why"],
        allow_rest_day_deficit=x.get("deficit_allowed") == "small_rest_days_only"
        and body_energy == "deficit",
    )


def _deadline_phases(g: _Goals, event_date: dt.date, combo_ids: list[str]) -> list[PhasePlan]:
    """Deficit until the event, then step back to maintenance (spec §4.2 wedding row)."""
    energy = g.direction("deadline_event") or "deficit"
    step_back = g.kb.rules["COMBO.LOSEFAT_DEADLINE.STEP_BACK"]
    weeks = _x(step_back)["step_back_weeks"]["max"]
    tier = g.tier("deadline_event")
    return [
        _phase(
            "deadline",
            g.request.as_of,
            event_date,
            energy,
            "deadline_event",
            [
                *([tier.id] if tier else []),
                *g.energy_rule_id("deadline_event"),
                "FEAS.DEADLINE",
                *combo_ids,
            ],
            _energy_copy(g.kb, energy),
        ),
        _phase(
            "step_back",
            event_date,
            None,
            "maintenance",
            "deadline_event",
            [step_back.id, *combo_ids],
            _x(step_back)["copy"]["why"],
            ramp_start=event_date,
            ramp_end=event_date + dt.timedelta(weeks=weeks),
        ),
    ]


def _sequenced(g: _Goals, order: list[_Step]) -> list[PhasePlan]:
    """Goals one after another; only the first has a start date until feasibility dates them."""
    return [
        _phase(
            name,
            g.request.as_of if i == 0 else None,
            None,
            energy,
            owner,
            ["RESOLVER.CONTRADICTION", *rule_ids],
            why,
        )
        for i, (owner, energy, why, rule_ids) in enumerate(order)
        for name in [f"{owner}_{i + 1}"]
    ]


def _add_ramps(kb: KnowledgeBase, phases: list[PhasePlan]) -> list[PhasePlan]:
    """Spec §4.1 rule 4: ramp 7 days for a one-step change, 14 for a full flip, ending at the
    new phase's start so event fueling is fully on from day one."""
    days = _x(kb.rules["RESOLVER.RAMP"])["ramp_days"]
    out = phases[:1]
    for prev, phase in zip(phases, phases[1:], strict=False):
        steps = abs(ENERGY_ORDER[phase.energy] - ENERGY_ORDER[prev.energy])
        if steps and phase.ramp_start is None and phase.start and prev.start:
            length = dt.timedelta(days=days["min"] if steps == 1 else days["max"])
            phase = phase.model_copy(
                update={
                    "ramp_start": max(prev.start, phase.start - length),
                    "ramp_end": phase.start,
                    "rule_ids": [*phase.rule_ids, "RESOLVER.RAMP"],
                }
            )
        out.append(phase)
    return out


def _remove_deficits(kb: KnowledgeBase, phases: list[PhasePlan]) -> list[PhasePlan]:
    """A guardrail removed the deficit (e.g. low energy availability): run at maintenance."""
    removers = [r for r in kb.guardrails.guardrails if "deficit" in _x(r).get("removes", [])]
    return [
        p.model_copy(
            update={
                "energy": "maintenance",
                "max_rate_pct_bw": None,
                "deficit_day_types": [],
                "allow_rest_day_deficit": False,
                "rule_ids": [*p.rule_ids, *(r.id for r in removers)],
            }
        )
        if p.energy == "deficit" or p.allow_rest_day_deficit
        else p
        for p in phases
    ]


def resolve(request: PlanRequest, safety: SafetyResult, kb: KnowledgeBase) -> Resolution:
    """Turn the request's goals into dated phases with one energy direction each."""
    if safety.blocked:
        return Resolution(status="blocked")

    g = _Goals(request, kb)
    combos = g.combos()
    combo_ids = [c.id for c in combos if not _x(c).get("blocked")]
    modifiers = [r.id for c in combos for r in c.rules]
    modifier_only = set(g.tier_rule["modifier_only_goal_types"])
    owners = [t for t in g.types if t not in modifier_only]

    endurance = next((x for x in g.goals if x.type == "endurance_event"), None)
    event_date = endurance.event_date if endurance and endurance.event_date else None
    if event_date and event_date <= request.as_of:
        event_date = None
    if endurance and not event_date and len(owners) > 1:
        owners.remove("endurance_event")  # no event window without a date

    # Body-composition goals (tier 4) and the deadline modifier: check for contradictions.
    body_tier = kb.rules["TIER.BODY_COMP"]
    body = [t for t in owners if g.tier(t) == body_tier]
    directions = {t: g.direction(t) for t in body}
    deficit = [t for t, d in directions.items() if d == "deficit"]
    surplus = [t for t, d in directions.items() if d == "surplus"]

    body_owner: str | None = body[0] if body else None
    body_rule_ids = g.energy_rule_id(body_owner) if body_owner else []
    if deficit and surplus:
        contradiction = [*deficit, *surplus]
        if g.recomp_eligible():
            body_owner = "recomp"
            body_rule_ids = ["RESOLVER.CONTRADICTION", *g.energy_rule_id("recomp")]
        elif "COMBO.LOSEFAT_MUSCLE" in combo_ids:
            cutoff = kb.rules["COMBO.LOSEFAT_MUSCLE.LEAN_CUTOFF"]
            copy = _x(cutoff)["copy"]
            order: list[_Step] = [
                (
                    deficit[0],
                    "deficit",
                    copy["cut"],
                    [cutoff.id, *g.energy_rule_id(deficit[0]), *combo_ids],
                ),
                (
                    surplus[0],
                    "surplus",
                    copy["lean_bulk"],
                    [cutoff.id, *g.energy_rule_id(surplus[0]), *combo_ids],
                ),
            ]
            return Resolution(status="ok", phases=_sequenced(g, order), combo_rule_ids=combo_ids)
        elif request.sequence_confirmed:
            copy = _x(kb.rules["RESOLVER.CONTRADICTION"])["copy"]
            by_priority: list[_Step] = [
                (
                    t,
                    directions[t] or "maintenance",
                    copy["sequenced"],
                    [*g.energy_rule_id(t), *combo_ids],
                )
                for t in g.types
                if t in contradiction
            ]
            return Resolution(
                status="ok", phases=_sequenced(g, by_priority), combo_rule_ids=combo_ids
            )
        else:
            return Resolution(
                status="needs_ordering",
                combo_rule_ids=combo_ids,
                conflicting_goals=[t for t in g.types if t in contradiction],
                ordering_question=_x(kb.rules["RESOLVER.CONTRADICTION"])["copy"]["question"],
            )
    body_energy = g.direction(body_owner) if body_owner else None

    if event_date:
        phases = _event_timeline(g, event_date, body_owner, body_energy, body_rule_ids, combo_ids)
    elif "deadline_event" in owners and g.goal("deadline_event").event_date:
        deadline_date = g.goal("deadline_event").event_date
        if deadline_date > request.as_of:
            phases = _deadline_phases(g, deadline_date, combo_ids)
        else:
            phases = []
    else:
        phases = []

    if not phases:
        # One phase: the highest-tier owner, falling back to maintenance for condition goals.
        ranked = sorted(owners, key=g.tier_number)
        owner = "recomp" if body_owner == "recomp" else (ranked[0] if ranked else g.types[0])
        energy: Energy = g.direction(owner) or g.tier_rule["default_energy"]
        tier = g.tier(owner)
        rule_ids = [
            "RESOLVER.ONE_ENERGY_GOAL",
            *([tier.id] if tier else []),
            *(body_rule_ids if owner == body_owner else g.energy_rule_id(owner)),
            *combo_ids,
        ]
        phases = [
            _phase("main", request.as_of, None, energy, owner, rule_ids, _energy_copy(kb, energy))
        ]

    if safety.restricted("remove") and "deficit" in safety.restricted("remove"):
        phases = _remove_deficits(kb, phases)
    phases = [p.model_copy(update={"modifier_rule_ids": modifiers}) for p in phases]
    # Feasibility (Stage 3) needs the weight goal and any user-chosen rate on deficit phases.
    weight_goal = next(
        (
            x
            for x in g.goals
            if x.target_weight_kg is not None and x.target_weight_kg < request.profile.weight_kg
        ),
        None,
    )
    if weight_goal:
        phases = [
            p.model_copy(
                update={
                    "target_weight_kg": weight_goal.target_weight_kg,
                    "rate_pct_bw_week": weight_goal.rate_pct_bw_week,
                }
            )
            if p.energy == "deficit"
            else p
            for p in phases
        ]
    if safety.max_loss_rate:
        cap = safety.max_loss_rate.max_loss_pct_bw_per_week
        phases = [
            p.model_copy(
                update={
                    "max_rate_pct_bw": min(cap, p.max_rate_pct_bw or cap),
                    "rule_ids": [*p.rule_ids, safety.max_loss_rate.rule_id],
                }
            )
            if p.energy == "deficit"
            else p
            for p in phases
        ]
    return Resolution(status="ok", phases=_add_ramps(kb, phases), combo_rule_ids=combo_ids)
