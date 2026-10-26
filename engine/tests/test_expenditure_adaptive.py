"""Adaptive expenditure on synthetic logs (Task 22; spec §2 Monitor & Evaluate)."""

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from nuri_reco import expenditure
from nuri_reco.engine import plan
from nuri_reco.expenditure import AdaptiveExpenditure, ColdStartExpenditure, trend_weights
from nuri_reco.kb import load_kb
from nuri_reco.models import DailyLog, PlanRequest
from nuri_reco.simulate import demo_history, synthetic_history

PERSONAS = Path(__file__).parent / "personas"
START = dt.date(2026, 9, 1)
TRUE_TDEE = 2400.0
# Agreed in Task 22: daily weigh-in noise SD 0.3 kg, intake logging noise SD 100 kcal.
WEIGHT_NOISE_KG = 0.3
INTAKE_NOISE_KCAL = 100.0


def request(name: str) -> PlanRequest:
    raw = json.loads((PERSONAS / f"{name}.json").read_text(encoding="utf-8"))
    raw.pop("expect")
    return PlanRequest.model_validate(raw)


def x(rule_id: str) -> dict[str, Any]:
    return load_kb().rules[rule_id].model_extra or {}


def logs(days: int, deficit: float = 500, seed: int = 0, **kw: Any) -> list[DailyLog]:
    args: dict[str, Any] = {
        "start": START,
        "days": days,
        "true_tdee_kcal": TRUE_TDEE,
        "intake_kcal": TRUE_TDEE - deficit,
        "start_weight_kg": 80.0,
        "kcal_per_kg": x("EXPENDITURE.ENERGY_DENSITY")["kcal_per_kg"],
        "weight_noise_kg": WEIGHT_NOISE_KG,
        "intake_noise_kcal": INTAKE_NOISE_KCAL,
        "seed": seed,
    }
    return synthetic_history(**(args | kw))


def maya() -> Any:
    return request("maya").profile


# --- Runbook Task 22: within ±5% of the true TDEE by week 4 ---


@pytest.mark.parametrize("deficit", [0, 250, 500, 750])
@pytest.mark.parametrize("seed", range(10))
def test_converges_within_5pct_by_week_4(deficit: float, seed: int) -> None:
    exp = AdaptiveExpenditure(load_kb(), logs(28, deficit, seed))
    assert exp.measured.week == 4
    assert exp.method == "adaptive"
    assert exp.tdee(maya()) == pytest.approx(TRUE_TDEE, rel=0.05)


def test_8_week_series_updates_expenditure_week_by_week() -> None:
    kb, profile = load_kb(), maya()
    cold = ColdStartExpenditure(kb).tdee(profile)
    takeover = x("EXPENDITURE.TAKEOVER")
    history = logs(56, seed=3)
    for week in range(1, 9):
        est = AdaptiveExpenditure(kb, history[: week * 7]).estimate(profile)
        assert est.week == week
        if week < takeover["blend_from_week"]:
            assert est.method == "mifflin_st_jeor" and est.estimate_kcal == cold
        elif week < takeover["measured_from_week"]:
            assert est.method == "blended"
            assert est.measured_pct == takeover["blend_measured_pct"]
            assert est.tdee_kcal is not None
            share = takeover["blend_measured_pct"] / 100
            assert est.estimate_kcal == pytest.approx((1 - share) * cold + share * est.tdee_kcal)
        else:
            assert est.method == "adaptive"
            assert est.estimate_kcal == pytest.approx(TRUE_TDEE, rel=0.05)


def test_plan_with_logs_uses_the_measured_expenditure() -> None:
    req = request("maya")
    history = logs(56, deficit=0, start=req.as_of - dt.timedelta(days=56))
    cold, adaptive = plan(req), plan(req.model_copy(update={"history": history}))
    # Maya's cold start is about 2,230 kcal; her logs say 2,400, so her targets rise.
    assert adaptive.phases[0].targets_by_day_type["rest"].kcal > (
        cold.phases[0].targets_by_day_type["rest"].kcal
    )
    assert "EXPENDITURE.ENERGY_BALANCE" in adaptive.phases[0].rule_ids
    assert "EXPENDITURE.ENERGY_BALANCE" not in cold.phases[0].rule_ids
    assert "ENERGY.MIFFLIN_ST_JEOR" not in adaptive.phases[0].rule_ids


