"""Stage 2 goal resolution (spec §4.1-4.3)."""

import copy
import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest

from nuri_reco.goals import PhasePlan, Resolution, _add_ramps, resolve
from nuri_reco.kb import load_kb
from nuri_reco.models import PlanRequest
from nuri_reco.safety import check

PERSONAS = Path(__file__).parent / "personas"
WEEK = dt.timedelta(weeks=1)


def persona(name: str, **updates: Any) -> PlanRequest:
    raw = json.loads((PERSONAS / f"{name}.json").read_text(encoding="utf-8"))
    raw.pop("expect")
    raw.update(updates)
    return PlanRequest.model_validate(raw)


def run(req: PlanRequest) -> Resolution:
    kb = load_kb()
    return resolve(req, check(req, kb), kb)


def request(goals: list[dict[str, Any]], **profile: Any) -> PlanRequest:
    raw: dict[str, Any] = {
        "profile": {
            "age": 30,
            "sex": "female",
            "height_cm": 168,
            "weight_kg": 70,
            "activity": "moderate",
            "training": {"resistance": True, "weekly_schedule": ["rest"] * 7},
        },
        "goals": goals,
        "as_of": "2026-10-16",
    }
    for key, value in profile.items():
        if isinstance(value, dict) and isinstance(raw["profile"].get(key), dict):
            raw["profile"][key] = {**raw["profile"][key], **value}
        else:
            raw["profile"][key] = value
    return PlanRequest.model_validate(raw)


def by_name(res: Resolution) -> dict[str, PhasePlan]:
    return {p.name: p for p in res.phases}


# --- Marathon + fat loss (spec §4.2, §4.3, §7b.6 dates) ---


def test_marathon_phase_sequence() -> None:
    res = run(persona("marathon_fatloss"))
    assert res.status == "ok"
    assert [p.name for p in res.phases] == [
        "base",
        "build",
        "peak",
        "taper",
        "race_week",
        "recovery",
        "resume",
    ]


def test_marathon_peak_starts_six_weeks_out() -> None:
    race = dt.date(2027, 4, 18)
    phases = by_name(run(persona("marathon_fatloss")))
    assert phases["base"].start == dt.date(2026, 10, 16)
    assert phases["base"].end == phases["build"].start == race - 16 * WEEK == dt.date(2026, 12, 27)
    assert phases["peak"].start == race - 6 * WEEK == dt.date(2027, 3, 7)
    assert phases["taper"].start == race - 3 * WEEK
    assert phases["race_week"].start == race - WEEK
    assert phases["race_week"].end == phases["recovery"].start == race + dt.timedelta(days=1)


def test_marathon_deficit_only_in_base_and_resume() -> None:
    res = run(persona("marathon_fatloss"))
    assert [p.name for p in res.phases if p.energy == "deficit"] == ["base", "resume"]
    phases = by_name(res)
    base = phases["base"]
    assert base.energy_owner == "lose_fat"
    assert base.max_rate_pct_bw == 0.5
    assert base.deficit_day_types == ["rest", "easy"]
    assert {"COMBO.LOSEFAT_ENDURANCE", "PHASE.BASE"} <= set(base.rule_ids)
    # Build: maintenance, small rest-day deficit at most; the event owns energy from build on.
    assert phases["build"].energy == "maintenance" and phases["build"].allow_rest_day_deficit
    for name in ["peak", "taper", "race_week", "recovery"]:
        assert phases[name].energy == "maintenance"
        assert phases[name].energy_owner == "endurance_event"
        assert not phases[name].allow_rest_day_deficit
    assert "PHASE.PEAK" in phases["peak"].rule_ids


def test_marathon_ramps_into_build_and_resume() -> None:
    phases = by_name(run(persona("marathon_fatloss")))
    build = phases["build"]
    assert build.start is not None
    assert (build.ramp_start, build.ramp_end) == (build.start - WEEK, build.start)
    assert "RESOLVER.RAMP" in build.rule_ids
    # No energy change, no ramp: peak is fully fueled from its first day.
    assert phases["peak"].ramp_start is None


def test_timeline_starts_mid_build() -> None:
    res = run(persona("marathon_fatloss", as_of="2027-01-15"))
    assert [p.name for p in res.phases][:2] == ["build", "peak"]
    assert res.phases[0].start == dt.date(2027, 1, 15)


def test_past_event_is_ignored() -> None:
    res = run(persona("marathon_fatloss", as_of="2027-06-01"))
    assert [p.name for p in res.phases] == ["main"]
    assert res.phases[0].energy_owner == "lose_fat"


# --- Recomp and contradictions (spec §4.1 rule 2, §4.2) ---


def test_novice_recomp() -> None:
    res = run(persona("novice_recomp"))
    assert res.status == "ok"
    [phase] = res.phases
    assert (phase.energy, phase.energy_owner) == ("deficit", "recomp")
    assert {"COMBO.LOSEFAT_MUSCLE", "GOAL.RECOMP.ENERGY"} <= set(phase.rule_ids)


def test_trained_and_lean_cut_then_bulk() -> None:
    req = request(
        [{"type": "lose_fat", "priority": 1}, {"type": "build_muscle", "priority": 2}],
        body_fat_pct=22,
        training={"experience": "advanced"},
    )
    res = run(req)
    assert res.status == "ok"
    assert [(p.energy, p.energy_owner) for p in res.phases] == [
        ("deficit", "lose_fat"),
        ("surplus", "build_muscle"),
    ]
    assert res.phases[0].start == req.as_of
    assert res.phases[1].start is None  # dated once feasibility knows when the cut ends
    assert "COMBO.LOSEFAT_MUSCLE.LEAN_CUTOFF" in res.phases[0].rule_ids


