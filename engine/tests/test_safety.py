"""Stage 1 safety: one test per guardrails.yaml rule, plus the blocked personas."""

import copy
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from nuri_reco.kb import GuardrailsFile, KnowledgeBase, Rule, load_kb
from nuri_reco.models import PlanRequest
from nuri_reco.safety import SafetyResult, check, claims_violations

PERSONAS = Path(__file__).parent / "personas"

BASE: dict[str, Any] = {
    "profile": {
        "age": 30,
        "sex": "female",
        "height_cm": 168,
        "weight_kg": 70,
        "activity": "moderate",
        "training": {"resistance": False, "weekly_schedule": ["rest"] * 7},
    },
    "goals": [{"type": "maintain", "priority": 1}],
    "as_of": "2026-10-16",
}


def request(
    goals: list[str] | None = None, *, target_weight_kg: float | None = None, **profile: Any
) -> PlanRequest:
    """BASE with the given goal types and profile/flags overrides (flags via `flags={...}`)."""
    raw = copy.deepcopy(BASE)
    if goals is not None:
        raw["goals"] = [{"type": g, "priority": i + 1} for i, g in enumerate(goals)]
    if target_weight_kg is not None:
        raw["goals"][0]["target_weight_kg"] = target_weight_kg
    raw["profile"].update(profile)
    return PlanRequest.model_validate(raw)


def run(req: PlanRequest) -> SafetyResult:
    return check(req, load_kb())


def rule(rule_id: str) -> dict[str, Any]:
    return load_kb().rules[rule_id].model_extra or {}


def finding_ids(result: SafetyResult) -> dict[str, list[str]]:
    return {
        "blocks": [f.rule_id for f in result.blocks],
        "warnings": [f.rule_id for f in result.warnings],
        "referrals": [f.rule_id for f in result.referrals],
    }


# --- One case per guardrail id ---

CASES: dict[str, Callable[[], None]] = {}


def case(rule_id: str) -> Callable[[Callable[[], None]], Callable[[], None]]:
    def register(fn: Callable[[], None]) -> Callable[[], None]:
        CASES[rule_id] = fn
        return fn

    return register


@case("GUARD.CALORIE_FLOOR")
def calorie_floor() -> None:
    female = run(request()).calorie_floor
    male = run(request(sex="male")).calorie_floor
    assert (female.sex_floor_kcal, male.sex_floor_kcal) == (1200, 1500)
    assert (
        female.ea_floor_kcal_per_kg_ffm == rule("GUARD.CALORIE_FLOOR")["ea_floor_kcal_per_kg_ffm"]
    )
    assert female.absolute_min_kcal_per_day == 800
    assert female.rule_id == "GUARD.CALORIE_FLOOR"


@case("GUARD.MAX_LOSS_RATE")
def max_loss_rate() -> None:
    # 168 cm: 88 kg -> BMI 31.2, 76 kg -> 26.9, 62 kg -> 22.0
    rates = {w: run(request(["lose_fat"], weight_kg=w)).max_loss_rate for w in (88.0, 76.0, 62.0)}
    assert {w: r.max_loss_pct_bw_per_week for w, r in rates.items() if r} == {
        88.0: 1.0,
        76.0: 0.75,
        62.0: 0.5,
    }
    assert run(request(["maintain"])).max_loss_rate is None


@case("GUARD.UNDER_18")
def under_18() -> None:
    result = run(request(["lose_fat"], age=16))
    assert result.blocked
    assert result.blocks[0].rule_ids == ["GUARD.UNDER_18", "COMBO.DEFICIT_BLOCKED"]
    assert result.referrals[0].to == ["family", "clinician"]
    # No deficit asked for: still referred, not blocked.
    maintaining = run(request(["maintain"], age=16))
    assert not maintaining.blocked
    assert finding_ids(maintaining)["referrals"] == ["GUARD.UNDER_18"]
    assert finding_ids(run(request(["lose_fat"], age=18))) == {
        "blocks": [],
        "warnings": [],
        "referrals": [],
    }


@case("GUARD.PREGNANCY")
def pregnancy() -> None:
    for flag in ("pregnant", "breastfeeding"):
        result = run(request(["lose_fat"], flags={flag: True}))
        assert finding_ids(result)["blocks"] == ["GUARD.PREGNANCY"]
        assert result.referrals[0].to == ["rd"]
    # A weight-loss target is blocked even without a deficit goal type.
    assert run(request(["maintain"], target_weight_kg=65, flags={"pregnant": True})).blocked
    maintaining = run(request(["maintain"], flags={"pregnant": True}))
    assert not maintaining.blocked
    assert finding_ids(maintaining)["referrals"] == ["GUARD.PREGNANCY"]


