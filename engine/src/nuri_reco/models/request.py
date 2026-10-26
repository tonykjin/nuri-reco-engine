"""PlanRequest: the domain input to POST /v1/plan (spec section 10)."""

import datetime as dt
from typing import Annotated, Literal

from pydantic import Field, field_validator

from .common import DayType, Sex, StrictModel

UnitInterval = Annotated[float, Field(ge=0, le=1)]


class Training(StrictModel):
    resistance: bool
    weekly_schedule: list[DayType] = Field(min_length=7, max_length=7)
    # Used for recomp eligibility (spec §4.2); None = unknown.
    experience: Literal["novice", "intermediate", "advanced", "returning"] | None = None


class Flags(StrictModel):
    """Safety inputs for Matrix F. Medication and condition ids are defined in guardrails.yaml."""

    pregnant: bool = False
    breastfeeding: bool = False
    ckd_stage: int | None = Field(default=None, ge=1, le=5)
    medications: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    scoff_score: int | None = Field(default=None, ge=0, le=5)
    ed_history: bool = False
    # Self-reported, e.g. missed_periods, stress_fractures, persistent_fatigue.
    reported_symptoms: list[str] = Field(default_factory=list)


class Profile(StrictModel):
    age: int = Field(gt=0)
    sex: Sex
    height_cm: float = Field(gt=0)
    weight_kg: float = Field(gt=0)
    # Invariant 7: unknown stays None, never 0.
    body_fat_pct: float | None = Field(default=None, gt=0, lt=100)
    activity: str
    training: Training
    flags: Flags = Field(default_factory=Flags)


class Goal(StrictModel):
    # Goal types are Matrix A ids; the knowledge base validates them.
    type: str
    priority: int = Field(ge=1)
    target_weight_kg: float | None = Field(default=None, gt=0)
    event: str | None = None
    event_date: dt.date | None = None
    # User-chosen weekly loss, % of body weight; never exceeds the Matrix F max (spec §4.4).
    rate_pct_bw_week: float | None = Field(default=None, gt=0)


class Constraints(StrictModel):
    allergens: list[str] = Field(default_factory=list)
    diet: str | None = None
    religious: list[str] = Field(default_factory=list)
    # Spec §9: wheat, barley, rye and non-certified oats are excluded.
    celiac: bool = False


class Preferences(StrictModel):
    taste: dict[str, UnitInterval] = Field(default_factory=dict)
    dislikes: list[str] = Field(default_factory=list)
    cook_time_min: int | None = Field(default=None, gt=0)
    budget: str | None = None
    cuisines: list[str] = Field(default_factory=list)
    # A Matrix D pattern id the user asked for (e.g. "mediterranean"); boosts its adherence.
    pattern_pref: str | None = None


class DailyLog(StrictModel):
    """One day of logs. Invariant 7: a day without an intake log or a weigh-in stays None."""

    date: dt.date
    intake_kcal: float | None = Field(default=None, ge=0)
    weight_kg: float | None = Field(default=None, gt=0)


class PlanRequest(StrictModel):
    profile: Profile
    goals: list[Goal] = Field(min_length=1)
    constraints: Constraints = Field(default_factory=Constraints)
    preferences: Preferences = Field(default_factory=Preferences)
    as_of: dt.date
    # The user confirmed the goal order, so contradictory goals are sequenced by priority
    # instead of returning needs_ordering (spec §4.1 rule 2).
    sequence_confirmed: bool = False
    # Logged intake and weigh-ins (spec §2 Monitor & Evaluate). Empty: the Mifflin-St Jeor
    # estimate; enough logs switch targets to adaptive expenditure (expenditure.yaml).
    history: list[DailyLog] = Field(default_factory=list)

    @field_validator("history")
    @classmethod
    def _one_log_per_day(cls, history: list[DailyLog]) -> list[DailyLog]:
        dates = [d.date for d in history]
        if len(dates) != len(set(dates)):
            raise ValueError("history has more than one log for a date")
        return sorted(history, key=lambda d: d.date)
