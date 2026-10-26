"""Scoring a meal or day against a loam_score_profile (POST /v1/score/evaluate, Task 23)."""

from typing import Literal

from pydantic import Field

from .common import DayType, Recommended, StrictModel
from .response import ScoreTarget

ScoreLevel = Literal["meal", "day"]


class ScoreItem(StrictModel):
    """A food from the food table (its key) and the grams eaten."""

    key: str
    grams: float = Field(gt=0, le=5000)


class ScoredItem(StrictModel):
    key: str
    name: str
    grams: float
    kcal: float


class ComponentScore(Recommended):
    # The profile component (protein, sat_fat, ...) or micronutrient (iron, ...) scored.
    id: str
    # Which of the 7 weights it counts toward.
    weight_key: str
    type: str
    # The target as scored: scaled to the meal's share of the day at meal level.
    target: ScoreTarget
    # Invariant 7: None when any food lacks the nutrient; the part is then left out.
    actual: float | None = None
    score: float | None = Field(default=None, ge=0, le=100)
    # This part's share of the weights (a shared weight is split equally between its parts).
    weight: float = Field(ge=0)
    # Points this part adds to the overall score (weight x score / available weight).
    contribution: float | None = None
    available: bool


class LeftOut(StrictModel):
    """A component that doesn't enter the score or the coverage at this level."""

    id: str
    reason: Literal["not_at_meal_level", "disabled"]


class ScoreEvaluation(Recommended):
    level: ScoreLevel
    phase: str
    day_type: DayType
    items: list[ScoredItem]
    energy_kcal: float
    day_energy_kcal: float
    # Meal kcal / day kcal target at meal level; 1 at day level.
    energy_share: float
    # None when no component has data.
    score: float | None = Field(default=None, ge=0, le=100)
    coverage_pct: float = Field(ge=0, le=100)
    components: list[ComponentScore]
    left_out: list[LeftOut] = Field(default_factory=list)
