"""Schema checks for the knowledge YAML (Matrices A-F, spec §3-§8)."""

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any, get_args

import pytest
import yaml

import nuri_reco
from nuri_reco.models import DayType

KNOWLEDGE = Path(nuri_reco.__file__).parent / "knowledge"
RULE_FILES = [
    "goals.yaml",
    "combos.yaml",
    "phases.yaml",
    "daytypes.yaml",
    "patterns.yaml",
    "food_weights.yaml",
    "guardrails.yaml",
    "targets.yaml",
    "micronutrients.yaml",
    "score_weights.yaml",
    "summary.yaml",
    "constraints.yaml",
    "compose.yaml",
    "expenditure.yaml",
]
ID_RE = re.compile(r"^[A-Z0-9_]+(\.[A-Z0-9_]+)+$")
NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
# Keys whose numbers are list positions, not values from the page.
POSITION_KEYS = {"step", "order"}
REF_KEYS = {"protein_from", "same_as", "pattern_first"}


def load(name: str) -> Any:
    return yaml.safe_load((KNOWLEDGE / name).read_text(encoding="utf-8"))


def walk_rules(node: Any) -> Iterator[dict[str, Any]]:
    """Every mapping with an `id` is a rule."""
    if isinstance(node, dict):
        if "id" in node:
            yield node
        for value in node.values():
            yield from walk_rules(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk_rules(item)


def own_values(node: Any, key: str | None = None) -> Iterator[tuple[str | None, Any]]:
    """(key, scalar) pairs of a rule, not descending into nested rules."""
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, dict) and "id" in v:
                continue
            if isinstance(v, list) and any(isinstance(i, dict) and "id" in i for i in v):
                continue
            yield from own_values(v, k)
    elif isinstance(node, list):
        for item in node:
            yield from own_values(item, key)
    else:
        yield key, node


NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}


def text_numbers(text: str) -> set[float]:
    numbers = {float(m.replace(",", "")) for m in NUMBER_RE.findall(text)}
    words = re.findall(r"[a-z]+", text.lower())
    return numbers | {float(NUMBER_WORDS[w]) for w in words if w in NUMBER_WORDS}


ALL_RULES = [(name, rule) for name in RULE_FILES for rule in walk_rules(load(name))]
RULE_IDS = {rule["id"] for _, rule in ALL_RULES}
CITATION_IDS = {c["id"] for c in load("citations.yaml")["citations"]}


def rule_param(name: str, rule: dict[str, Any]) -> Any:
    return pytest.param(rule, id=f"{name}:{rule['id']}")


RULE_PARAMS = [rule_param(name, rule) for name, rule in ALL_RULES]


def test_rule_ids_are_unique() -> None:
    ids = [rule["id"] for _, rule in ALL_RULES]
    duplicates = {i for i in ids if ids.count(i) > 1}
    assert not duplicates


def test_citation_ids_are_unique() -> None:
    ids = [c["id"] for c in load("citations.yaml")["citations"]]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("rule", RULE_PARAMS)
def test_rule_has_required_fields(rule: dict[str, Any]) -> None:
    assert ID_RE.match(rule["id"])
    assert isinstance(rule.get("citation_ids"), list)
    assert isinstance(rule.get("verify"), bool)
    assert isinstance(rule.get("heuristic"), bool)
    assert set(rule["citation_ids"]) <= CITATION_IDS


@pytest.mark.parametrize("rule", RULE_PARAMS)
def test_tags_in_text_set_flags(rule: dict[str, Any]) -> None:
    text = rule.get("text", "")
    if "⚠️" in text:
        assert rule["verify"] is True
    if "🧪" in text:
        assert rule["heuristic"] is True


@pytest.mark.parametrize("rule", RULE_PARAMS)
def test_numbers_come_from_text(rule: dict[str, Any]) -> None:
    allowed = text_numbers(rule.get("text", ""))
    for key, value in own_values(rule):
        if key in POSITION_KEYS or isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            assert abs(value) in allowed, f"{key}={value} is not in the rule text"


@pytest.mark.parametrize("rule", RULE_PARAMS)
def test_rule_references_resolve(rule: dict[str, Any]) -> None:
    for key, value in own_values(rule):
        if key is None or not isinstance(value, str):
            continue
        if key.endswith("_rule_ids") or key in REF_KEYS or key == "exclude_pattern_ids":
            assert value in RULE_IDS, f"{key} -> {value}"


def test_day_types_match_model_literal() -> None:
    day_types = [d["day_type"] for d in load("daytypes.yaml")["day_types"]]
    assert sorted(day_types) == sorted(get_args(DayType))


def test_combo_goal_types_exist() -> None:
    goal_types = {g["type"] for g in load("goals.yaml")["goals"]} | {"any_deficit"}
    for combo in load("combos.yaml")["combinations"]:
        assert set(combo["goals"]) <= goal_types, combo["id"]
