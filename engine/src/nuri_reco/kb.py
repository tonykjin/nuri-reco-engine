"""Load and validate the knowledge base (knowledge/*.yaml) into typed models.

Every rule carries id, citation_ids, verify and heuristic (spec §10 principles). Loading fails
loudly with a KnowledgeError on a schema error, a duplicate rule id across files, an unknown
citation id, or a {min, max} range with min > max.

    uv run python -m nuri_reco.kb --summary
"""

import argparse
import functools
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Self, TypeGuard

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError, model_validator

from nuri_reco.models import DayType

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"
RULE_ID_PATTERN = r"^[A-Z0-9_]+(\.[A-Z0-9_]+)+$"


class KnowledgeError(ValueError):
    """The knowledge base failed to load or validate."""


class Rule(BaseModel):
    """Any knowledge rule. Rule-specific values (ranges, thresholds) are kept as extra fields."""

    model_config = ConfigDict(extra="allow", frozen=True)

    id: str = Field(pattern=RULE_ID_PATTERN)
    citation_ids: list[str]
    verify: StrictBool
    heuristic: StrictBool
    text: str | None = None

    @model_validator(mode="after")
    def _ranges_ordered(self) -> Self:
        for path, low, high in _ranges(self.model_extra or {}):
            if low > high:
                raise ValueError(f"range {path} has min {low} > max {high}")
        return self


def _ranges(node: Any, path: str = "") -> Iterator[tuple[str, float, float]]:
    """Every {min, max} pair with both values numeric, skipping nested rules."""
    if isinstance(node, dict):
        if "id" in node and path:
            return
        low, high = node.get("min"), node.get("max")
        if _is_number(low) and _is_number(high):
            yield path or "<rule>", low, high
        for key, value in node.items():
            yield from _ranges(value, f"{path}.{key}" if path else str(key))
    elif isinstance(node, list):
        for i, item in enumerate(node):
            yield from _ranges(item, f"{path}[{i}]")


def _is_number(value: Any) -> TypeGuard[float]:
    return isinstance(value, int | float) and not isinstance(value, bool)


class FileModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    spec_section: str


# --- Per-file schemas ---


class GoalRule(Rule):
    type: str
    name: str
    rd_gated: StrictBool
    rules: dict[str, Rule]


class GoalsFile(FileModel):
    method: Rule
    goals: list[GoalRule]


class ComboRule(Rule):
    goals: list[str]
    name: str
    rules: list[Rule] = Field(default_factory=list)


class CombosFile(FileModel):
    tiers: list[Rule]
    tier_rule: Rule
    resolver_rules: list[Rule]
    combinations: list[ComboRule]


class PhaseRule(Rule):
    name: str


class PhasesFile(FileModel):
    boundary_note: Rule
    phases: list[PhaseRule]
    feasibility: Rule
    diet_breaks: Rule
    pre_event: Rule


class DayTypeRule(Rule):
    day_type: DayType
    name: str


class DayTypesFile(FileModel):
    caption: Rule
    day_types: list[DayTypeRule]
    timing: list[Rule]
    per_meal_note: Rule


class PatternRule(Rule):
    pattern: str
    name: str
    offered: StrictBool


class PatternsFile(FileModel):
    evidence_grades: Rule
    patterns: list[PatternRule]
    selection: list[Rule]


class FoodWeightsFile(FileModel):
    attributes: list[Rule]
    normalization: Rule
    weights: list[Rule]
    seed_foods: list[Rule]
    ranking_pipeline: list[Rule]
    ranking_note: Rule
    ranking_params: list[Rule]


class GuardrailsFile(FileModel):
    guardrails: list[Rule]


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    label: str
    url: str | None
    alt_urls: list[str] = Field(default_factory=list)
    in_sources: StrictBool


class CitationsFile(FileModel):
    citations: list[Citation]


class TargetsFile(FileModel):
    mifflin_st_jeor: Rule
    activity_factors: Rule
    kcal_per_kg: Rule
    energy_position: Rule
    protein_position: Rule
    fat: Rule
    carb_tiers: Rule
    deficit_split: Rule
    fiber: Rule


