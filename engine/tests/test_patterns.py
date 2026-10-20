"""Stage 5 diet-pattern ranking (spec §6 Matrix D)."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from nuri_reco.engine import plan
from nuri_reco.kb import load_kb
from nuri_reco.models import PlanRequest
from nuri_reco.models.response import PatternRecommendation

PERSONAS = Path(__file__).parent / "personas"
PLANT = {"vegetarian_vegan"}
BASE: dict[str, Any] = {
    "profile": {
        "age": 45,
        "sex": "male",
        "height_cm": 178,
        "weight_kg": 88,
        "activity": "light",
        "training": {"resistance": False, "weekly_schedule": ["rest"] * 7},
    },
    "goals": [{"type": "maintain", "priority": 1}],
    "as_of": "2026-10-16",
}


def request(
    goals: list[str], *, diet: str | None = None, medications: list[str] | None = None, **prefs: Any
) -> PlanRequest:
    raw = copy.deepcopy(BASE)
    raw["goals"] = [{"type": g, "priority": i + 1} for i, g in enumerate(goals)]
    raw["constraints"] = {"diet": diet}
    raw["preferences"] = prefs
    if medications:
        raw["profile"]["flags"] = {"medications": medications}
    return PlanRequest.model_validate(raw)


def ids(req: PlanRequest) -> list[str]:
    return [p.id for p in plan(req).patterns]


def persona(name: str) -> PlanRequest:
    raw = json.loads((PERSONAS / f"{name}.json").read_text(encoding="utf-8"))
    raw.pop("expect")
    return PlanRequest.model_validate(raw)


# --- The four runbook cases ---


@pytest.mark.parametrize(
    "prefs",
    [{}, {"cuisines": ["mediterranean", "italian"]}, {"pattern_pref": "mediterranean"}],
)
def test_hypertension_ranks_dash_first(prefs: dict[str, Any]) -> None:
    recs = plan(request(["hypertension"], **prefs)).patterns
    assert recs[0].id == "dash"
    assert "PATTERN.SELECT.FIRST_LINE" in recs[0].rule_ids
    assert recs[0].why.startswith("The best-tested eating style for blood pressure.")


def test_lose_fat_plus_hypertension_ranks_dash_first() -> None:
    # Spec §4.2: "DASH pattern ranked first".
    assert ids(request(["lose_fat", "hypertension"]))[0] == "dash"


@pytest.mark.parametrize("med", ["sglt2_inhibitor", "insulin", "sulfonylurea"])
@pytest.mark.parametrize("prefs", [{}, {"pattern_pref": "low_carb_keto"}])
def test_no_keto_on_glucose_lowering_meds(med: str, prefs: dict[str, Any]) -> None:
    assert "low_carb_keto" not in ids(request(["t2d"], medications=[med], **prefs))


def test_keto_can_appear_without_those_meds() -> None:
    # Control: the exclusion above is what removes it.
    assert "low_carb_keto" in ids(request(["t2d"], pattern_pref="low_carb_keto"))


@pytest.mark.parametrize("diet", ["vegan", "vegetarian"])
@pytest.mark.parametrize("goal", ["lose_fat", "build_muscle", "hypertension", "t2d", "maintain"])
def test_vegan_and_vegetarian_only_get_plant_patterns(diet: str, goal: str) -> None:
    got = ids(request([goal], diet=diet, pattern_pref="mediterranean"))
    assert got and set(got) <= PLANT, got


def test_vegan_persona() -> None:
    recs = plan(persona("vegan_muscle")).patterns
    assert [p.id for p in recs] == ["vegetarian_vegan"]
    assert "PATTERN.SELECT.DIET_FIT" in recs[0].rule_ids


def test_pattern_pref_changes_ranking() -> None:
    default = ids(persona("maya"))
    for pref in ("high_protein", "if_tre"):
        req = persona("maya")
        req = req.model_copy(
            update={"preferences": req.preferences.model_copy(update={"pattern_pref": pref})}
        )
        ranked = ids(req)
        assert ranked[0] == pref and ranked != default
    assert "if_tre" not in default  # IF/TRE only when asked for


# --- Other rules ---


def test_mind_never_offered() -> None:
    for goals in (["maintain"], ["hypertension"], ["t2d"]):
        assert "mind" not in ids(request(goals, pattern_pref="mind"))


def test_maya_gets_three_explained_patterns() -> None:
    recs = plan(persona("maya")).patterns
    assert len(recs) == 3 and len({p.id for p in recs}) == 3
    rules = set(load_kb().rules)
    for p in recs:
        assert p.why and p.provenance == "recommended" and 0 <= p.score <= 1
        assert set(p.rule_ids) <= rules
    assert [p.score for p in recs] == sorted((p.score for p in recs), reverse=True)


def test_cuisine_and_diet_lift_adherence() -> None:
    marathon = plan(
        persona("marathon_fatloss")
    ).patterns  # pescatarian, likes mediterranean/japanese
    assert marathon[0].id == "flexitarian_pescatarian"
    assert "It matches the way you already eat." in marathon[0].why


def test_dislikes_and_budget_lower_a_pattern() -> None:
    base = {p.id: p.score for p in plan(request(["lose_fat"])).patterns}
    picky = {
        p.id: p.score
        for p in plan(request(["lose_fat"], budget="low", dislikes=["chicken", "eggs"])).patterns
    }
    assert picky.get("high_protein", 0) < base["high_protein"]


def test_dry_run_and_blocked_skip_patterns() -> None:
    assert plan(persona("maya"), dry_run=True).patterns == []
    assert plan(persona("under18")).patterns == []


def test_adherence_is_the_largest_weight() -> None:
    weights = load_kb().rules["PATTERN.SCORE.WEIGHTS"].model_extra or {}
    assert weights["adherence"] > weights["evidence"]
    assert weights["adherence"] == max(v for v in weights.values() if isinstance(v, float))


def test_recommendations_are_typed() -> None:
    for p in plan(persona("glp1_t2d_strength")).patterns:
        assert isinstance(p, PatternRecommendation)
