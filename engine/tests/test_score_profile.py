"""Stage 4b: personal Loam Score profile (spec §7b, Matrix G)."""

import itertools
import json
from pathlib import Path

import pytest

from nuri_reco.goals import resolve
from nuri_reco.kb import load_kb
from nuri_reco.models import PlanRequest
from nuri_reco.models.response import LoamScoreProfile, PhaseScoreProfile, ScoreComponent
from nuri_reco.safety import check as safety_check
from nuri_reco.safety import claims_violations
from nuri_reco.score_profile import build, phase_weights, round_to_100
from nuri_reco.targets import Targets, compute

PERSONAS = Path(__file__).parent / "personas"
NOT_BLOCKED = [
    "maya",
    "novice_recomp",
    "marathon_fatloss",
    "wedding_8wk",
    "hybrid",
    "glp1_t2d_strength",
    "vegan_muscle",
]
COMPONENTS = ["energy", "protein", "carb", "fiber", "micro", "pattern", "moderation"]


def persona(name: str, **flags: object) -> PlanRequest:
    raw = json.loads((PERSONAS / f"{name}.json").read_text(encoding="utf-8"))
    raw.pop("expect")
    raw["profile"].setdefault("flags", {}).update(flags)
    return PlanRequest.model_validate(raw)


def profile_for(
    req: PlanRequest, *, with_safety: bool = True
) -> tuple[LoamScoreProfile, list[Targets]]:
    kb = load_kb()
    safety = safety_check(req, kb)
    phases = resolve(req, safety, kb).phases
    targets = [compute(p, req.profile, kb, safety=safety) for p in phases]
    lsp = build(
        phases,
        targets,
        req.profile,
        kb,
        goal_types=[g.type for g in req.goals],
        diet=req.constraints.diet,
        safety=safety if with_safety else None,
    )
    return lsp, targets


def weights(p: PhaseScoreProfile) -> list[int]:
    return [p.weights[c] for c in COMPONENTS]


def find(p: PhaseScoreProfile, id: str, day_type: str | None = None) -> ScoreComponent:
    return next(c for c in p.components if c.id == id and c.day_type == day_type)


# --- Weights ---


@pytest.mark.parametrize("name", NOT_BLOCKED)
def test_weights_sum_to_100_every_phase(name: str) -> None:
    lsp, _ = profile_for(persona(name))
    assert lsp.by_phase
    for p in lsp.by_phase:
        assert sum(p.weights.values()) == 100, p.phase
        assert sum(p.weights_exact.values()) == pytest.approx(100), p.phase
        assert list(p.weights) == COMPONENTS


def test_maya_weights() -> None:
    lsp, _ = profile_for(persona("maya"))
    [p] = lsp.by_phase
    assert (p.primary, weights(p)) == ("lose_fat", [20, 20, 5, 15, 15, 15, 10])
    assert p.weight_rule_ids == ["LSW.ROW.WEIGHTLOSS"]


def test_marathoner_phase_switch() -> None:
    lsp, _ = profile_for(persona("marathon_fatloss"))
    phases = {p.phase: p for p in lsp.by_phase}
    # Spec §7b.5: base = 0.6 weight loss + 0.4 athlete;
    # peak -> race week = 0.6 athlete + 0.4 weight loss.
    assert phases["base"].primary == "lose_fat"
    assert weights(phases["base"]) == [20, 20, 13, 13, 13, 13, 8]
    for name in ("peak", "taper", "race_week"):
        assert phases[name].primary == "endurance_event"
        assert weights(phases[name]) == [20, 20, 17, 12, 12, 12, 7]
    assert phases["base"].weights_exact["carb"] == pytest.approx(13.0)
    assert {"LSW.STACK.0604", "LSW.ROW.WEIGHTLOSS", "LSW.ROW.ATHLETE"} <= set(lsp.weight_rule_ids)


def test_glp1_t2d_floors() -> None:
    lsp, _ = profile_for(persona("glp1_t2d_strength"))
    [p] = lsp.by_phase
    w = p.weights_exact
    assert w["protein"] >= 25 and w["micro"] >= 20
    assert w["carb"] >= 20 and w["fiber"] >= 20
    assert sum(w.values()) == pytest.approx(100)
    assert {"LSW.FLOOR.T2D", "LSW.FLOOR.GLP1", "LSW.FLOOR.RULE"} <= set(p.weight_rule_ids)