def test_logs_after_as_of_are_ignored() -> None:
    req = request("maya")
    future = logs(56, start=req.as_of + dt.timedelta(days=1))
    exp = expenditure.for_request(req.model_copy(update={"history": future}), load_kb())
    assert isinstance(exp, ColdStartExpenditure)


# --- Missing data stays missing (invariant 7) ---


def test_missing_days_are_left_out_not_zero() -> None:
    gaps = set(range(0, 28, 3))
    history = logs(
        28,
        weight_noise_kg=0,
        intake_noise_kcal=0,
        missing_intake_days=gaps,
        missing_weigh_in_days=gaps,
    )
    assert sum(d.intake_kcal is None for d in history) == len(gaps)
    exp = AdaptiveExpenditure(load_kb(), history)
    assert exp.measured.intake_days == 28 - len(gaps)
    assert exp.measured.avg_intake_kcal == pytest.approx(TRUE_TDEE - 500, abs=1)
    assert exp.tdee(maya()) == pytest.approx(TRUE_TDEE, rel=0.005)


def test_too_few_logs_keep_the_cold_start_estimate() -> None:
    balance = x("EXPENDITURE.ENERGY_BALANCE")
    too_few = set(range(28 - balance["min_intake_days"] + 1))
    exp = AdaptiveExpenditure(load_kb(), logs(28, missing_intake_days=too_few))
    assert exp.measured.intake_days == balance["min_intake_days"] - 1
    assert exp.measured.tdee_kcal is None
    assert exp.method == "mifflin_st_jeor"
    assert exp.tdee(maya()) == ColdStartExpenditure(load_kb()).tdee(maya())


def test_only_the_window_counts() -> None:
    window = x("EXPENDITURE.ENERGY_BALANCE")["window_days"]
    # Eight weeks of logs, but only the last four are inside the window.
    exp = AdaptiveExpenditure(load_kb(), logs(56))
    assert exp.measured.intake_days == window
    assert exp.measured.window_start == START + dt.timedelta(days=56 - window)


# --- Trend weight (EMA) ---


def test_trend_weight_is_an_ema_that_skips_missing_weigh_ins() -> None:
    a = x("EXPENDITURE.TREND_WEIGHT")["smoothing"]
    history = [
        DailyLog(date=START, weight_kg=80),
        DailyLog(date=START + dt.timedelta(days=1), weight_kg=81),
        DailyLog(date=START + dt.timedelta(days=2), intake_kcal=2000),
        DailyLog(date=START + dt.timedelta(days=3), weight_kg=79),
    ]
    second = 80 + a * (81 - 80)
    assert [w for _, w in trend_weights(history, a)] == pytest.approx(
        [80, second, second + a * (79 - second)]
    )


# --- Generator and request validation ---


def test_generator_is_deterministic() -> None:
    assert logs(56, seed=7) == logs(56, seed=7)
    assert logs(56, seed=7) != logs(56, seed=8)


def test_demo_history_ends_before_as_of_near_todays_weight() -> None:
    req, kb = request("maya"), load_kb()
    history, true_tdee = demo_history(req, plan(req, dry_run=True), kb)
    sim = x("EXPENDITURE.SIMULATION")
    assert len(history) == sim["weeks"] * 7
    assert history[-1].date == req.as_of - dt.timedelta(days=1)
    cold = ColdStartExpenditure(kb).tdee(req.profile)
    assert true_tdee == pytest.approx(cold * (1 + sim["true_tdee_offset_pct"] / 100))
    assert AdaptiveExpenditure(kb, history).tdee(req.profile) == pytest.approx(true_tdee, rel=0.05)
    last = history[-1].weight_kg
    assert last is not None and abs(last - req.profile.weight_kg) < 1.5


def test_history_rejects_two_logs_for_one_date() -> None:
    raw = request("maya").model_dump(mode="json")
    raw["history"] = [{"date": "2026-10-01", "weight_kg": 70}] * 2
    with pytest.raises(ValidationError, match="more than one log"):
        PlanRequest.model_validate(raw)
