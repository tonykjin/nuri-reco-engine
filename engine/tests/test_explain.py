"""Explanations (spec §10): templated copy keyed by rule id, the claims filter (PRD §4 and §11),
and citation collection. The scans run over every golden persona, plus food chips in every slot.
"""

import json
from functools import cache
from pathlib import Path
from typing import get_args

import pytest

from nuri_reco import explain
from nuri_reco.engine import plan
from nuri_reco.explain import ClaimsViolation, ExplanationMissing
from nuri_reco.foods import load_foods, rank
from nuri_reco.kb import ExplanationsFile, KnowledgeBase, load_kb
from nuri_reco.models import FoodContext, MealSlot, PantryItem, PlanRequest, PlanResponse

PERSONAS = Path(__file__).parent / "personas"
NAMES = sorted(p.stem for p in PERSONAS.glob("*.json"))


def request(name: str) -> PlanRequest:
    raw = json.loads((PERSONAS / f"{name}.json").read_text(encoding="utf-8"))
    raw.pop("expect")
    return PlanRequest.model_validate(raw)


@cache
def response(name: str) -> PlanResponse:
    return plan(request(name))


def test_there_are_ten_personas() -> None:
    assert len(NAMES) == 10


# --- Banned phrases: every generated string, every persona ---


@pytest.mark.parametrize("name", NAMES)
def test_no_banned_phrases_in_plan(name: str) -> None:
    resp = response(name)
    assert explain.strings_in(resp), "the scan found no strings to check"
    assert explain.banned_phrases_in(resp, load_kb()) == []


@pytest.mark.parametrize("name", NAMES)
def test_no_banned_phrases_in_food_chips(name: str) -> None:
    req, resp, kb = request(name), response(name), load_kb()
    if resp.status != "ok":
        return
    banana = "bananas_ripe_and_slightly_ripe_raw"
    pantry = [PantryItem(key=banana, ripeness="peak", peaks_tonight=True)]
    for slot in get_args(MealSlot):
        context = FoodContext(meal_slot=slot, pantry=pantry)
        recs = rank(context, resp, req.preferences, req.constraints, kb, load_foods(), limit=40)
        hits = [h for r in recs for h in explain.banned_phrases_in(r, kb)]
        assert hits == [], f"{slot}: {hits}"


@pytest.mark.parametrize("name", NAMES)
def test_generated_text_is_filled_in(name: str) -> None:
    for path, text in explain.strings_in(response(name)):
        assert "{" not in text and "}" not in text, f"{path}: unfilled placeholder in {text!r}"
        if path.endswith("why"):
            assert text.strip(), f"{path}: empty why"


def test_every_template_is_claim_free() -> None:
    kb = load_kb()
    hits = [
        f"{rule_id}.{variant}: {found}"
        for rule_id, variants in kb.explanations.templates.items()
        for variant, text in variants.items()
        if (found := explain.claims_violations(text, kb))
    ]
    assert hits == []


# --- Every rule id in output has a template ---


@pytest.mark.parametrize("name", NAMES)
def test_every_output_rule_id_has_a_template(name: str) -> None:
    kb = load_kb()
    missing = [r for r in explain.rule_ids_in(response(name)) if not explain.has(kb, r, "rule")]
    assert missing == []


# --- text(): fails loudly ---


def kb_with(templates: dict[str, dict[str, str]]) -> KnowledgeBase:
    kb = load_kb()
    merged = {**kb.explanations.templates, **templates}
    return kb.model_copy(
        update={"explanations": ExplanationsFile(spec_section="10", templates=merged)}
    )


def test_text_formats_placeholders() -> None:
    kb = load_kb()
    assert explain.text(kb, "FOOD.RANK.CHIPS", "protein", value=12.4) == (
        "12 g protein per 100 kcal"
    )


def test_missing_template_raises() -> None:
    with pytest.raises(ExplanationMissing, match=r"no 'nope' explanation for GUARD\.CLAIMS"):
        explain.text(load_kb(), "GUARD.CLAIMS", "nope")
    with pytest.raises(ExplanationMissing):
        explain.text(load_kb(), "NOT.A.RULE")


def test_banned_phrase_in_a_template_raises() -> None:
    kb = kb_with({"GUARD.CLAIMS": {"rule": "This plan cures everything."}})
    with pytest.raises(ClaimsViolation, match=r"GUARD\.CLAIMS\.rule uses banned phrases"):
        explain.text(kb, "GUARD.CLAIMS")


def test_banned_phrase_in_a_value_raises() -> None:
    kb = kb_with({"GUARD.CLAIMS": {"rule": "Try {food}."}})
    assert explain.text(kb, "GUARD.CLAIMS", food="oats") == "Try oats."
    with pytest.raises(ClaimsViolation):
        explain.text(kb, "GUARD.CLAIMS", food="a detox tea")


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("This food cures fatigue", ["cures"]),
        ("Is it SAFE TO EAT?", ["safe to eat"]),
        ("Plan a cheat meal", ["cheat", "cheat meal"]),
        ("Feel guilty about dessert", ["guilty"]),
        ("We won't spoil the ending", ["won't spoil"]),
        ("Cured ham is salty", []),
        ("A well-treated sore muscle", []),
    ],
)
def test_claims_filter(text: str, found: list[str]) -> None:
    assert explain.claims_violations(text, load_kb()) == found


# --- Citations ---


@pytest.mark.parametrize("name", NAMES)
def test_citations_are_collected_from_cited_rules(name: str) -> None:
    resp, kb = response(name), load_kb()
    assert resp.citations == explain.collect_citations(resp, kb)
    expected = {
        cid
        for rid in explain.rule_ids_in(resp)
        if rid in kb.rules
        for cid in kb.rules[rid].citation_ids
    }
    assert set(resp.citations) == expected
    assert len(resp.citations) == len(set(resp.citations))
    assert set(resp.citations) <= set(kb.citation_index)


def test_maya_cites_sources() -> None:
    assert response("maya").citations
