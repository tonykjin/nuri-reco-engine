"""Shared types and the provenance base for every recommendation-bearing output."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Matrix C day types.
DayType = Literal["rest", "easy", "quality", "long", "carb_load"]
Sex = Literal["female", "male"]
Energy = Literal["deficit", "maintenance", "surplus"]


class StrictModel(BaseModel):
    """Base for all API models: unknown fields are rejected so spec drift fails loudly."""

    model_config = ConfigDict(extra="forbid")


class Recommended(StrictModel):
    """Invariant 2: every output item carries provenance, the rules behind it and a why."""

    provenance: Literal["recommended"] = "recommended"
    rule_ids: list[str] = Field(min_length=1)
    why: str = Field(min_length=1)
