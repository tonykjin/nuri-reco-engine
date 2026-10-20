"""engine.plan(): paths the golden personas don't cover, plus response-wide invariants."""

import json
from pathlib import Path

import pytest

from nuri_reco import demo
from nuri_reco.engine import all_rule_ids, plan
from nuri_reco.kb import load_kb
from nuri_reco.models import PlanRequest

PERSONAS = Path(__file__).parent / "personas"
NAMES = sorted(p.stem for p in PERSONAS.glob("*.json"))


def persona(name: str) -> PlanRequest:
    raw = json.loads((PERSONAS / f"{name}.json").read_text(encoding="utf-8"))
    raw.pop("expect")
    return PlanRequest.model_validate(raw)


GAIN_LOSE = PlanRequest.model_validate(
    {
        "profile": {
            "age": 30,
            "sex": "female",
            "height_cm": 168,
            "weight_kg": 70,
            "activity": "moderate",
            "training": {"resistance": False, "weekly_schedule": ["rest"] * 7},
        },
        "goals": [{"type": "gain_weight", "priority": 1}, {"type": "lose_fat", "priority": 2}],
        "as_of": "2026-10-16",
    }
)


def test_needs_ordering_has_no_numbers() -> None:
    resp = plan(GAIN_LOSE)
    assert resp.status == "needs_ordering"
    assert resp.phases == [] and resp.loam_score_profile.by_phase == []
    assert [g.resolved_as for g in resp.goal_summary.goals] == [
        "waiting for you to choose which goal comes first"
    ] * 2
    assert "RESOLVER.CONTRADICTION" in all_rule_ids(resp)


def test_confirmed_order_sequences_goals() -> None:
    resp = plan(GAIN_LOSE.model_copy(update={"sequence_confirmed": True}))
    assert resp.status == "ok"
    assert [p.energy for p in resp.phases] == ["surplus", "deficit"]
    assert [g.role for g in resp.goal_summary.goals] == ["primary", "secondary"]
    assert resp.goal_summary.goals[0].resolved_as.startswith("phase 1 of 2: surplus")


@pytest.mark.parametrize("name", NAMES)
def test_rule_ids_and_citations_resolve(name: str) -> None:
    kb = load_kb()
    resp = plan(persona(name))
    ids = all_rule_ids(resp)
    assert ids and set(ids) <= set(kb.rules), set(ids) - set(kb.rules)
    assert set(resp.citations) <= set(kb.citation_index)
    for finding in [*resp.safety.blocks, *resp.safety.warnings, *resp.safety.referrals]:
        assert finding.provenance == "recommended" and finding.why


def test_plan_is_deterministic() -> None:
    req = persona("marathon_fatloss")
    assert plan(req) == plan(req)


def test_marathon_projection_carries_weight() -> None:
    resp = plan(persona("marathon_fatloss"))
    # Base deficit at 0.5 %/week from 72 kg, then maintenance until after the race.
    assert resp.feasibility is not None and resp.feasibility.status == "feasible"
    assert resp.goal_summary.pace.projected_kg_at_event == pytest.approx(68.4, abs=0.05)
    assert (
        resp.goal_summary.headline == "Lose fat at a steady pace while fueling your marathon build."
    )


def test_demo_prints_plan(capsys: pytest.CaptureFixture[str]) -> None:
    assert demo.main(["maya"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "ok" and "goal_summary" in out and "loam_score_profile" in out


def test_demo_unknown_persona() -> None:
    with pytest.raises(SystemExit, match="no persona or file 'nobody'"):
        demo.main(["nobody"])
