"""PlanResponse and its parts (spec section 10, goal_summary / loam_score_profile from 7b.6)."""

import datetime as dt
from typing import Literal, Self

from pydantic import Field, model_validator

from .common import DayType, Energy, Recommended, StrictModel

PlanStatus = Literal["ok", "clamped", "rd_review", "blocked", "needs_ordering"]
FeasibilityStatus = Literal["feasible", "clamped", "blocked"]


# --- Safety (Matrix F) ---


class SafetyFinding(Recommended):
    rule_id: str
    message: str


class Referral(SafetyFinding):
    to: list[str] = Field(min_length=1)


class Safety(StrictModel):
    blocks: list[SafetyFinding] = Field(default_factory=list)
    warnings: list[SafetyFinding] = Field(default_factory=list)
    referrals: list[Referral] = Field(default_factory=list)


# --- Phases and targets ---


class DayTargets(StrictModel):
    kcal: float = Field(gt=0)
    protein_g: float = Field(ge=0)
    carb_g: float = Field(ge=0)
    fat_g: float = Field(ge=0)


class PhaseTimeline(Recommended):
    """A phase's place in the plan. Dates are half-open: [start, end)."""

    name: str
    # None: starts when the previous phase ends (sequenced goals with no date yet).
    start: dt.date | None
    # None: open-ended.
    end: dt.date | None
    energy: Energy
    # Goal type that holds the energy direction in this phase (spec §7b.2 primary goal).
    energy_owner: str
    max_rate_pct_bw: float | None = Field(default=None, ge=0)
    # Targets ramp in over [ramp_start, ramp_end) instead of jumping (spec §4.1 rule 4).
    ramp_start: dt.date | None = None
    ramp_end: dt.date | None = None

    @model_validator(mode="after")
    def _dates_ordered(self) -> Self:
        if self.start and self.end and self.end < self.start:
            raise ValueError("phase end is before start")
        if self.ramp_start and self.ramp_end and self.ramp_end < self.ramp_start:
            raise ValueError("ramp end is before ramp start")
        return self


class Phase(PhaseTimeline):
    targets_by_day_type: dict[DayType, DayTargets]


class Feasibility(StrictModel):
    status: FeasibilityStatus
    projected_kg_at_event: float | None = None
    reachable_date: dt.date | None = None


# --- Patterns and foods ---


class PatternRecommendation(Recommended):
    id: str
    score: float = Field(ge=0, le=1)


class FoodRecommendation(Recommended):
    fdc_id: int
    name: str
    score: float = Field(ge=0, le=1)
    # Short bullet reasons ("19 g protein/100 kcal"); `why` is the one-line summary.
    reasons: list[str] = Field(default_factory=list)


# --- Goal summary (7b.6) ---


class GoalResolution(Recommended):
    type: str
    role: Literal["primary", "secondary"]
    resolved_as: str


class Pace(StrictModel):
    rate_pct_bw_week: float | None = None
    projected_kg_at_event: float | None = None
    reachable_date: dt.date | None = None


class GoalSummary(StrictModel):
    headline: str
    goals: list[GoalResolution]
    pace: Pace
    provenance: Literal["recommended"] = "recommended"


# --- Loam Score profile (Matrix G, 7b.6) ---


class ScoreTarget(StrictModel):
    unit: str
    low: float | None = None
    high: float | None = None
    min: float | None = None
    max: float | None = None


class ScoreComponent(Recommended):
    id: str
    type: str
    target: ScoreTarget
    applies_to: list[str] = Field(min_length=1)


class MicronutrientTarget(StrictModel):
    id: str
    target: float = Field(ge=0)
    unit: str
    window: str


class DisabledComponent(StrictModel):
    id: str
    reason: str


class PhaseScoreProfile(StrictModel):
    phase: str
    weights: dict[str, int]
    components: list[ScoreComponent]
    micronutrients: list[MicronutrientTarget] = Field(default_factory=list)
    disabled: list[DisabledComponent] = Field(default_factory=list)

    @model_validator(mode="after")
    def _weights_sum_to_100(self) -> Self:
        # Invariant 8.
        total = sum(self.weights.values())
        if total != 100:
            raise ValueError(f"score weights for phase {self.phase!r} sum to {total}, not 100")
        return self


class TopLever(StrictModel):
    component: str
    text: str


class LoamScoreProfile(StrictModel):
    by_phase: list[PhaseScoreProfile]
    top_levers: list[TopLever] = Field(default_factory=list)
    weight_rule_ids: list[str] = Field(min_length=1)
    provenance: Literal["recommended"] = "recommended"


# --- Plan ---


class PlanResponse(StrictModel):
    status: PlanStatus
    safety: Safety = Field(default_factory=Safety)
    phases: list[Phase] = Field(default_factory=list)
    feasibility: Feasibility | None = None
    # Empty when ?dry_run=true.
    patterns: list[PatternRecommendation] = Field(default_factory=list)
    foods: list[FoodRecommendation] = Field(default_factory=list)
    goal_summary: GoalSummary
    loam_score_profile: LoamScoreProfile
    citations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _blocked_has_no_targets(self) -> Self:
        # Invariant 1.
        if self.status == "blocked" and self.phases:
            raise ValueError("blocked plans must not return phases or targets")
        return self
