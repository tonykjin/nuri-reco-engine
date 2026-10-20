"""Stage 7: explanations (spec §10, §7b.4; claims guardrail spec §8, PRD §4 and §11).

Every sentence the engine shows comes from knowledge/explanations.yaml, keyed by rule id, through
text(). Each rendered string goes through the claims filter (GUARD.CLAIMS forbidden phrases), so a
banned phrase fails loudly instead of reaching a user. collect_citations() gathers the sources
behind every rule a plan cites.
"""

import re
from typing import Any

from pydantic import BaseModel

from nuri_reco.kb import KnowledgeBase


class ExplanationMissing(KeyError):
    """No template for a rule id / variant."""


class ClaimsViolation(ValueError):
    """Copy contains a phrase the claims guardrail forbids."""


def claims_violations(text: str, kb: KnowledgeBase) -> list[str]:
    """Forbidden claim phrases (GUARD.CLAIMS) found in text, matched as whole words."""
    phrases = (kb.rules["GUARD.CLAIMS"].model_extra or {})["forbidden_phrases"]
    return [p for p in phrases if re.search(rf"\b{re.escape(p)}\b", text, flags=re.IGNORECASE)]


def has(kb: KnowledgeBase, rule_id: str, variant: str) -> bool:
    return variant in kb.explanations.templates.get(rule_id, {})


def text(kb: KnowledgeBase, rule_id: str, variant: str = "rule", **values: Any) -> str:
    """The rendered sentence for a rule id and variant; raises if missing or if it makes a claim."""
    try:
        template = kb.explanations.templates[rule_id][variant]
    except KeyError:
        raise ExplanationMissing(f"no {variant!r} explanation for {rule_id}") from None
    rendered = template.format(**values)
    banned = claims_violations(rendered, kb)
    if banned:
        raise ClaimsViolation(f"{rule_id}.{variant} uses banned phrases {banned}: {rendered!r}")
    return rendered


def collect_citations(model: BaseModel, kb: KnowledgeBase) -> list[str]:
    """Citation ids behind every rule id the model cites, in order of first appearance."""
    out: list[str] = []
    for rule_id in rule_ids_in(model):
        if rule_id in kb.rules:
            out.extend(kb.rules[rule_id].citation_ids)
    return list(dict.fromkeys(out))


def rule_ids_in(model: BaseModel) -> list[str]:
    """Every rule id a model cites (rule_ids, weight_rule_ids, rule_id), in order of appearance."""
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("rule_ids", "weight_rule_ids") and isinstance(value, list):
                    found.extend(value)
                elif key == "rule_id" and isinstance(value, str):
                    found.append(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(model.model_dump())
    return list(dict.fromkeys(found))


# Fields that hold data rather than copy (USDA food names, ids, dates).
DATA_FIELDS = {
    "name",
    "key",
    "id",
    "rule_id",
    "rule_ids",
    "weight_rule_ids",
    "citations",
    "type",
    "unit",
}


def strings_in(model: BaseModel) -> list[tuple[str, str]]:
    """(path, text) for every user-facing string in a model."""
    found: list[tuple[str, str]] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key not in DATA_FIELDS:
                    walk(value, f"{path}.{key}" if path else str(key))
        elif isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, f"{path}[{i}]")
        elif isinstance(node, str):
            found.append((path, node))

    walk(model.model_dump(mode="json"), "")
    return found


def banned_phrases_in(model: BaseModel, kb: KnowledgeBase) -> list[str]:
    """Claims-filter hits anywhere in a model's user-facing strings, as 'path: phrases'."""
    return [
        f"{path}: {hits}" for path, s in strings_in(model) if (hits := claims_violations(s, kb))
    ]