@case("GUARD.ED_RISK")
def ed_risk() -> None:
    scoff = run(request(["lose_fat"], flags={"scoff_score": 2}))
    assert finding_ids(scoff)["blocks"] == ["GUARD.ED_RISK"]
    assert scoff.restricted("offer") == ["number_hiding_mode"]
    assert scoff.referrals[0].to == ["resources"]
    assert not run(request(["lose_fat"], flags={"scoff_score": 1})).blocked
    # 168 cm, goal 50 kg -> BMI 17.7
    assert run(request(["lose_fat"], target_weight_kg=50)).blocked
    assert not run(request(["lose_fat"], target_weight_kg=60)).blocked
    # Aesthetic (deadline) modes are blocked too.
    assert run(request(["deadline_event"], flags={"ed_history": True})).blocked
    history_only = run(request(["maintain"], flags={"ed_history": True}))
    assert not history_only.blocked
    assert finding_ids(history_only)["referrals"] == ["GUARD.ED_RISK"]


@case("GUARD.LOW_EA")
def low_ea() -> None:
    result = run(request(["lose_fat"], flags={"reported_symptoms": ["missed_periods"]}))
    assert not result.blocked
    assert result.restricted("remove") == ["deficit"]
    assert finding_ids(result)["warnings"] == ["GUARD.LOW_EA"]
    assert result.referrals[0].to == ["doctor", "sports_rd"]
    maintaining = run(request(["maintain"], flags={"reported_symptoms": ["stress_fractures"]}))
    assert maintaining.restricted("remove") == []
    assert finding_ids(maintaining) == {
        "blocks": [],
        "warnings": [],
        "referrals": ["GUARD.LOW_EA"],
    }
    assert run(request(["lose_fat"], flags={"reported_symptoms": ["headache"]})).warnings == []


@case("GUARD.CKD")
def ckd() -> None:
    stage3 = run(request(["maintain"], flags={"ckd_stage": 3}))
    assert stage3.protein_cap is not None
    assert (stage3.protein_cap.min_g_per_kg, stage3.protein_cap.max_g_per_kg) == (0.55, 0.6)
    assert "GUARD.CKD" in stage3.rd_gated_rule_ids
    assert "GUARD.CKD" in finding_ids(stage3)["warnings"]
    with_diabetes = run(request(["t2d"], flags={"ckd_stage": 4})).protein_cap
    assert with_diabetes is not None
    assert (with_diabetes.min_g_per_kg, with_diabetes.max_g_per_kg) == (0.6, 0.8)
    stage2 = run(request(["maintain"], flags={"ckd_stage": 2}))
    assert stage2.protein_cap is None
    assert "GUARD.CKD" in stage2.rd_gated_rule_ids
    assert run(request()).protein_cap is None


@case("GUARD.SGLT2")
def sglt2() -> None:
    result = run(request(["t2d"], flags={"medications": ["SGLT2_inhibitor"]}))
    assert result.excluded_pattern_ids == ["PATTERN.LOW_CARB_KETO"]
    assert "GUARD.SGLT2" in finding_ids(result)["warnings"]
    assert run(request(["t2d"])).excluded_pattern_ids == []


@case("GUARD.INSULIN_SU")
def insulin_su() -> None:
    for med in ("insulin", "sulfonylurea"):
        result = run(request(["maintain"], flags={"medications": [med]}))
        assert finding_ids(result)["referrals"] == ["GUARD.INSULIN_SU"]
        assert result.referrals[0].to == ["rd"]
        assert "GUARD.INSULIN_SU" in finding_ids(result)["warnings"]
        assert result.restricted("rd_approval_required") == ["carb_restriction", "large_deficit"]
    assert run(request(["maintain"], flags={"medications": ["metformin"]})).referrals == []


@case("GUARD.WARFARIN")
def warfarin() -> None:
    result = run(request(["maintain"], flags={"medications": ["warfarin"]}))
    assert result.restricted("keep_consistent") == ["vitamin_k"]
    assert finding_ids(result)["warnings"] == ["GUARD.WARFARIN"]


