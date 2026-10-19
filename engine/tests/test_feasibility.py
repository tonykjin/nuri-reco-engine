"""Stage 3 feasibility (spec §4.4)."""

import datetime as dt
import json
import math
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from nuri_reco.feasibility import FeasibilityResult, check, weeks_to_reach
from nuri_reco.goals import PhasePlan, resolve
from nuri_reco.kb import load_kb
from nuri_reco.models import PlanRequest, Profile
from nuri_reco.safety import check as safety_check

PERSONAS = Path(__file__).parent / "personas"
START = dt.date(2026, 10, 16)


def persona(name: str) -> PlanRequest:
    raw = json.loads((PERSONAS / f"{name}.json").read_text(encoding="utf-8"))
    raw.pop("expect")
    return PlanRequest.model_validate(raw)


def profile(weight_kg: float = 72, height_cm: float = 165, sex: str = "female") -> Profile:
    return Profile.model_validate(
        {
            "age": 30,
            "sex": sex,
            "height_cm": height_cm,
            "weight_kg": weight_kg,
            "activity": "light",
            "training": {"resistance": False, "weekly_schedule": ["rest"] * 7},
        }
    )


def deficit_phase(
    target_weight_kg: float | None,
    weeks: float | None = 8,
    **extra: Any,
) -> PhasePlan:
    end = START + dt.timedelta(weeks=weeks) if weeks is not None else None
    return PhasePlan(
        name="deadline",
        start=START,
        end=end,
        energy="deficit",
        energy_owner="lose_fat",
        rule_ids=["GOAL.LOSE_FAT.ENERGY"],
        why="w",
        target_weight_kg=target_weight_kg,
        **extra,
    )


# --- Personas ---


def test_wedding_is_clamped() -> None:
    req = persona("wedding_8wk")
    kb = load_kb()
    phases = resolve(req, safety_check(req, kb), kb).phases
    result = check(phases[0], req.profile, kb)
    assert result.status == "clamped"
    # BMI 26.4 -> 0.75 %/week; -9 kg in 8 weeks needs 1.5625 %/week.
    assert result.rate_pct_bw_week == result.max_rate_pct_bw_week == 0.75
    assert result.required_rate_pct_bw_week == pytest.approx(9 / 8 / 72 * 100)
    # By hand: weight x (1 - rate) ^ weeks.
    assert result.projected_kg == pytest.approx(72 * (1 - 0.0075) ** 8)
    assert result.to_api().projected_kg_at_event == 67.8
    days = math.ceil(weeks_to_reach(72, 63, 0.75) * 7)
    assert result.reachable_date == START + dt.timedelta(days=days) == dt.date(2027, 2, 18)
    assert {"FEAS.DEADLINE", "GUARD.MAX_LOSS_RATE"} <= set(result.rule_ids)


def test_goal_bmi_low_is_blocked() -> None:
    req = persona("goal_bmi_low")
    target = req.goals[0].target_weight_kg
    result = check(deficit_phase(target), req.profile, load_kb())
    assert result.status == "blocked"
    assert result.projected_kg is None and result.reachable_date is None
    assert "GUARD.ED_RISK" in result.rule_ids


# --- Rates ---


def test_user_rate_above_max_is_clamped() -> None:
    result = check(deficit_phase(63, rate_pct_bw_week=2.0), profile(), load_kb())
    assert result.rate_pct_bw_week == 0.75
    assert result.user_rate_clamped


def test_user_rate_below_max_is_respected() -> None:
    # 72 -> 70 kg in 8 weeks needs 0.35 %/week; the user picks 0.25, so it's clamped at 0.25.
    result = check(deficit_phase(70, rate_pct_bw_week=0.25), profile(), load_kb())
    assert result.rate_pct_bw_week == 0.25 and not result.user_rate_clamped
    assert result.status == "clamped"
    assert result.projected_kg == pytest.approx(72 * (1 - 0.0025) ** 8)


