"""Target weight range for the onboarding slider (Task 25; spec §4.4b, weight_range.yaml)."""

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.main import app
from nuri_reco import explain
from nuri_reco.kb import load_kb
from nuri_reco.models import PlanRequest, WeightRangeResponse
from nuri_reco.weight_range import weight_range

PERSONAS = Path(__file__).parent / "personas"
client = TestClient(app, raise_server_exceptions=False)


def request(
    goal: str = "lose_fat",
    *,
    target: float | None = None,
    flags: dict[str, Any] | None = None,
    **profile: Any,
) -> PlanRequest:
    raw = json.loads((PERSONAS / "maya.json").read_text(encoding="utf-8"))
    raw.pop("expect")
    raw["profile"].update(profile)
    raw["profile"]["flags"].update(flags or {})
    raw["goals"] = [{"type": goal, "priority": 1, "target_weight_kg": target}]
    return PlanRequest.model_validate(raw)


def wr(req: PlanRequest) -> WeightRangeResponse:
    return weight_range(req, load_kb())


# --- Ranges (WEIGHT.RANGE.BMI, .OLDER, .BODY_FAT) ---


def test_adult_range_is_bmi_18_5_to_24_9_with_bounds_rounded_inward() -> None:
    resp = wr(request(sex="female", age=30, height_cm=168, weight_kg=76))
    assert resp.status == "ok"
    assert resp.recommended is not None
    assert resp.recommended.basis == "bmi"
    # 52.21 and 70.28 kg, rounded inward to 0.1 kg.
    assert (resp.recommended.min_kg, resp.recommended.max_kg) == (52.3, 70.2)
    assert resp.milestone is None
    assert "WEIGHT.RANGE.BMI" in resp.rule_ids


def test_older_adults_use_bmi_23_to_29_9() -> None:
    resp = wr(request(sex="male", age=70, height_cm=175, weight_kg=85))
    assert resp.recommended is not None
    assert resp.recommended.basis == "bmi_older"
    assert (resp.recommended.min_kg, resp.recommended.max_kg) == (70.5, 91.5)


def test_body_fat_range_comes_from_fat_free_mass() -> None:
    resp = wr(request(sex="male", age=30, height_cm=180, weight_kg=90, body_fat_pct=15))
    assert resp.recommended is not None
    assert resp.recommended.basis == "body_fat"
    # FFM 76.5 kg ÷ (1 − 0.14) = 88.95, ÷ (1 − 0.24) = 100.66.
    assert (resp.recommended.min_kg, resp.recommended.max_kg) == (89.0, 100.6)


def test_body_fat_range_never_goes_below_the_floor() -> None:
    # Very lean and light: FFM ÷ (1 − 0.21) would sit under BMI 18.5.
    resp = wr(request(sex="female", age=30, height_cm=175, weight_kg=50, body_fat_pct=12))
    assert resp.recommended is not None
    assert resp.recommended.min_kg == 56.7  # BMI 18.5 at 175 cm = 56.66 kg, rounded up
    assert "GUARD.ED_RISK" in resp.recommended.rule_ids


# --- Milestone (WEIGHT.RANGE.MILESTONE) ---


def test_bmi_30_or_more_adds_a_5_to_10_percent_milestone() -> None:
    resp = wr(request(height_cm=175, weight_kg=120))
    assert resp.milestone is not None
    assert (resp.milestone.min_kg, resp.milestone.max_kg) == (108.0, 114.0)
    assert resp.target_bounds["lose_fat"].default_kg == 114.0


def test_no_milestone_for_a_gain_goal() -> None:
    assert wr(request("gain_weight", height_cm=175, weight_kg=120)).milestone is None


# --- Sliders (WEIGHT.RANGE.SLIDER) ---


def test_lose_slider_runs_from_the_ed_floor_to_current_weight() -> None:
    resp = wr(request(sex="female", age=30, height_cm=168, weight_kg=76))
    slider = resp.target_bounds["lose_fat"]
    assert (slider.min_kg, slider.max_kg, slider.step_kg) == (52.3, 76.0, 0.5)
    assert slider.default_kg == 72.2  # 5% below current
    assert {"WEIGHT.RANGE.SLIDER", "GUARD.ED_RISK"} <= set(slider.rule_ids)


def test_the_lowest_slider_weight_passes_the_ed_guardrail() -> None:
    resp = wr(request(sex="female", age=30, height_cm=168, weight_kg=76))
    lowest = resp.target_bounds["lose_fat"].min_kg
    assert wr(request(sex="female", age=30, height_cm=168, weight_kg=76, target=lowest)).status == (
        "ok"
    )