ROW_TYPES = [g for row in load_kb().score_weights.rows for g in row.goal_types]


@pytest.mark.parametrize("primary", ROW_TYPES)
def test_floors_never_blended_down_and_total_100(primary: str) -> None:
    kb = load_kb()
    floors = {
        g: (f.model_extra or {})["minimums"] for f in kb.score_weights.floors for g in f.goal_types
    }
    for n in range(4):
        for others in itertools.combinations([t for t in ROW_TYPES if t != primary], n):
            goal_types = [primary, *others]
            w, rule_ids = phase_weights(primary, goal_types, kb)
            assert sum(w.values()) == pytest.approx(100), goal_types
            assert all(v >= 0 for v in w.values())
            mins: dict[str, float] = {}
            for g in goal_types:
                for component, minimum in floors.get(g, {}).items():
                    mins[component] = max(mins.get(component, 0), minimum)
            if sum(mins.values()) <= 100:
                # Floors hold; never blended down.
                assert all(w[c] >= m - 1e-9 for c, m in mins.items()), goal_types
                assert "LSW.FLOOR.CONFLICT" not in rule_ids
            else:
                # Only T2D + GLP-1 + hypertension (floors sum to 110): scaled to fit.
                assert {"t2d", "glp1", "hypertension"} <= set(goal_types)
                assert "LSW.FLOOR.CONFLICT" in rule_ids
                assert sum(w[c] for c in mins) == pytest.approx(100)
            assert sum(round_to_100(w).values()) == 100


def test_floor_conflict_scales_floors() -> None:
    w, rule_ids = phase_weights("lose_fat", ["lose_fat", "t2d", "glp1", "hypertension"], load_kb())
    assert w["protein"] == pytest.approx(25 * 100 / 110)
    assert w["carb"] == pytest.approx(20 * 100 / 110)
    assert w["energy"] == 0 and w["pattern"] == 0
    assert "LSW.FLOOR.CONFLICT" in rule_ids


def test_recomp_primary_not_double_counted() -> None:
    w, _ = phase_weights("recomp", ["lose_fat", "build_muscle"], load_kb())
    assert w["protein"] == pytest.approx(22.5)


# --- Maya's personal targets (spec §7b.5, at her safety-capped 1,845 kcal) ---


def test_maya_targets() -> None:
    lsp, [t] = profile_for(persona("maya"))
    [p] = lsp.by_phase
    day = t.by_day_type["rest"]
    e = day.kcal

    energy = find(p, "energy", "rest").target
    assert energy.low == pytest.approx(e * 0.95) and energy.high == pytest.approx(e * 1.05)
    protein = find(p, "protein").target
    assert protein.low == pytest.approx(112) and protein.high == pytest.approx(154)  # 1.6-2.2 x 70
    carb = find(p, "carb", "rest").target
    assert carb.low == pytest.approx(day.carb_g * 0.9)
    assert carb.high == pytest.approx(day.carb_g * 1.1)
    # Loam Score page formulas.
    assert find(p, "fiber", "rest").target.min == pytest.approx(max(25, 14 * e / 1000))
    assert find(p, "sat_fat", "rest").target.max == pytest.approx(e * 0.10 / 9)
    assert find(p, "free_sugar", "rest").target.max == pytest.approx(e * 0.10 / 4)
    # At 1,845 kcal: fiber 25.8 g, sat fat 20.5 g, free sugar 46.1 g
    # (7b.5 shows 25 / 20 / 45 at 1,800 kcal).
    assert find(p, "fiber", "rest").target.min == pytest.approx(25.8, abs=0.1)
    assert find(p, "sat_fat", "rest").target.max == pytest.approx(20.5, abs=0.1)
    assert find(p, "free_sugar", "rest").target.max == pytest.approx(46.1, abs=0.1)
    assert find(p, "sodium").target.max == 2300
    assert find(p, "produce").target.min == 400
    micros = {m.id: m.target for m in p.micronutrients}
    assert micros["iron"] == 18 and micros["magnesium"] == 310 and micros["potassium"] == 2600


