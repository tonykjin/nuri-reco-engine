"""Inputs for food ranking (spec §7.4 context boosts)."""

from typing import Literal

from pydantic import Field

from .common import DayType, StrictModel

MealSlot = Literal["any", "breakfast", "lunch", "dinner", "snack", "pre_race", "during", "recovery"]
Ripeness = Literal["unripe", "ripe", "peak", "overripe"]


class PantryItem(StrictModel):
    """A food in the Virtual Pantry (key from foods.json), with its NIR ripeness when known."""

    key: str
    ripeness: Ripeness | None = None
    peaks_tonight: bool = False


class RemainingTargets(StrictModel):
    """What's left of today's targets; unknown values stay None."""

    kcal: float | None = Field(default=None, ge=0)
    protein_g: float | None = Field(default=None, ge=0)
    carb_g: float | None = Field(default=None, ge=0)
    fat_g: float | None = Field(default=None, ge=0)
    fiber_g: float | None = Field(default=None, ge=0)


class FoodContext(StrictModel):
    meal_slot: MealSlot = "any"
    day_type: DayType = "rest"
    # A phase name from the plan; None: the first phase.
    phase: str | None = None
    pantry: list[PantryItem] = Field(default_factory=list)
    remaining: RemainingTargets | None = None