@case("GUARD.CONDITION_GOALS")
def condition_goals() -> None:
    gated = [
        request(["t2d"]),
        request(["glp1"]),
        request(["maintain"], flags={"medications": ["glp1_agonist"]}),
        request(["maintain"], flags={"conditions": ["t2d"]}),
        request(["maintain"], flags={"ckd_stage": 1}),
        request(["hypertension"], flags={"medications": ["antihypertensive"]}),
    ]
    for req in gated:
        assert "GUARD.CONDITION_GOALS" in run(req).rd_gated_rule_ids, req.goals
    # Hypertension without medication is not a condition goal.
    assert run(request(["hypertension"])).rd_gated_rule_ids == []
    assert run(request(["lose_fat"])).rd_gated_rule_ids == []


@case("GUARD.CLAIMS")
def claims() -> None:
    kb = load_kb()
    assert claims_violations("This food cures fatigue", kb) == ["cures"]
    assert claims_violations("Is it safe to eat?", kb) == ["safe to eat"]
    assert claims_violations("A treatment-free, tasty plan", kb) == []
    # Copy rules never fire on a request.
    assert "GUARD.CLAIMS" not in str(finding_ids(run(request(["lose_fat"], age=16))))


@case("GUARD.PEAK_WEEK")
def peak_week() -> None:
    result = run(request(["lose_fat", "deadline_event"]))
    assert result.restricted("never_advise") == [
        "water_restriction",
        "diuretics",
        "extreme_sodium_manipulation",
    ]
    assert run(request(["lose_fat"])).restricted("never_advise") == []


GUARDRAIL_IDS = [r.id for r in load_kb().guardrails.guardrails]


@pytest.mark.parametrize("rule_id", GUARDRAIL_IDS)
def test_guardrail(rule_id: str) -> None:
    assert rule_id in CASES, f"no test for {rule_id}: add a @case({rule_id!r}) function"
    CASES[rule_id]()


def test_every_case_is_a_real_rule() -> None:
    assert set(CASES) == set(GUARDRAIL_IDS)


# --- Blocked personas ---


def load_persona(name: str) -> PlanRequest:
    raw = json.loads((PERSONAS / f"{name}.json").read_text(encoding="utf-8"))
    raw.pop("expect")
    return PlanRequest.model_validate(raw)


@pytest.mark.parametrize(
    ("persona", "guardrail"),
    [
        ("under18", "GUARD.UNDER_18"),
        ("pregnant", "GUARD.PREGNANCY"),
        ("goal_bmi_low", "GUARD.ED_RISK"),
    ],
)
def test_blocked_personas(persona: str, guardrail: str) -> None:
    result = run(load_persona(persona))
    assert result.blocked
    assert [b.rule_id for b in result.blocks] == [guardrail]
    assert "COMBO.DEFICIT_BLOCKED" in result.blocks[0].rule_ids
    assert result.referrals, "blocked personas are always referred"
    for finding in [*result.blocks, *result.referrals]:
        assert finding.provenance == "recommended"
        assert not re.search(r"\d", finding.message + finding.why), "no numbers in reasons"


def test_non_blocked_personas_are_not_blocked() -> None:
    for name in [
        "maya",
        "novice_recomp",
        "marathon_fatloss",
        "wedding_8wk",
        "hybrid",
        "vegan_muscle",
    ]:
        assert not run(load_persona(name)).blocked, name
    glp1 = run(load_persona("glp1_t2d_strength"))
    assert not glp1.blocked and glp1.rd_gated


# --- Copy, purity, completeness ---


def test_guardrail_copy_is_plain_and_claim_free() -> None:
    kb = load_kb()
    for r in kb.guardrails.guardrails:
        for text in ((r.model_extra or {}).get("copy") or {}).values():
            assert not re.search(r"\d", text), f"{r.id}: number in copy"
            assert claims_violations(text, kb) == [], f"{r.id}: claim in copy"


def test_check_is_pure() -> None:
    req = request(["lose_fat"], age=16, flags={"medications": ["warfarin"]})
    before = req.model_dump()
    assert run(req) == run(req)
    assert req.model_dump() == before


def test_unknown_guardrail_fails_loudly() -> None:
    kb = load_kb()
    extra = Rule(id="GUARD.NEW_RULE", citation_ids=[], verify=False, heuristic=False)
    guardrails = GuardrailsFile(spec_section="8", guardrails=[*kb.guardrails.guardrails, extra])
    broken = KnowledgeBase.model_validate({**dict(kb), "guardrails": guardrails})
    with pytest.raises(ValueError, match="GUARD.NEW_RULE has no trigger"):
        check(request(), broken)
