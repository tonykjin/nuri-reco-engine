"""Decision trace: each engine stage in order and every rule it fired (Task 22, RD review)."""

from typing import Any

from pydantic import Field

from .common import StrictModel
from .response import PlanResponse


class TraceCitation(StrictModel):
    id: str
    label: str
    url: str | None = None


class TraceRule(StrictModel):
    """A knowledge rule as an RD reviews it: the matrix text, flags and sources."""

    id: str
    # The knowledge file it lives in (e.g. "targets" for knowledge/targets.yaml).
    file: str
    text: str | None = None
    # The plain-language explanation shown to users, when the rule has one.
    why: str | None = None
    verify: bool
    heuristic: bool
    citations: list[TraceCitation] = Field(default_factory=list)


class TraceStage(StrictModel):
    # Stage key: safety, goals, feasibility, expenditure, targets, score_profile, patterns,
    # foods, summary; children carry per-phase detail.
    stage: str
    # Rules this stage fired, in the order it used them.
    rule_ids: list[str] = Field(default_factory=list)
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    children: list["TraceStage"] = Field(default_factory=list)


class Trace(StrictModel):
    stages: list[TraceStage]
    # Every rule fired across the stages, in order of first use.
    rules_fired: list[str]
    rules: dict[str, TraceRule]


class TracedPlan(StrictModel):
    plan: PlanResponse
    trace: Trace