def test_maya_levers() -> None:
    lsp, _ = profile_for(persona("maya"))
    # Spec §7b.5: fiber (15 x 0.9), protein (20 x 0.6), energy (20 x 0.5).
    assert [lever.component for lever in lsp.top_levers] == ["fiber", "protein", "energy"]
    assert lsp.top_levers[0].text == "Fiber is your biggest lever: aim for 26 g a day."
    assert "35 g at each of 4 meals" in lsp.top_levers[1].text


def test_applies_to() -> None:
    lsp, _ = profile_for(persona("maya"))
    [p] = lsp.by_phase
    assert find(p, "energy", "rest").applies_to == ["meal", "day"]
    assert find(p, "sodium").applies_to == ["meal", "day"]
    assert find(p, "produce").applies_to == ["day", "week"]


def test_endurance_carbs_use_matrix_c_tiers() -> None:
    lsp, _ = profile_for(persona("marathon_fatloss"))
    peak = next(p for p in lsp.by_phase if p.phase == "peak")
    long = find(peak, "carb", "long").target
    assert long.low == pytest.approx(6 * 72) and long.high == pytest.approx(10 * 72)
    assert "DAYTYPE.LONG" in find(peak, "carb", "long").rule_ids


# --- Disabled components and flags ---


@pytest.mark.parametrize("with_safety", [True, False])
def test_ckd_disables_potassium(with_safety: bool) -> None:
    lsp, _ = profile_for(persona("maya", ckd_stage=3), with_safety=with_safety)
    for p in lsp.by_phase:
        assert [(d.id, d.reason) for d in p.disabled] == [("potassium_credit", "rd_gated")]
        assert "potassium" not in {m.id for m in p.micronutrients}
        assert find(p, "protein").target.high == pytest.approx(0.6 * 70)  # CKD cap


def test_no_ckd_no_disabled() -> None:
    lsp, _ = profile_for(persona("maya"))
    assert lsp.by_phase[0].disabled == []


def test_vegan_b12_must_supplement() -> None:
    lsp, _ = profile_for(persona("vegan_muscle"))
    flags = {m.id: m.flag for m in lsp.by_phase[0].micronutrients}
    assert flags["vitamin_b12"] == "must_supplement"
    assert flags["iron"] is None


def test_t2d_carbs_rd_set() -> None:
    lsp, _ = profile_for(persona("glp1_t2d_strength"))
    assert ("carb_auto_target", "rd_set") in [(d.id, d.reason) for d in lsp.by_phase[0].disabled]


def test_hypertension_sodium_and_moderation_floor() -> None:
    req = persona("maya")
    req = req.model_copy(
        update={
            "goals": [
                *req.goals,
                req.goals[0].model_copy(update={"type": "hypertension", "priority": 2}),
            ]
        }
    )
    lsp, _ = profile_for(req)
    p = lsp.by_phase[0]
    assert find(p, "sodium").target.max == 1500
    assert p.weights_exact["moderation"] >= 25


# --- Copy and provenance ---


@pytest.mark.parametrize("name", NOT_BLOCKED)
def test_levers_read_naturally_and_make_no_claims(name: str) -> None:
    kb = load_kb()
    lsp, _ = profile_for(persona(name))
    assert len(lsp.top_levers) == 3
    for lever in lsp.top_levers:
        assert "{" not in lever.text and lever.text.endswith(".")
        assert claims_violations(lever.text, kb) == []
    templates = (kb.score_weights.levers.model_extra or {})["templates"]
    for pair in templates.values():
        for text in pair.values():
            assert claims_violations(text, kb) == []


@pytest.mark.parametrize("name", NOT_BLOCKED)
def test_components_carry_rule_ids_and_provenance(name: str) -> None:
    rules = set(load_kb().rules)
    lsp, _ = profile_for(persona(name))
    assert lsp.provenance == "recommended"
    assert set(lsp.weight_rule_ids) <= rules
    for p in lsp.by_phase:
        for c in p.components:
            assert c.provenance == "recommended" and c.why
            assert set(c.rule_ids) <= rules, set(c.rule_ids) - rules


def test_round_to_100() -> None:
    assert round_to_100({"a": 33.4, "b": 33.3, "c": 33.3}) == {"a": 34, "b": 33, "c": 33}
    assert sum(round_to_100({"a": 7.29, "b": 4.71, "c": 88.0}).values()) == 100
