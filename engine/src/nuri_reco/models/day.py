"""A sample day of meals (spec §5 timing, §7.4 foods; POST /v1/recommendations/day)."""

from typing import Literal

from pydantic import Field

from .common import DayType, Recommended, StrictModel
from .response import DayTargets

ComposeSlot = Literal["breakfast", "lunch", "pre_session", "dinner", "snack"]
Macro = Literal["kcal", "protein_g", "carb_g", "fat_g"]


class Nutrients(StrictModel):
    kcal: float = Field(ge=0)
    protein_g: float = Field(ge=0)
    carb_g: float = Field(ge=0)
    fat_g: float = Field(ge=0)
    # Invariant 7: None when any food in the sum has no fiber value.
    fiber_g: float | None = Field(default=None, ge=0)


class GramRange(StrictModel):
    min: float = Field(ge=0)
    max: float = Field(ge=0)


class MealItem(Recommended):
    key: str
    fdc_id: int
    name: str
    grams: float = Field(gt=0)
    # The role the food fills in its meal (protein, carb, vegetable, fruit, fat).
    role: str
    nutrients: Nutrients


class Meal(Recommended):
    slot: ComposeSlot
    items: list[MealItem]
    nutrients: Nutrients
    # Soft per-meal guidance (TIMING.GUIDANCE_NOT_CAPS); None when the meal has no protein target.
    protein_target_g: float | None = None
    carb_target_g: GramRange | None = None


class SampleDay(Recommended):
    phase: str
    day_type: DayType
    meals: list[Meal]
    nutrients: Nutrients
    targets: DayTargets
    tolerance_pct: float
    # Signed % off target per macro: (actual - target) / target * 100.
    deviation_pct: dict[Macro, float]
    within_tolerance: bool
