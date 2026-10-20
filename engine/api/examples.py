"""OpenAPI examples: the golden personas (tests/personas/*.json, spec §11.2) without `expect`."""

import json
import re
from pathlib import Path
from typing import Any

PERSONAS = Path(__file__).resolve().parents[1] / "tests" / "personas"


def _summaries() -> dict[str, str]:
    """File stem -> persona description, from the table in tests/personas/README.md."""
    readme = PERSONAS / "README.md"
    if not readme.exists():
        return {}
    rows = re.findall(r"^\|\s*`(\w+)\.json`\s*\|\s*([^|]+?)\s*\|", readme.read_text("utf-8"), re.M)
    return dict(rows)


def persona_requests() -> dict[str, dict[str, Any]]:
    """Persona name -> PlanRequest body, Maya first."""
    out: dict[str, dict[str, Any]] = {}
    for path in sorted(PERSONAS.glob("*.json"), key=lambda p: (p.stem != "maya", p.stem)):
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw.pop("expect", None)
        out[path.stem] = raw
    return out


def plan_examples() -> dict[str, dict[str, Any]]:
    summaries = _summaries()
    return {
        name: {"summary": name, "description": summaries.get(name, ""), "value": body}
        for name, body in persona_requests().items()
    }


def food_examples() -> dict[str, dict[str, Any]]:
    """Each persona as a foods request: lunch on their most common day type."""
    out = {}
    for name, example in plan_examples().items():
        schedule = example["value"]["profile"]["training"]["weekly_schedule"]
        day = max(sorted(set(schedule)), key=schedule.count)
        value = {
            "request": example["value"],
            "context": {"meal_slot": "lunch", "day_type": day},
            "limit": 10,
        }
        out[name] = {**example, "value": value}
    return out
