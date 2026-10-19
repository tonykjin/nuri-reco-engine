"""Stage 3: deadline feasibility (spec §4.4, Matrix F max loss rate).

    required_rate = (current_kg - goal_kg) / weeks / current_kg
    max_rate      = BMI band (Matrix F), never above the phase's own cap
    if required_rate > rate: projected_kg = current_kg * (1 - rate) ** weeks; status = "clamped"
    else:                    status = "feasible"
    if goal_BMI < 18.5:      status = "blocked"

`rate` is the user's chosen rate when given, but never above max_rate. check() is pure.
"""

import datetime as dt
import math
from typing import Literal

from pydantic import Field

from nuri_reco.goals import PhasePlan
from nuri_reco.kb import KnowledgeBase
from nuri_reco.models import Profile, StrictModel
from nuri_reco.models.response import Feasibility
from nuri_reco.safety import bmi, loss_rate_band

FeasibilityStatus = Literal["feasible", "clamped", "blocked"]


class FeasibilityResult(StrictModel):
    status: FeasibilityStatus
    rule_ids: list[str] = Field(min_length=1)
    # Rates are % of body weight per week.
    max_rate_pct_bw_week: float | None = None
    rate_pct_bw_week: float | None = None
    required_rate_pct_bw_week: float | None = None
    # The user asked for a faster rate than max_rate and was clamped to it.
    user_rate_clamped: bool = False
    weeks: float | None = None
    projected_kg: float | None = None
    reachable_date: dt.date | None = None

    def to_api(self) -> Feasibility:
        return Feasibility(
            status=self.status,
            projected_kg_at_event=None
            if self.projected_kg is None
            else round(self.projected_kg, 1),
            reachable_date=self.reachable_date,
        )


def weeks_to_reach(current_kg: float, goal_kg: float, rate_pct: float) -> float:
    """Weeks for compound loss at rate_pct per week to take current_kg down to goal_kg."""
    if goal_kg >= current_kg:
        return 0.0
    return math.log(goal_kg / current_kg) / math.log(1 - rate_pct / 100)


def check(phase: PhasePlan, profile: Profile, kb: KnowledgeBase) -> FeasibilityResult:
    """Feasibility of a deficit phase's weight goal by its end date (or open-ended)."""
    deadline = kb.rules["FEAS.DEADLINE"]
    goal_kg = phase.target_weight_kg
    if goal_kg is None or phase.energy != "deficit" or phase.start is None:
        return FeasibilityResult(status="feasible", rule_ids=[deadline.id])

    blocked_below = (deadline.model_extra or {})["blocked_goal_bmi_below"]
    if bmi(goal_kg, profile.height_cm) < blocked_below:
        return FeasibilityResult(status="blocked", rule_ids=[deadline.id, "GUARD.ED_RISK"])

    band = loss_rate_band(bmi(profile.weight_kg, profile.height_cm), kb)
    max_rate = band.max_loss_pct_bw_per_week
    if phase.max_rate_pct_bw is not None:
        max_rate = min(max_rate, phase.max_rate_pct_bw)
    requested = phase.rate_pct_bw_week
    rate = min(requested, max_rate) if requested is not None else max_rate
    rule_ids = [deadline.id, band.rule_id]

    current_kg = profile.weight_kg
    to_goal = dt.timedelta(weeks=weeks_to_reach(current_kg, goal_kg, rate))
    reachable = phase.start + dt.timedelta(days=math.ceil(to_goal / dt.timedelta(days=1)))
    common = {
        "rule_ids": rule_ids,
        "max_rate_pct_bw_week": max_rate,
        "rate_pct_bw_week": rate,
        "user_rate_clamped": requested is not None and requested > max_rate,
    }
    if phase.end is None:
        # Open-ended: no deadline to miss; report when the goal is reached at the planned rate.
        return FeasibilityResult(status="feasible", reachable_date=reachable, **common)

    weeks = (phase.end - phase.start) / dt.timedelta(weeks=1)
    required = (current_kg - goal_kg) / weeks / current_kg * 100 if weeks > 0 else math.inf
    if required > rate:
        return FeasibilityResult(
            status="clamped",
            weeks=weeks,
            required_rate_pct_bw_week=required,
            projected_kg=current_kg * (1 - rate / 100) ** weeks,
            reachable_date=reachable,
            **common,
        )
    return FeasibilityResult(
        status="feasible",
        weeks=weeks,
        required_rate_pct_bw_week=max(required, 0.0),
        projected_kg=max(goal_kg, current_kg * (1 - rate / 100) ** weeks),
        reachable_date=reachable,
        **common,
    )
