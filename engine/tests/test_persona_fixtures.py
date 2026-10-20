"""Golden persona fixtures (spec §11.2): schema checks only (engine runs: test_personas.py).

Each tests/personas/*.json is a PlanRequest plus an `expect` object. The engine is checked
against the expectations later (runbook Task 11); here we only make sure the files are valid
and that the expectations point at real rules.
"""

import datetime as dt
import json
from pathlib import Path
from typing import Any, Literal, Self

import pytest
from pydantic import BaseModel, ConfigDict, Field, model_validator

from nuri_reco.goals import RESOLVER_PHASE_NAMES
from nuri_reco.kb import load_kb
from nuri_reco.models import DayType, Energy, PlanRequest

PERSONAS = Path(__file__).parent / "personas"
PERSONA_NAMES = [
    "maya",
    "novice_recomp",
    "marathon_fatloss",
    "wedding_8wk",
    "hybrid",
    "glp1_t2d_strength",
    "vegan_muscle",
    "under18",
    "pregnant",
    "goal_bmi_low",
]
SCORE_COMPONENTS = ["energy", "protein", "carb", "fiber", "micro", "pattern", "moderation"]


class Expect(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Range(Expect):
    min: float | None = None
    max: float | None = None

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("min > max")
        return self


class PhaseExpect(Expect):
    # None means every phase in the plan.
    name: str | None = None
    energy: list[Energy] | None = None
    # Targets that hold on every day type of the phase.
    targets: dict[str, Range] = Field(default_factory=dict)
    targets_by_day_type: dict[DayType, dict[str, Range]] = Field(default_factory=dict)


class FeasibilityExpect(Expect):
    status: Literal["feasible", "clamped", "blocked"]
    projected_kg_present: bool = False
    reachable_date_present: bool = False


class WeightsExpect(Expect):
    phase: str | None = None
    weights: dict[str, int]

    @model_validator(mode="after")
    def _complete(self) -> Self:
        if sorted(self.weights) != sorted(SCORE_COMPONENTS):
            raise ValueError(f"weights must cover {SCORE_COMPONENTS}")
        if sum(self.weights.values()) != 100:
            raise ValueError("weights must sum to 100")
        return self


class PersonaExpect(Expect):
    notes: str
    status: Literal["ok", "clamped", "rd_review", "blocked"]
    no_targets: bool = False
    phases: list[PhaseExpect] = Field(default_factory=list)
    deficit_only_in: list[str] | None = None
    feasibility: FeasibilityExpect | None = None
    required_rule_ids: list[str] = Field(default_factory=list)
    required_warnings: list[str] = Field(default_factory=list)
    required_blocks: list[str] = Field(default_factory=list)
    loam_score_weights: list[WeightsExpect] = Field(default_factory=list)
    loam_score_weight_minimums: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _blocked_has_no_targets(self) -> Self:
        if self.status == "blocked" and not (self.no_targets and not self.phases):
            raise ValueError("blocked personas expect no_targets and no phases")
        return self


def load_persona(name: str) -> tuple[PlanRequest, PersonaExpect]:
    raw: dict[str, Any] = json.loads((PERSONAS / f"{name}.json").read_text(encoding="utf-8"))
    expect = PersonaExpect.model_validate(raw.pop("expect"))
    return PlanRequest.model_validate(raw), expect


def bmi(weight_kg: float, height_cm: float) -> float:
    return weight_kg / (height_cm / 100) ** 2


def test_persona_set_is_complete() -> None:
    assert sorted(p.stem for p in PERSONAS.glob("*.json")) == sorted(PERSONA_NAMES)


@pytest.mark.parametrize("name", PERSONA_NAMES)
def test_persona_is_valid(name: str) -> None:
    load_persona(name)


@pytest.mark.parametrize("name", PERSONA_NAMES)
def test_persona_expectations_reference_real_rules(name: str) -> None:
    _, expect = load_persona(name)
    kb = load_kb()
    referenced = expect.required_rule_ids + expect.required_warnings + expect.required_blocks
    assert set(referenced) <= set(kb.rules), set(referenced) - set(kb.rules)
    phase_names = {p.name for p in kb.phases.phases} | RESOLVER_PHASE_NAMES
    named = [p.name for p in expect.phases] + [w.phase for w in expect.loam_score_weights]
    named += expect.deficit_only_in or []
    assert {n for n in named if n is not None} <= phase_names
    assert set(expect.loam_score_weight_minimums) <= set(SCORE_COMPONENTS)


def test_maya_matches_prd() -> None:
    _, expect = load_persona("maya")
    targets = expect.phases[0].targets
    assert targets["kcal"].min is not None and targets["kcal"].max is not None
    assert targets["kcal"].min <= 1800 <= targets["kcal"].max
    assert targets["protein_g"].min is not None and targets["protein_g"].max is not None
    assert targets["protein_g"].min <= 140 <= targets["protein_g"].max
    assert expect.loam_score_weights[0].weights == dict(
        zip(SCORE_COMPONENTS, [20, 20, 5, 15, 15, 15, 10], strict=True)
    )


def test_marathon_fatloss_matches_section_10_example() -> None:
    req, _ = load_persona("marathon_fatloss")
    spec_example = json.loads(
        (Path(__file__).parent / "fixtures" / "spec_plan_request.json").read_text(encoding="utf-8")
    )
    assert req == PlanRequest.model_validate(spec_example)
    assert req.constraints.allergens == ["peanuts"]
    assert req.constraints.diet == "pescatarian"


def test_wedding_is_infeasible() -> None:
    req, expect = load_persona("wedding_8wk")
    lose_fat = next(g for g in req.goals if g.type == "lose_fat")
    deadline = next(g for g in req.goals if g.type == "deadline_event")
    assert lose_fat.target_weight_kg is not None and deadline.event_date is not None
    weeks = (deadline.event_date - req.as_of) / dt.timedelta(weeks=1)
    current_kg = req.profile.weight_kg
    required_pct = (current_kg - lose_fat.target_weight_kg) / weeks / current_kg
    bands = (load_kb().rules["GUARD.MAX_LOSS_RATE"].model_extra or {})["bands"]
    top_band = max(b["max_loss_pct_bw_per_week"] for b in bands)
    assert required_pct * 100 > top_band
    assert expect.feasibility is not None and expect.feasibility.status == "clamped"


def test_goal_bmi_low_is_below_threshold() -> None:
    req, _ = load_persona("goal_bmi_low")
    target = req.goals[0].target_weight_kg
    assert target is not None
    threshold = (load_kb().rules["FEAS.DEADLINE"].model_extra or {})["blocked_goal_bmi_below"]
    assert bmi(target, req.profile.height_cm) < threshold


def test_blocked_personas() -> None:
    blocked = [n for n in PERSONA_NAMES if load_persona(n)[1].status == "blocked"]
    assert sorted(blocked) == ["goal_bmi_low", "pregnant", "under18"]
