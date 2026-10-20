"""Golden personas (spec §11.2): run each persona through engine.plan and assert its `expect`.

The expectations live in tests/personas/*.json and are never loosened here; the fixture schema is
checked in test_persona_fixtures.py.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from nuri_reco.engine import all_rule_ids, plan
from nuri_reco.expenditure import ColdStartExpenditure
from nuri_reco.kb import load_kb
from nuri_reco.models import PlanRequest, PlanResponse
from nuri_reco.models.response import DayTargets, Phase

PERSONAS = Path(__file__).parent / "personas"
NAMES = sorted(p.stem for p in PERSONAS.glob("*.json"))


def load(name: str) -> tuple[PlanRequest, dict[str, Any]]:
    raw = json.loads((PERSONAS / f"{name}.json").read_text(encoding="utf-8"))
    expect = raw.pop("expect")
    return PlanRequest.model_validate(raw), expect


def target_value(key: str, day: DayTargets, req: PlanRequest) -> float:
    """A target the persona names: a DayTargets field or a derived value."""
    if key == "carb_g_per_kg":
        return day.carb_g / req.profile.weight_kg
    if key == "deficit_pct_tdee":
        tdee = ColdStartExpenditure(load_kb()).tdee(req.profile)
        return (tdee - day.kcal) / tdee * 100
    value: float = getattr(day, key)
    return value


def in_range(value: float, rng: dict[str, float | None], label: str) -> None:
    lo, hi = rng.get("min"), rng.get("max")
    assert lo is None or value >= lo - 1e-6, f"{label}: {value:.2f} < {lo}"
    assert hi is None or value <= hi + 1e-6, f"{label}: {value:.2f} > {hi}"


def check_phase(phase: Phase, exp: dict[str, Any], req: PlanRequest) -> None:
    if exp.get("energy"):
        assert phase.energy in exp["energy"], f"{phase.name}: energy {phase.energy}"
    for key, rng in exp.get("targets", {}).items():
        for day_type, day in phase.targets_by_day_type.items():
            in_range(target_value(key, day, req), rng, f"{phase.name}/{day_type}/{key}")
    for day_type, targets in exp.get("targets_by_day_type", {}).items():
        day = phase.targets_by_day_type[day_type]
        for key, rng in targets.items():
            in_range(target_value(key, day, req), rng, f"{phase.name}/{day_type}/{key}")


def assert_expect(resp: PlanResponse, expect: dict[str, Any], req: PlanRequest) -> None:
    assert resp.status == expect["status"]

    if expect.get("no_targets"):
        assert resp.phases == []
        assert resp.loam_score_profile.by_phase == []
        assert resp.goal_summary.pace.model_dump(exclude_none=True) == {}

    phases = {p.name: p for p in resp.phases}
    for exp in expect.get("phases", []):
        name = exp.get("name")
        targets = [phases[name]] if name else resp.phases
        assert targets, f"no phase {name!r}"
        for phase in targets:
            check_phase(phase, exp, req)

    if expect.get("deficit_only_in") is not None:
        deficit = {p.name for p in resp.phases if p.energy == "deficit"}
        assert deficit <= set(expect["deficit_only_in"]), deficit

    if expect.get("feasibility"):
        exp = expect["feasibility"]
        assert resp.feasibility is not None
        assert resp.feasibility.status == exp["status"]
        if exp.get("projected_kg_present"):
            assert resp.feasibility.projected_kg_at_event is not None
        if exp.get("reachable_date_present"):
            assert resp.feasibility.reachable_date is not None

    cited = set(all_rule_ids(resp))
    missing = set(expect.get("required_rule_ids", [])) - cited
    assert not missing, f"rule ids not in the plan: {sorted(missing)}"
    warnings = {w.rule_id for w in resp.safety.warnings}
    assert set(expect.get("required_warnings", [])) <= warnings, warnings
    blocks = {b.rule_id for b in resp.safety.blocks}
    assert set(expect.get("required_blocks", [])) <= blocks, blocks

    by_phase = {p.phase: p for p in resp.loam_score_profile.by_phase}
    for exp in expect.get("loam_score_weights", []):
        name = exp.get("phase")
        profiles = [by_phase[name]] if name else list(by_phase.values())
        assert profiles, f"no score profile for phase {name!r}"
        for p in profiles:
            assert p.weights == exp["weights"], f"{p.phase}: {p.weights}"
    for component, minimum in expect.get("loam_score_weight_minimums", {}).items():
        for p in by_phase.values():
            assert p.weights_exact[component] >= minimum, f"{p.phase}: {component}"


@pytest.mark.parametrize("name", NAMES)
def test_persona(name: str) -> None:
    req, expect = load(name)
    resp = plan(req)
    # Invariant 8: every plan returns goal_summary + loam_score_profile.
    assert resp.goal_summary.headline and resp.loam_score_profile
    assert_expect(resp, expect, req)