class MicronutrientRule(Rule):
    nutrient: str
    unit: str
    window: str
    values: list[dict[str, Any]] = Field(min_length=1)


class MicronutrientsFile(FileModel):
    nutrients: list[MicronutrientRule]


class WeightRow(Rule):
    goal_types: list[str] = Field(min_length=1)
    weights: dict[str, float]


class GoalTypesRule(Rule):
    goal_types: list[str] = Field(min_length=1)


class ComponentTargetRule(Rule):
    component: str
    score_type: str


class ExpenditureFile(FileModel):
    trend_weight: Rule
    energy_density: Rule
    energy_balance: Rule
    takeover: Rule
    simulation: Rule


class ScoreEvalFile(FileModel):
    formulas: Rule
    coverage: Rule
    meal_share: Rule
    nutrients: Rule


class WeightRangeFile(FileModel):
    bmi: Rule
    older: Rule
    body_fat: Rule
    milestone: Rule
    slider: Rule


class ComposeFile(FileModel):
    tolerance: Rule
    templates: list[Rule]
    roles: Rule
    portions: Rule
    search: Rule


class ExplanationsFile(FileModel):
    """explanations.yaml: rule id -> variant -> sentence template (no rules of its own)."""

    templates: dict[str, dict[str, str]]


class ConstraintRulesFile(FileModel):
    rules: list[Rule]


class SummaryFile(FileModel):
    headlines: Rule
    resolved_as: Rule


class ScoreWeightsFile(FileModel):
    components: list[str] = Field(min_length=1)
    rows: list[WeightRow]
    stacking: Rule
    floors: list[GoalTypesRule]
    floor_rule: Rule
    floor_conflict: Rule
    priors: Rule
    levers: Rule
    component_targets: list[ComponentTargetRule]
    applies_to: Rule

    @model_validator(mode="after")
    def _rows_complete(self) -> Self:
        expected = set(self.components)
        for row in self.rows:
            if set(row.weights) != expected:
                raise ValueError(f"{row.id}: weights must cover exactly {self.components}")
            total = sum(row.weights.values())
            if abs(total - 100) > 1e-9:
                raise ValueError(f"{row.id}: weights sum to {total:g}, not 100")
        for floor in self.floors:
            unknown = set((floor.model_extra or {}).get("minimums", {})) - expected
            if unknown:
                raise ValueError(f"{floor.id}: unknown components {sorted(unknown)}")
        return self


FILE_MODELS: dict[str, type[FileModel]] = {
    "goals": GoalsFile,
    "combos": CombosFile,
    "phases": PhasesFile,
    "daytypes": DayTypesFile,
    "patterns": PatternsFile,
    "food_weights": FoodWeightsFile,
    "guardrails": GuardrailsFile,
    "targets": TargetsFile,
    "micronutrients": MicronutrientsFile,
    "score_weights": ScoreWeightsFile,
    "summary": SummaryFile,
    "constraints": ConstraintRulesFile,
    "compose": ComposeFile,
    "expenditure": ExpenditureFile,
    "score_eval": ScoreEvalFile,
    "weight_range": WeightRangeFile,
    "explanations": ExplanationsFile,
    "citations": CitationsFile,
}


class KnowledgeBase(BaseModel):
    model_config = ConfigDict(frozen=True)

    goals: GoalsFile
    combos: CombosFile
    phases: PhasesFile
    daytypes: DayTypesFile
    patterns: PatternsFile
    food_weights: FoodWeightsFile
    guardrails: GuardrailsFile
    targets: TargetsFile
    micronutrients: MicronutrientsFile
    score_weights: ScoreWeightsFile
    summary: SummaryFile
    constraints: ConstraintRulesFile
    compose: ComposeFile
    expenditure: ExpenditureFile
    score_eval: ScoreEvalFile
    weight_range: WeightRangeFile
    explanations: ExplanationsFile
    citations: CitationsFile

    def rules_by_file(self) -> dict[str, list[Rule]]:
        return {
            name: list(iter_rules(getattr(self, name)))
            for name in FILE_MODELS
            if name not in ("citations", "explanations")
        }

    @functools.cached_property
    def rules(self) -> dict[str, Rule]:
        return {rule.id: rule for rules in self.rules_by_file().values() for rule in rules}

    @functools.cached_property
    def citation_index(self) -> dict[str, Citation]:
        return {c.id: c for c in self.citations.citations}