def test_trained_but_body_fat_unknown_is_recomp() -> None:
    req = request(
        [{"type": "lose_fat", "priority": 1}, {"type": "build_muscle", "priority": 2}],
        training={"experience": "advanced"},
    )
    assert run(req).phases[0].energy_owner == "recomp"


GAIN_LOSE = [{"type": "gain_weight", "priority": 1}, {"type": "lose_fat", "priority": 2}]


def test_gain_and_lose_needs_ordering() -> None:
    res = run(request(GAIN_LOSE, training={"resistance": False}))
    assert res.status == "needs_ordering"
    assert res.phases == []
    assert res.conflicting_goals == ["gain_weight", "lose_fat"]
    assert res.ordering_question
    assert "COMBO.GAINWEIGHT_LOSEFAT" in res.combo_rule_ids


def test_gain_and_lose_sequenced_once_confirmed() -> None:
    req = request(GAIN_LOSE, training={"resistance": False})
    res = run(req.model_copy(update={"sequence_confirmed": True}))
    assert res.status == "ok"
    assert [(p.energy, p.energy_owner) for p in res.phases] == [
        ("surplus", "gain_weight"),
        ("deficit", "lose_fat"),
    ]


def test_gain_and_lose_recomp_when_eligible() -> None:
    res = run(request(GAIN_LOSE))
    assert res.status == "ok"
    assert res.phases[0].energy_owner == "recomp"


# --- Single goals, deadline, condition goals ---


def test_maya_single_phase() -> None:
    res = run(persona("maya"))
    [phase] = res.phases
    assert (phase.name, phase.energy, phase.energy_owner) == ("main", "deficit", "lose_fat")
    assert phase.start == dt.date(2026, 10, 16) and phase.end is None
    assert phase.max_rate_pct_bw == 0.5  # BMI 24.8 band from Matrix F
    assert "GUARD.MAX_LOSS_RATE" in phase.rule_ids


def test_wedding_deadline_then_step_back() -> None:
    phases = run(persona("wedding_8wk")).phases
    assert [(p.name, p.energy, p.energy_owner) for p in phases] == [
        ("deadline", "deficit", "deadline_event"),
        ("step_back", "maintenance", "deadline_event"),
    ]
    wedding = dt.date(2026, 12, 11)
    assert phases[0].end == phases[1].start == wedding
    assert phases[0].max_rate_pct_bw == 0.75  # BMI 26.4
    # Spec: step back to maintenance over 2-4 weeks after the event.
    assert (phases[1].ramp_start, phases[1].ramp_end) == (wedding, wedding + 4 * WEEK)


def test_condition_goals_never_own_energy() -> None:
    [phase] = run(persona("glp1_t2d_strength")).phases
    assert (phase.energy, phase.energy_owner) == ("maintenance", "strength_hybrid")
    assert "COMBO.GLP1_T2D_STRENGTH" in phase.rule_ids
    [alone] = run(request([{"type": "t2d", "priority": 1}])).phases
    assert (alone.energy, alone.energy_owner) == ("maintenance", "t2d")


def test_vegan_modifiers_attached() -> None:
    [phase] = run(persona("vegan_muscle")).phases
    assert phase.energy == "surplus"
    assert phase.modifier_rule_ids == [
        "COMBO.MUSCLE_VEGAN.UPPER_PROTEIN",
        "COMBO.MUSCLE_VEGAN.NUTRIENTS",
    ]


# --- Safety interplay ---


@pytest.mark.parametrize("name", ["under18", "pregnant", "goal_bmi_low"])
def test_blocked_returns_no_phases(name: str) -> None:
    res = run(persona(name))
    assert (res.status, res.phases) == ("blocked", [])


def test_low_energy_availability_removes_deficits() -> None:
    req = persona("marathon_fatloss")
    flags = req.profile.flags.model_copy(update={"reported_symptoms": ["missed_periods"]})
    req = req.model_copy(
        update={"profile": req.profile.model_copy(update={"flags": flags})}, deep=True
    )
    res = run(req)
    assert all(p.energy == "maintenance" for p in res.phases)
    assert not any(p.allow_rest_day_deficit for p in res.phases)
    assert "GUARD.LOW_EA" in by_name(res)["base"].rule_ids


# --- Ramp lengths and invariants ---


def test_full_flip_ramps_fourteen_days() -> None:
    start = dt.date(2027, 1, 1)
    common: dict[str, Any] = {"rule_ids": ["X.Y"], "why": "w", "energy_owner": "o"}
    phases = [
        PhasePlan(name="a", start=start, end=start + 8 * WEEK, energy="deficit", **common),
        PhasePlan(name="b", start=start + 8 * WEEK, end=None, energy="surplus", **common),
    ]
    b = _add_ramps(load_kb(), phases)[1]
    assert (b.ramp_start, b.ramp_end) == (start + 6 * WEEK, start + 8 * WEEK)


@pytest.mark.parametrize(
    "name", ["maya", "novice_recomp", "marathon_fatloss", "wedding_8wk", "hybrid", "vegan_muscle"]
)
def test_every_phase_is_owned_and_explained(name: str) -> None:
    res = run(persona(name))
    assert res.phases
    kb = load_kb()
    for phase in res.phases:
        assert phase.energy_owner
        assert phase.why and phase.provenance == "recommended"
        assert set(phase.rule_ids) <= set(kb.rules), set(phase.rule_ids) - set(kb.rules)
    # Phases are contiguous where dated.
    for prev, nxt in zip(res.phases, res.phases[1:], strict=False):
        if prev.end and nxt.start:
            assert prev.end == nxt.start


def test_resolve_is_pure() -> None:
    req = persona("marathon_fatloss")
    before = copy.deepcopy(req.model_dump())
    assert run(req) == run(req)
    assert req.model_dump() == before