def test_gain_slider_runs_from_current_to_the_range_top_or_15_percent_up() -> None:
    resp = wr(request("gain_weight", height_cm=175, weight_kg=60))
    slider = resp.target_bounds["gain_weight"]
    # Range top 76.26 kg beats 60 × 1.15 = 69 kg.
    assert (slider.min_kg, slider.max_kg) == (60.0, 76.2)
    assert slider.default_kg == 63.0
    assert "lose_fat" not in resp.target_bounds


def test_already_below_the_floor_gets_no_lose_slider() -> None:
    resp = wr(request(sex="female", age=30, height_cm=175, weight_kg=55))
    assert resp.status == "ok"
    assert resp.recommended is not None
    assert "lose_fat" not in resp.target_bounds
    assert resp.why == explain.text(load_kb(), "WEIGHT.RANGE.SLIDER", "at_floor")


def test_goals_without_a_weight_goal_get_no_sliders() -> None:
    resp = wr(request("build_muscle"))
    assert resp.status == "ok"
    assert resp.target_bounds == {}
    assert resp.recommended is not None


# --- Safety first: blocked and hidden carry no numbers ---


def assert_no_numbers(resp: WeightRangeResponse) -> None:
    assert resp.current_kg is None
    assert resp.recommended is None
    assert resp.milestone is None
    assert resp.target_bounds == {}


@pytest.mark.parametrize(
    ("goal", "profile", "status", "rule_id"),
    [
        ("lose_fat", {"flags": {"scoff_score": 2}}, "blocked", "GUARD.ED_RISK"),
        ("gain_weight", {"flags": {"scoff_score": 2}}, "hidden", "GUARD.ED_RISK"),
        ("gain_weight", {"flags": {"ed_history": True}}, "hidden", "GUARD.ED_RISK"),
        ("lose_fat", {"flags": {"pregnant": True}}, "blocked", "GUARD.PREGNANCY"),
        ("gain_weight", {"flags": {"pregnant": True}}, "hidden", "GUARD.PREGNANCY"),
        ("gain_weight", {"flags": {"breastfeeding": True}}, "hidden", "GUARD.PREGNANCY"),
        ("lose_fat", {"age": 16}, "blocked", "GUARD.UNDER_18"),
        ("gain_weight", {"age": 16}, "hidden", "GUARD.UNDER_18"),
    ],
)
def test_guardrails_hide_every_number(
    goal: str, profile: dict[str, Any], status: str, rule_id: str
) -> None:
    resp = wr(request(goal, **profile))
    assert resp.status == status
    assert rule_id in resp.rule_ids
    assert_no_numbers(resp)
    assert resp.why


def test_a_target_under_the_floor_is_blocked() -> None:
    resp = wr(request(height_cm=168, weight_kg=56, target=50))
    assert resp.status == "blocked"
    assert "GUARD.ED_RISK" in resp.rule_ids
    assert_no_numbers(resp)


# --- Invariants ---


@pytest.mark.parametrize(
    "req",
    [
        request(height_cm=168, weight_kg=76),
        request(height_cm=175, weight_kg=120),
        request("gain_weight", height_cm=175, weight_kg=60),
        request(sex="male", height_cm=180, weight_kg=90, body_fat_pct=15),
        request("gain_weight", flags={"scoff_score": 3}),
        request(flags={"pregnant": True}),
    ],
)
def test_every_output_has_provenance_rules_and_a_why(req: PlanRequest) -> None:
    kb = load_kb()
    resp = wr(req)
    items = [resp, resp.recommended, resp.milestone, *resp.target_bounds.values()]
    for item in [i for i in items if i is not None]:
        assert item.provenance == "recommended"
        assert item.rule_ids
        assert item.why
    missing = [r for r in explain.rule_ids_in(resp) if not explain.has(kb, r, "rule")]
    assert not missing
    assert resp.citations


def test_deterministic() -> None:
    req = request(sex="male", age=70, height_cm=175, weight_kg=85)
    assert wr(req) == wr(req)


# --- API ---


def test_endpoint_returns_the_range() -> None:
    body = request(sex="female", age=30, height_cm=168, weight_kg=76).model_dump(mode="json")
    resp = client.post("/v1/goals/weight-range", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "ok"
    assert (data["recommended"]["min_kg"], data["recommended"]["max_kg"]) == (52.3, 70.2)
    assert set(data["target_bounds"]) == {"lose_fat"}


def test_endpoint_rejects_unknown_goal_types() -> None:
    body = request().model_dump(mode="json")
    body["goals"][0]["type"] = "nope"
    resp = client.post("/v1/goals/weight-range", json=body)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "unknown_goal_type"
