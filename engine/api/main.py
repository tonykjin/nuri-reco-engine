"""FastAPI app for the Nuri recommendation engine (spec §10 endpoints table).

The API takes a domain PlanRequest and knows nothing about onboarding screens (invariant 9).
Every non-2xx response uses the error shape in api/errors.py.
"""

from collections import Counter
from typing import Annotated, Literal

from fastapi import Body, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import Field

from api import errors, examples
from api.errors import ApiError
from nuri_reco import compose, explain, foods, safety, score_eval, simulate, weight_range
from nuri_reco.engine import plan
from nuri_reco.kb import GoalsFile, GuardrailsFile, PatternsFile, ScoreWeightsFile, load_kb
from nuri_reco.models import (
    DayType,
    FoodContext,
    FoodRecommendation,
    LoamScoreProfile,
    PlanRequest,
    PlanResponse,
    SampleDay,
    ScoreEvaluation,
    ScoreItem,
    ScoreLevel,
    StrictModel,
    TracedPlan,
    WeightRangeResponse,
)
from nuri_reco.models.response import PlanStatus
from nuri_reco.safety import SafetyResult

CORS_ORIGINS = ["http://localhost:3000"]

app = FastAPI(
    title="Nuri Recommendation Engine",
    version="0.1.0",
    description=(
        "Goal-aware nutrition plans from a domain `PlanRequest` (spec §10). Every recommendation "
        "carries `provenance`, `rule_ids` and a plain-language `why`."
    ),
    responses=errors.RESPONSES,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
errors.install(app)

PlanBody = Annotated[PlanRequest, Body(openapi_examples=examples.plan_examples())]


# --- Request and response models the engine doesn't already define ---


class FoodRecommendationsRequest(StrictModel):
    request: PlanRequest
    context: FoodContext = Field(default_factory=FoodContext)
    limit: int | None = Field(default=None, ge=1, le=100)


class FoodRecommendationsResponse(StrictModel):
    status: PlanStatus
    foods: list[FoodRecommendation]
    citations: list[str] = Field(default_factory=list)


class DayRecommendationRequest(StrictModel):
    request: PlanRequest
    # None: the user's most common day type.
    day_type: DayType | None = None
    # A phase name from the plan; None: the first phase.
    phase: str | None = None


class DayRecommendationResponse(StrictModel):
    status: PlanStatus
    # None when the plan is blocked or waiting for the user to order their goals.
    day: SampleDay | None = None
    citations: list[str] = Field(default_factory=list)


class TraceRequest(StrictModel):
    request: PlanRequest
    # Demo only: trace after simulated weeks of logs (EXPENDITURE.SIMULATION), so the
    # expenditure stage shows the adaptive estimate. Replaces any history in the request.
    simulate_history: bool = False


class ScoreEvaluateRequest(StrictModel):
    request: PlanRequest
    items: list[ScoreItem] = Field(min_length=1, max_length=50)
    level: ScoreLevel = "meal"
    # None: the user's most common day type.
    day_type: DayType | None = None
    # A phase name from the plan; None: the first phase.
    phase: str | None = None


class ScoreEvaluateResponse(StrictModel):
    status: PlanStatus
    # None when the plan is blocked or waiting for the user to order their goals.
    evaluation: ScoreEvaluation | None = None
    citations: list[str] = Field(default_factory=list)


class FoodListing(StrictModel):
    key: str
    fdc_id: int
    name: str
    group: str


class SafetyCheckResponse(SafetyResult):
    status: Literal["ok", "rd_review", "blocked"]


class Health(StrictModel):
    status: Literal["ok"]


def _check_goal_types(request: PlanRequest) -> None:
    known = {g.type for g in load_kb().goals.goals}
    unknown = [
        {"loc": ["body", "goals", i, "type"], "msg": f"unknown goal type {g.type!r}"}
        for i, g in enumerate(request.goals)
        if g.type not in known
    ]
    if unknown:
        raise ApiError(422, "unknown_goal_type", "Unknown goal type.", unknown)


# --- Routes ---


@app.get("/health", tags=["meta"])
def health() -> Health:
    return Health(status="ok")


@app.post("/v1/plan", tags=["plan"], responses=errors.INVALID)
def create_plan(
    request: PlanBody,
    dry_run: Annotated[
        bool, Query(description="Skip patterns and foods; for fast, repeated calls.")
    ] = False,
) -> PlanResponse:
    """The full plan: safety, phases, targets, feasibility, goal summary, Loam Score profile,
    patterns and foods."""
    _check_goal_types(request)
    return plan(request, dry_run=dry_run)


@app.post("/v1/plan/trace", tags=["plan"], responses=errors.INVALID)
def trace_plan(
    body: Annotated[TraceRequest, Body(openapi_examples=examples.trace_examples())],
) -> TracedPlan:
    """The full plan plus its decision trace: each engine stage in order, every rule it fired,
    and each rule's text, flags and citations, for dietitian review. /v1/plan is unchanged."""
    _check_goal_types(body.request)
    if body.simulate_history:
        return simulate.traced_demo(body.request, load_kb())
    return plan(body.request, trace=True)


@app.post("/v1/score/profile", tags=["score"], responses=errors.INVALID)
def score_profile(request: PlanBody) -> LoamScoreProfile:
    """Only the Loam Score profile: weights and personal targets per phase, and the top levers.
    A blocked request returns an empty `by_phase`."""
    _check_goal_types(request)
    return plan(request, dry_run=True).loam_score_profile


@app.post("/v1/score/evaluate", tags=["score"], responses=errors.INVALID)
def score_evaluate(
    body: Annotated[ScoreEvaluateRequest, Body(openapi_examples=examples.evaluate_examples())],
) -> ScoreEvaluateResponse:
    """Score a meal or day (food keys + grams) against the plan's Loam Score profile, with data
    coverage shown separately. Blocked or unordered plans return no evaluation."""
    _check_goal_types(body.request)
    full = plan(body.request, dry_run=True)
    evaluation: ScoreEvaluation | None = None
    if full.status not in ("blocked", "needs_ordering"):
        schedule = body.request.profile.training.weekly_schedule
        evaluation = score_eval.evaluate(
            full,
            body.items,
            load_kb(),
            foods.load_foods(),
            level=body.level,
            day_type=body.day_type or Counter(schedule).most_common(1)[0][0],
            phase=body.phase,
        )
    resp = ScoreEvaluateResponse(status=full.status, evaluation=evaluation)
    return resp.model_copy(update={"citations": explain.collect_citations(resp, load_kb())})


@app.post("/v1/recommendations/foods", tags=["recommendations"], responses=errors.INVALID)
def recommend_foods(
    body: Annotated[FoodRecommendationsRequest, Body(openapi_examples=examples.food_examples())],
) -> FoodRecommendationsResponse:
    """Ranked foods for a plan request in a given context (meal slot, day type, pantry, what's
    left of today's targets). Blocked or unordered plans return no foods."""
    _check_goal_types(body.request)
    full = plan(body.request)
    recs: list[FoodRecommendation] = []
    if full.status not in ("blocked", "needs_ordering"):
        kb = load_kb()
        req = body.request
        recs = foods.rank(
            body.context,
            full,
            req.preferences,
            req.constraints,
            kb,
            foods.load_foods(),
            limit=body.limit,
        )
    resp = FoodRecommendationsResponse(status=full.status, foods=recs)
    return resp.model_copy(update={"citations": explain.collect_citations(resp, load_kb())})


@app.post("/v1/recommendations/day", tags=["recommendations"], responses=errors.INVALID)
def recommend_day(
    body: Annotated[DayRecommendationRequest, Body(openapi_examples=examples.day_examples())],
) -> DayRecommendationResponse:
    """A sample day of meals for one phase and day type, built from the ranked foods to land
    within ±10% of that day's targets. Blocked or unordered plans return no day."""
    _check_goal_types(body.request)
    full = plan(body.request)
    day: SampleDay | None = None
    if full.status not in ("blocked", "needs_ordering"):
        req = body.request
        schedule = req.profile.training.weekly_schedule
        day = compose.compose(
            full,
            req.profile,
            req.preferences,
            req.constraints,
            load_kb(),
            foods.load_foods(),
            day_type=body.day_type or Counter(schedule).most_common(1)[0][0],
            phase=body.phase,
        )
    resp = DayRecommendationResponse(status=full.status, day=day)
    return resp.model_copy(update={"citations": explain.collect_citations(resp, load_kb())})


@app.post("/v1/goals/weight-range", tags=["goals"], responses=errors.INVALID)
def goal_weight_range(
    request: Annotated[PlanRequest, Body(openapi_examples=examples.weight_range_examples())],
) -> WeightRangeResponse:
    """The recommended target-weight range, an optional first milestone, and target bounds with a
    suggested default for each weight goal (spec §4.4b). Safety runs first: a blocked request
    returns no numbers, and number-hiding cases return status `hidden`."""
    _check_goal_types(request)
    return weight_range.weight_range(request, load_kb())


@app.post("/v1/safety/check", tags=["safety"], responses=errors.INVALID)
def safety_check(request: PlanBody) -> SafetyCheckResponse:
    """Guardrails only (Matrix F): blocks, warnings, referrals and the limits they set."""
    result = safety.check(request, load_kb())
    status: Literal["ok", "rd_review", "blocked"] = (
        "blocked" if result.blocked else "rd_review" if result.rd_gated else "ok"
    )
    return SafetyCheckResponse(status=status, **result.model_dump())


@app.get("/v1/knowledge/goals", tags=["knowledge"])
def knowledge_goals() -> GoalsFile:
    """Matrix A: goal types and their rules."""
    return load_kb().goals


@app.get("/v1/knowledge/patterns", tags=["knowledge"])
def knowledge_patterns() -> PatternsFile:
    """Matrix D: eating patterns."""
    return load_kb().patterns


@app.get("/v1/knowledge/guardrails", tags=["knowledge"])
def knowledge_guardrails() -> GuardrailsFile:
    """Matrix F: safety guardrails."""
    return load_kb().guardrails


@app.get("/v1/knowledge/foods", tags=["knowledge"])
def knowledge_foods() -> list[FoodListing]:
    """The food table's foods (key, name, group) for pickers; nutrient values stay in the
    engine."""
    return [
        FoodListing(key=f["key"], fdc_id=f["fdc_id"], name=f["description"], group=f["group"])
        for f in foods.load_foods()
    ]


@app.get("/v1/knowledge/score_weights", tags=["knowledge"])
def knowledge_score_weights() -> ScoreWeightsFile:
    """Matrix G: Loam Score weights."""
    return load_kb().score_weights
