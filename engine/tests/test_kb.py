import shutil
from pathlib import Path

import pytest

from nuri_reco.kb import KNOWLEDGE_DIR, KnowledgeError, load_kb, load_kb_from, main

BROKEN = Path(__file__).parent / "fixtures" / "kb_broken"


def broken_kb(case: str, tmp_path: Path) -> Path:
    """The real knowledge base with one file replaced by kb_broken/<case>/."""
    directory = tmp_path / "knowledge"
    shutil.copytree(KNOWLEDGE_DIR, directory)
    for override in (BROKEN / case).iterdir():
        shutil.copy(override, directory / override.name)
    return directory


def test_real_kb_loads() -> None:
    kb = load_kb()
    assert len(kb.goals.goals) == 11
    assert {d.day_type for d in kb.daytypes.day_types} == {
        "rest",
        "easy",
        "quality",
        "long",
        "carb_load",
    }
    floor = kb.rules["GUARD.CALORIE_FLOOR"].model_extra or {}
    assert floor["absolute_min_kcal_per_day"] == 800
    assert kb.rules["GUARD.SGLT2"].verify is True
    assert "ISSN2017" in kb.citation_index


def test_load_kb_is_cached() -> None:
    assert load_kb() is load_kb()


def test_nested_rules_are_indexed() -> None:
    kb = load_kb()
    assert kb.rules["GOAL.GLP1.PROTEIN"].verify is True
    assert kb.rules["COMBO.LOSEFAT_DEADLINE.STEP_BACK"].heuristic is True


@pytest.mark.parametrize(
    ("case", "message"),
    [
        (
            "unknown_citation",
            r"unknown citation ids: GUARD\.CALORIE_FLOOR -> XXX \(guardrails\.yaml\)",
        ),
        (
            "duplicate_rule_id",
            r"duplicate rule ids: GOAL\.LOSE_FAT in goals\.yaml, guardrails\.yaml",
        ),
        ("missing_required_field", r"guardrails\.yaml:.*verify\s+Field required"),
        (
            "range_min_gt_max",
            r"guardrails\.yaml:.*protein_cap_g_per_kg\.with_diabetes has min 0\.8 > max 0\.6",
        ),
        ("non_bool_flag", r"guardrails\.yaml:.*verify\s+Input should be a valid boolean"),
        ("unknown_key", r"guardrails\.yaml:.*guardrail\s+Extra inputs are not permitted"),
        ("invalid_yaml", r"guardrails\.yaml: invalid YAML"),
        ("duplicate_citation", r"citations\.yaml: duplicate citation ids: HELMS2014"),
        (
            "weight_row_not_100",
            r"score_weights\.yaml:.*LSW\.ROW\.WEIGHTLOSS: weights sum to 101, not 100",
        ),
    ],
)
def test_broken_kb_fails_loudly(case: str, message: str, tmp_path: Path) -> None:
    with pytest.raises(KnowledgeError, match=f"(?s){message}"):
        load_kb_from(broken_kb(case, tmp_path))


def test_missing_file(tmp_path: Path) -> None:
    directory = tmp_path / "knowledge"
    shutil.copytree(KNOWLEDGE_DIR, directory)
    (directory / "patterns.yaml").unlink()
    with pytest.raises(KnowledgeError, match=r"patterns\.yaml: file is missing"):
        load_kb_from(directory)


def test_every_broken_fixture_is_tested() -> None:
    cases = {p.name for p in BROKEN.iterdir() if p.is_dir()}
    tested = {
        "unknown_citation",
        "duplicate_rule_id",
        "missing_required_field",
        "range_min_gt_max",
        "non_bool_flag",
        "unknown_key",
        "invalid_yaml",
        "duplicate_citation",
        "weight_row_not_100",
    }
    assert cases == tested


def test_cli_summary(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--summary"]) == 0
    out = capsys.readouterr().out
    for name in [
        "goals",
        "combos",
        "phases",
        "daytypes",
        "patterns",
        "food_weights",
        "guardrails",
        "targets",
        "micronutrients",
        "score_weights",
    ]:
        assert f"{name}.yaml" in out
    assert "total" in out


def test_cli_reports_invalid_kb(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--dir", str(broken_kb("unknown_citation", tmp_path))]) == 1
    assert "knowledge base invalid" in capsys.readouterr().out