def test_phase_cap_lowers_the_band() -> None:
    # Marathon base caps at 0.5 even though BMI 26.4 allows 0.75.
    result = check(deficit_phase(63, max_rate_pct_bw=0.5), profile(), load_kb())
    assert result.max_rate_pct_bw_week == 0.5


def test_bmi_bands() -> None:
    kb = load_kb()
    # 165 cm: 85 kg -> BMI 31.2, 72 -> 26.4, 60 -> 22.0
    for weight, band in [(85, 1.0), (72, 0.75), (60, 0.5)]:
        assert check(deficit_phase(55), profile(weight), kb).max_rate_pct_bw_week == band


# --- Other outcomes ---


def test_feasible_reaches_goal_by_deadline() -> None:
    result = check(deficit_phase(70, weeks=12), profile(), load_kb())
    assert result.status == "feasible"
    assert result.projected_kg == 70
    assert result.reachable_date is not None and result.reachable_date <= START + dt.timedelta(
        weeks=12
    )


def test_open_ended_phase_reports_reachable_date() -> None:
    result = check(deficit_phase(63, weeks=None), profile(), load_kb())
    assert result.status == "feasible"
    assert result.projected_kg is None
    assert result.reachable_date == dt.date(2027, 2, 18)


@pytest.mark.parametrize(
    "phase",
    [
        deficit_phase(None),
        deficit_phase(63).model_copy(update={"energy": "maintenance"}),
        deficit_phase(63).model_copy(update={"start": None}),
    ],
)
def test_nothing_to_check(phase: PhasePlan) -> None:
    result = check(phase, profile(), load_kb())
    assert result == FeasibilityResult(status="feasible", rule_ids=["FEAS.DEADLINE"])


# --- Property: the projection never implies a weekly loss above max_rate ---


@settings(max_examples=500, deadline=None)
@given(
    height_cm=st.floats(145, 205),
    weight_kg=st.floats(45, 200),
    loss_fraction=st.floats(0.001, 0.4),
    weeks=st.floats(1 / 7, 80),
    user_rate=st.one_of(st.none(), st.floats(0.05, 5)),
    phase_cap=st.one_of(st.none(), st.floats(0.1, 1.5)),
)
def test_projection_never_exceeds_max_rate(
    height_cm: float,
    weight_kg: float,
    loss_fraction: float,
    weeks: float,
    user_rate: float | None,
    phase_cap: float | None,
) -> None:
    goal_kg = weight_kg * (1 - loss_fraction)
    phase = deficit_phase(
        goal_kg, weeks=weeks, rate_pct_bw_week=user_rate, max_rate_pct_bw=phase_cap
    )
    result = check(phase, profile(weight_kg, height_cm), load_kb())
    if result.status == "blocked":
        assert goal_kg / (height_cm / 100) ** 2 < 18.5
        return

    assert result.max_rate_pct_bw_week is not None and result.rate_pct_bw_week is not None
    max_rate = result.max_rate_pct_bw_week / 100
    assert result.rate_pct_bw_week <= result.max_rate_pct_bw_week
    if user_rate is not None:
        assert result.rate_pct_bw_week == min(user_rate, result.max_rate_pct_bw_week)

    # Projected weight by the deadline: implied compound weekly loss <= max_rate.
    assert result.projected_kg is not None and result.weeks is not None
    assert result.projected_kg >= goal_kg - 1e-9
    implied = 1 - (result.projected_kg / weight_kg) ** (1 / result.weeks)
    assert implied <= max_rate + 1e-9

    # Reachable date: getting to the goal by then needs no more than max_rate per week.
    assert result.reachable_date is not None
    weeks_to_date = (result.reachable_date - START) / dt.timedelta(weeks=1)
    assert weeks_to_date + 1e-9 >= weeks_to_reach(weight_kg, goal_kg, result.max_rate_pct_bw_week)
