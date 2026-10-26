import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from nuri_reco.models import PlanRequest, PlanResponse

FIXTURES = Path(__file__).parent / "fixtures"


def spec_request() -> dict[str, Any]:
    """Section 10 request example, verbatim."""
    raw: dict[str, Any] = json.loads(
        (FIXTURES / "spec_plan_request.json").read_text(encoding="utf-8")
    )
    return raw


def spec_response() -> dict[str, Any]:
    """Section 10 response example, with goal_summary / loam_score_profile from 7b.6."""
    return {
        "status": "ok",
        "safety": {"blocks": [], "warnings": [], "referrals": []},
        "phases": [
            {
                "name": "base",
                "start": "2026-10-16",
                "end": "2026-12-27",
                "energy": "deficit",
                "energy_owner": "lose_fat",
                "max_rate_pct_bw": 0.5,
                "targets_by_day_type": {
                    "rest": {"kcal": 1750, "protein_g": 130, "carb_g": 230, "fat_g": 55},
                    "long": {"kcal": 2300, "protein_g": 130, "carb_g": 430, "fat_g": 55},
                },
                "meal_pattern": {
                    "meals": 3,
                    "snacks": 1,
                    "source": "default",
                    "per_meal_protein_g": 32.5,
                    "rule_ids": ["TIMING.MEAL_PATTERN", "TIMING.PROTEIN_PER_MEAL"],
                    "why": "Your protein is spread across 3 meals and 1 snack: about 33 g each.",
                },
                "rule_ids": ["COMBO.LOSEFAT_ENDURANCE", "PHASE.BASE"],
                "why": "Your base block is the window for fat loss before training load peaks.",
            }
        ],
        "feasibility": {"status": "feasible", "projected_kg_at_event": 66.4},
        "patterns": [
            {
                "id": "mediterranean",
                "name": "Mediterranean",
                "score": 0.86,
                "rule_ids": ["PATTERN.MEDITERRANEAN"],
                "why": "Fits pescatarian eating and your cuisine picks.",
            }
        ],
        "foods": [
            {
                "key": "salmon_cooked",
                "fdc_id": 175168,
                "name": "Salmon, Atlantic",
                "score": 0.91,
                "why": "High protein for the calories, plus omega-3.",
                "reasons": ["19 g protein/100 kcal", "omega-3"],
                "rule_ids": ["FOOD.W.LOSEFAT"],
                "provenance": "recommended",
            }
        ],
        "goal_summary": {
            "headline": "Lose fat at a steady pace while fueling your marathon build.",
            "goals": [
                {
                    "type": "lose_fat",
                    "role": "primary",
                    "resolved_as": "deficit in base phase only, ≤ 0.5% BW/week",
                    "rule_ids": ["COMBO.LOSEFAT_ENDURANCE"],
                    "why": "Fat loss fits best before your training load peaks.",
                },
                {
                    "type": "endurance_event",
                    "role": "secondary",
                    "resolved_as": "primary from peak (2027-03-07) to race week",
                    "rule_ids": ["PHASE.PEAK"],
                    "why": "Full fueling takes over once race-specific training starts.",
                },
            ],
            "pace": {
                "rate_pct_bw_week": 0.5,
                "projected_kg_at_event": 66.4,
                "reachable_date": None,
            },
            "provenance": "recommended",
        },
        "loam_score_profile": {
            "by_phase": [
                {
                    "phase": "base",
                    "weights": {
                        "energy": 20,
                        "protein": 20,
                        "carb": 13,
                        "fiber": 13,
                        "micro": 13,
                        "pattern": 13,
                        "moderation": 8,
                    },
                    "components": [
                        {
                            "id": "protein",
                            "type": "range",
                            "target": {"low": 115, "high": 158, "unit": "g"},
                            "applies_to": ["meal", "day"],
                            "rule_ids": ["GOAL.LOSEFAT.PROTEIN_RT"],
                            "why": "High protein protects muscle while you lose fat.",
                        },
                        {
                            "id": "fiber",
                            "type": "adequacy",
                            "target": {"min": 25, "unit": "g"},
                            "applies_to": ["meal", "day"],
                            "rule_ids": ["LS.FIBER"],
                            "why": "Fiber keeps you full and supports gut health.",
                        },
                    ],
                    "micronutrients": [{"id": "iron", "target": 18, "unit": "mg", "window": "7d"}],
                    "disabled": [{"id": "potassium_credit", "reason": "rd_gated"}],
                }
            ],
            "top_levers": [
                {"component": "fiber", "text": "Fiber is your biggest lever: aim for 25 g a day."}
            ],
            "weight_rule_ids": ["LSW.STACK.0604", "LSW.ROW.WEIGHTLOSS", "LSW.ROW.ATHLETE"],
            "provenance": "recommended",
        },
        "citations": ["ISSN2017", "IMPEY2018"],
    }


def test_parses_spec_example_request() -> None:
    raw = spec_request()
    req = PlanRequest.model_validate(raw)

    assert req.profile.body_fat_pct is None
    assert req.profile.training.weekly_schedule[5] == "long"
    assert [g.type for g in req.goals] == ["lose_fat", "endurance_event"]
    assert req.goals[1].event_date == dt.date(2027, 4, 18)
    assert req.as_of == dt.date(2026, 10, 16)
    # Nothing in the spec example is dropped or reinterpreted.
    assert req.model_dump(mode="json", exclude_unset=True) == raw


def test_validates_hand_built_response() -> None:
    resp = PlanResponse.model_validate(spec_response())

    assert resp.phases[0].targets_by_day_type["rest"].kcal == 1750
    assert resp.foods[0].reasons == ["19 g protein/100 kcal", "omega-3"]
    assert resp.loam_score_profile.by_phase[0].components[1].target.min == 25
    dumped = resp.model_dump(mode="json")
    assert PlanResponse.model_validate(dumped) == resp
    # Provenance is filled on every item even when the input omitted it.
    for item in [*dumped["phases"], *dumped["patterns"], *dumped["foods"]]:
        assert item["provenance"] == "recommended"


@pytest.mark.parametrize("section", ["phases", "patterns", "foods"])
@pytest.mark.parametrize("field", ["rule_ids", "why"])
def test_recommendation_items_require_rule_ids_and_why(section: str, field: str) -> None:
    raw = spec_response()
    del raw[section][0][field]
    with pytest.raises(ValidationError):
        PlanResponse.model_validate(raw)


def test_rejects_empty_rule_ids() -> None:
    raw = spec_response()
    raw["foods"][0]["rule_ids"] = []
    with pytest.raises(ValidationError):
        PlanResponse.model_validate(raw)


def test_rejects_other_provenance() -> None:
    raw = spec_response()
    raw["foods"][0]["provenance"] = "measured"
    with pytest.raises(ValidationError):
        PlanResponse.model_validate(raw)


def test_score_weights_must_sum_to_100() -> None:
    raw = spec_response()
    raw["loam_score_profile"]["by_phase"][0]["weights"]["moderation"] = 9
    with pytest.raises(ValidationError, match="sum to 101"):
        PlanResponse.model_validate(raw)


def test_blocked_plan_has_no_phases() -> None:
    raw = spec_response()
    raw["status"] = "blocked"
    with pytest.raises(ValidationError, match="blocked"):
        PlanResponse.model_validate(raw)
    raw["phases"] = []
    assert PlanResponse.model_validate(raw).status == "blocked"


def test_rejects_unknown_fields() -> None:
    raw = spec_request()
    raw["profile"]["bodyfat"] = 20
    with pytest.raises(ValidationError):
        PlanRequest.model_validate(raw)
