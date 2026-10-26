"""Trace mode (Task 22): record each engine stage and every rule it fired, in order.

engine.plan(..., trace=True) passes a Tracer through the pipeline; without one the engine skips
all of this, so normal responses are unchanged. Rule details come from the knowledge base, so a
viewer needs no logic of its own to show them.
"""

from typing import Any

from pydantic import BaseModel

from nuri_reco import explain
from nuri_reco.kb import KnowledgeBase
from nuri_reco.models import Trace, TraceCitation, TraceRule, TraceStage


def rule_ids_of(node: Any) -> list[str]:
    """Every rule id a value cites (any `*rule_ids` list or `rule_id`), in order of appearance."""
    found: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, BaseModel):
            value = value.model_dump()
        if isinstance(value, dict):
            for key, item in value.items():
                if key.endswith("rule_ids") and isinstance(item, list):
                    found.extend(i for i in item if isinstance(i, str))
                elif key == "rule_id" and isinstance(item, str):
                    found.append(item)
                else:
                    walk(item)
        elif isinstance(value, list | tuple):
            for item in value:
                walk(item)

    walk(node)
    return list(dict.fromkeys(found))


def dump(value: Any) -> Any:
    """JSON-ready form of a stage input or output."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(k): dump(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [dump(v) for v in value]
    return value


class Tracer:
    def __init__(self, kb: KnowledgeBase) -> None:
        self._kb = kb
        self.stages: list[TraceStage] = []

    @staticmethod
    def node(
        stage: str,
        *,
        rule_ids: list[str],
        inputs: dict[str, Any] | None = None,
        outputs: dict[str, Any] | None = None,
        children: list[TraceStage] | None = None,
    ) -> TraceStage:
        return TraceStage(
            stage=stage,
            rule_ids=list(dict.fromkeys(rule_ids)),
            inputs=dump(inputs or {}),
            outputs=dump(outputs or {}),
            children=children or [],
        )

    def stage(
        self,
        stage: str,
        *,
        rule_ids: list[str],
        inputs: dict[str, Any] | None = None,
        outputs: dict[str, Any] | None = None,
        children: list[TraceStage] | None = None,
    ) -> None:
        self.stages.append(
            self.node(stage, rule_ids=rule_ids, inputs=inputs, outputs=outputs, children=children)
        )

    def _rule(self, rule_id: str, files: dict[str, str]) -> TraceRule:
        kb = self._kb
        rule = kb.rules[rule_id]
        cites = [kb.citation_index[c] for c in rule.citation_ids if c in kb.citation_index]
        return TraceRule(
            id=rule_id,
            file=files[rule_id],
            text=rule.text,
            why=explain.text(kb, rule_id, "rule") if explain.has(kb, rule_id, "rule") else None,
            verify=rule.verify,
            heuristic=rule.heuristic,
            citations=[TraceCitation(id=c.id, label=c.label, url=c.url) for c in cites],
        )

    def build(self) -> Trace:
        fired: list[str] = []

        def walk(stages: list[TraceStage]) -> None:
            for s in stages:
                fired.extend(s.rule_ids)
                walk(s.children)

        walk(self.stages)
        fired = list(dict.fromkeys(fired))
        files = {r.id: name for name, rules in self._kb.rules_by_file().items() for r in rules}
        return Trace(
            stages=self.stages,
            rules_fired=fired,
            rules={r: self._rule(r, files) for r in fired if r in self._kb.rules},
        )
