"""Synthetic intake and weigh-in logs with a known true expenditure (Task 22).

For tests of the adaptive estimator and the /trace demo only; never real user data. Seeded, so
the same arguments always give the same logs.
"""

import datetime as dt
import random
from collections.abc import Collection

from nuri_reco.engine import plan
from nuri_reco.expenditure import ColdStartExpenditure
from nuri_reco.kb import KnowledgeBase
from nuri_reco.models import DailyLog, PlanRequest, PlanResponse, TracedPlan
from nuri_reco.trace import Tracer


def synthetic_history(
    *,
    start: dt.date,
    days: int,
    true_tdee_kcal: float,
    intake_kcal: float,
    start_weight_kg: float,
    kcal_per_kg: float,
    weight_noise_kg: float,
    intake_noise_kcal: float,
    seed: int,
    missing_intake_days: Collection[int] = (),
    missing_weigh_in_days: Collection[int] = (),
) -> list[DailyLog]:
    """Daily logs of eating intake_kcal every day: the true weight moves by
    (intake - true TDEE) / kcal_per_kg a day, logged intake adds logging noise and weigh-ins add
    scale noise. Missing days stay None."""
    rng = random.Random(seed)
    weight = start_weight_kg
    logs: list[DailyLog] = []
    for i in range(days):
        logged = intake_kcal + rng.gauss(0, intake_noise_kcal)
        scale = weight + rng.gauss(0, weight_noise_kg)
        logs.append(
            DailyLog(
                date=start + dt.timedelta(days=i),
                intake_kcal=None if i in missing_intake_days else round(logged),
                weight_kg=None if i in missing_weigh_in_days else round(scale, 2),
            )
        )
        weight += (intake_kcal - true_tdee_kcal) / kcal_per_kg
    return logs


def demo_history(
    request: PlanRequest, cold: PlanResponse, kb: KnowledgeBase
) -> tuple[list[DailyLog], float]:
    """The /trace demo's logs (EXPENDITURE.SIMULATION): weeks of eating the first phase's average
    target while true expenditure sits above the cold-start estimate, ending the day before
    as_of at about the profile's weight. Returns the logs and the true TDEE behind them."""
    sim = kb.expenditure.simulation.model_extra or {}
    kcal_per_kg = (kb.expenditure.energy_density.model_extra or {})["kcal_per_kg"]
    profile = request.profile
    true_tdee = ColdStartExpenditure(kb).tdee(profile) * (1 + sim["true_tdee_offset_pct"] / 100)
    schedule = profile.training.weekly_schedule
    by_day = cold.phases[0].targets_by_day_type if cold.phases else {}
    intake = (
        sum(by_day[d].kcal for d in schedule) / len(schedule)
        if all(d in by_day for d in schedule)
        else true_tdee
    )
    days = sim["weeks"] * (kb.expenditure.takeover.model_extra or {})["days_per_week"]
    logs = synthetic_history(
        start=request.as_of - dt.timedelta(days=days),
        days=days,
        true_tdee_kcal=true_tdee,
        intake_kcal=intake,
        # Start where the user would have been, so the last weigh-in lands near today's weight.
        start_weight_kg=profile.weight_kg + (true_tdee - intake) * days / kcal_per_kg,
        kcal_per_kg=kcal_per_kg,
        weight_noise_kg=sim["weight_noise_kg"],
        intake_noise_kcal=sim["intake_noise_kcal"],
        seed=sim["seed"],
    )
    return logs, true_tdee


def traced_demo(request: PlanRequest, kb: KnowledgeBase) -> TracedPlan:
    """The /trace demo: the request's plan traced after simulated weeks of logs, with a first
    stage showing the simulation and the true TDEE the estimator should find."""
    cold = plan(request, kb, dry_run=True)
    if cold.status in ("blocked", "needs_ordering"):
        return plan(request, kb, trace=True)
    logs, true_tdee = demo_history(request, cold, kb)
    traced = plan(request.model_copy(update={"history": logs}), kb, trace=True)
    tracer = Tracer(kb)
    tracer.stage(
        "simulation",
        rule_ids=[kb.expenditure.simulation.id],
        inputs={"as_of": request.as_of, "weight_kg": request.profile.weight_kg},
        outputs={"true_tdee_kcal": true_tdee, "history": logs},
    )
    tracer.stages.extend(traced.trace.stages)
    return TracedPlan(plan=traced.plan, trace=tracer.build())
