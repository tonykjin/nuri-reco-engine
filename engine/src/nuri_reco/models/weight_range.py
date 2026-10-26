"""Target weight range, first milestone and target bounds (Task 25, spec §4.4b). Weights in kg."""

from typing import Literal

from pydantic import Field

from .common import Recommended

WeightRangeStatus = Literal["ok", "hidden", "blocked"]
RangeBasis = Literal["bmi", "bmi_older", "body_fat"]


class RecommendedRange(Recommended):
    min_kg: float
    max_kg: float
    basis: RangeBasis


class Milestone(Recommended):
    """A first step for a fat-loss goal (WEIGHT.RANGE.MILESTONE)."""

    min_kg: float
    max_kg: float


class TargetBounds(Recommended):
    """Bounds and a suggested default target for one weight goal."""

    min_kg: float
    max_kg: float
    step_kg: float
    default_kg: float


class WeightRangeResponse(Recommended):
    # ok: numbers below. hidden: number-hiding mode, no numbers. blocked: safety blocked the plan.
    status: WeightRangeStatus
    current_kg: float | None = None
    recommended: RecommendedRange | None = None
    milestone: Milestone | None = None
    # Keyed by goal type (lose_fat, gain_weight), for the weight goals in the request.
    target_bounds: dict[str, TargetBounds] = Field(default_factory=dict)
    citations: list[str] = Field(default_factory=list)
