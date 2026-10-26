"""Trace mode (Task 22): every stage in order, every rule fired, off by default."""

import json
from pathlib import Path

import pytest

from nuri_reco import explain
from nuri_reco.engine import plan
from nuri_reco.kb import load_kb
from nuri_reco.models import PlanRequest, TraceStage
from nuri_reco.simulate import traced_demo
from nuri_reco.trace import rule_ids_of

PERSONAS = Path(__file__).parent / "personas"
NAMES = sorted(p.stem for p in PERSONAS.glob("*.json"))
FULL = [
    "safety",
    "goals",
    "feasibility",
    "expenditure",
    "targets",
    "score_profile",
    "patterns",
    "foods",
    "summary",
]


def request(name: str) -> PlanRequest:
    raw = json.loads((PERSONAS / f"{name}.json").read_text(encoding="utf-8"))
    raw.pop("expect")
    return PlanRequest.model_validate(raw)


def walk(stages: list[TraceStage]) -> list[TraceStage]:
    return [n for s in stages for n in (s, *walk(s.children))]


@pytest.mark.parametrize("name", NAMES)
def test_trace_mode_does_not_change_the_response(name: str) -> None:
    req = request(name)
    assert plan(req, trace=True).plan == plan(req)
    assert plan(req, dry_run=True, trace=True).plan == plan(req, dry_run=True)


def test_maya_trace_has_every_stage_in_order() -> None:
    trace = plan(request("maya"), trace=True).trace
    assert [s.stage for s in trace.stages] == FULL
    targets = trace.stages[FULL.index("targets")]
    assert [c.outputs["targets"]["phase"] for c in targets.children] == [
        p.name for p in plan(request("maya")).phases
    ]
    assert trace.stages[0].rule_ids, "safety records the rules it checked"


@pytest.mark.parametrize("name", NAMES)
def test_every_rule_in_the_plan_is_in_the_trace(name: str) -> None:
    traced = plan(request(name), trace=True)
    fired = traced.trace.rules_fired
    assert set(explain.rule_ids_in(traced.plan)) <= set(fired)
    in_order = [r for s in walk(traced.trace.stages) for r in s.rule_ids]
    assert fired == list(dict.fromkeys(in_order))
    assert set(traced.trace.rules) == set(fired), "every fired rule has its details"


def test_rule_details_come_from_the_knowledge_base() -> None:
    kb = load_kb()
    rules = plan(request("maya"), trace=True).trace.rules
    msj = rules["ENERGY.MIFFLIN_ST_JEOR"]
    assert msj.file == "targets"
    assert msj.text == kb.rules["ENERGY.MIFFLIN_ST_JEOR"].text
    assert msj.why == explain.text(kb, "ENERGY.MIFFLIN_ST_JEOR")
    for rule in rules.values():
        source = kb.rules[rule.id]
        assert (rule.verify, rule.heuristic) == (source.verify, source.heuristic)
        assert [c.id for c in rule.citations] == source.citation_ids


@pytest.mark.parametrize(("name", "last"), [("pregnant", "safety"), ("under18", "safety")])
def test_blocked_trace_stops_after_safety(name: str, last: str) -> None:
    traced = plan(request(name), trace=True)
    assert traced.plan.status == "blocked"
    assert [s.stage for s in traced.trace.stages] == [last, "summary"]
    assert traced.trace.stages[0].outputs["blocked"] is True


def test_trace_is_json_ready_and_deterministic() -> None:
    first = plan(request("hybrid"), trace=True)
    json.dumps(first.model_dump(mode="json"))
    assert plan(request("hybrid"), trace=True) == first


def test_simulated_trace_shows_the_adaptive_estimate() -> None:
    kb = load_kb()
    traced = traced_demo(request("maya"), kb)
    stages = {s.stage: s for s in traced.trace.stages}
    assert traced.trace.stages[0].stage == "simulation"
    assert "EXPENDITURE.SIMULATION" in traced.trace.rules_fired
    estimate = stages["expenditure"].outputs["estimate"]
    assert estimate["method"] == "adaptive"
    true_tdee = stages["simulation"].outputs["true_tdee_kcal"]
    assert estimate["estimate_kcal"] == pytest.approx(true_tdee, rel=0.05)
    assert "EXPENDITURE.ENERGY_BALANCE" in stages["expenditure"].rule_ids


def test_rule_ids_of_reads_every_rule_id_key() -> None:
    value = {"rule_ids": ["A.B"], "x": [{"combo_rule_ids": ["C.D"], "rule_id": "E.F"}]}
    assert rule_ids_of(value) == ["A.B", "C.D", "E.F"]