def iter_rules(node: Any) -> Iterator[Rule]:
    """Every Rule in a model tree, including rules nested inside other rules."""
    if isinstance(node, Rule):
        yield node
    if isinstance(node, BaseModel):
        for name in type(node).model_fields:
            yield from iter_rules(getattr(node, name))
    elif isinstance(node, list):
        for item in node:
            yield from iter_rules(item)
    elif isinstance(node, dict):
        for item in node.values():
            yield from iter_rules(item)


def _load_file(directory: Path, name: str) -> FileModel:
    path = directory / f"{name}.yaml"
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise KnowledgeError(f"{path.name}: file is missing") from e
    except yaml.YAMLError as e:
        raise KnowledgeError(f"{path.name}: invalid YAML: {e}") from e
    try:
        return FILE_MODELS[name].model_validate(raw)
    except ValidationError as e:
        raise KnowledgeError(f"{path.name}: {e}") from e


def _cross_check(kb: KnowledgeBase) -> None:
    by_file = kb.rules_by_file()

    files_for_id: dict[str, list[str]] = {}
    for name, rules in by_file.items():
        for rule in rules:
            files_for_id.setdefault(rule.id, []).append(f"{name}.yaml")
    duplicates = {rid: files for rid, files in files_for_id.items() if len(files) > 1}
    if duplicates:
        detail = "; ".join(
            f"{rid} in {', '.join(files)}" for rid, files in sorted(duplicates.items())
        )
        raise KnowledgeError(f"duplicate rule ids: {detail}")

    citation_counts = Counter(c.id for c in kb.citations.citations)
    repeated = sorted(cid for cid, n in citation_counts.items() if n > 1)
    if repeated:
        raise KnowledgeError(f"citations.yaml: duplicate citation ids: {', '.join(repeated)}")

    unknown = [
        f"{rule.id} -> {cid} ({name}.yaml)"
        for name, rules in by_file.items()
        for rule in rules
        for cid in rule.citation_ids
        if cid not in citation_counts
    ]
    if unknown:
        raise KnowledgeError(f"unknown citation ids: {'; '.join(unknown)}")

    unknown_templates = sorted(set(kb.explanations.templates) - set(kb.rules))
    if unknown_templates:
        raise KnowledgeError(
            f"explanations.yaml: templates for unknown rule ids: {unknown_templates}"
        )


def load_kb_from(directory: Path) -> KnowledgeBase:
    """Load and validate the knowledge base in `directory` (uncached)."""
    files = {name: _load_file(directory, name) for name in FILE_MODELS}
    kb = KnowledgeBase.model_validate(files)
    _cross_check(kb)
    return kb


@functools.cache
def load_kb() -> KnowledgeBase:
    """The packaged knowledge base, loaded once per process."""
    return load_kb_from(KNOWLEDGE_DIR)


def summary(kb: KnowledgeBase) -> str:
    lines = [f"{'file':<20}{'rules':>7}{'verify':>8}{'heuristic':>11}"]
    totals = [0, 0, 0]
    for name, rules in kb.rules_by_file().items():
        counts = [len(rules), sum(r.verify for r in rules), sum(r.heuristic for r in rules)]
        totals = [t + c for t, c in zip(totals, counts, strict=True)]
        lines.append(f"{name + '.yaml':<20}{counts[0]:>7}{counts[1]:>8}{counts[2]:>11}")
    lines.append(f"{'total':<20}{totals[0]:>7}{totals[1]:>8}{totals[2]:>11}")
    lines.append(f"citations: {len(kb.citations.citations)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m nuri_reco.kb", description=__doc__)
    parser.add_argument("--summary", action="store_true", help="print rule counts per file")
    parser.add_argument("--dir", type=Path, default=KNOWLEDGE_DIR, help="knowledge directory")
    args = parser.parse_args(argv)
    try:
        kb = load_kb_from(args.dir)
    except KnowledgeError as e:
        print(f"knowledge base invalid: {e}")
        return 1
    print(summary(kb) if args.summary else "knowledge base OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
