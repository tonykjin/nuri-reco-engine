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


def day_examples() -> dict[str, dict[str, Any]]:
    """Each persona as a sample-day request: the hardest day type in their week."""
    order = ["carb_load", "long", "quality", "easy", "rest"]
    out = {}
    for name, example in plan_examples().items():
        schedule = example["value"]["profile"]["training"]["weekly_schedule"]
        day = next(d for d in order if d in schedule)
        out[name] = {**example, "value": {"request": example["value"], "day_type": day}}
    return out


def trace_examples() -> dict[str, dict[str, Any]]:
    """Each persona as a trace request; Maya also with simulated weeks of logs."""
    out = {name: {**ex, "value": {"request": ex["value"]}} for name, ex in plan_examples().items()}
    maya = out.get("maya")
    if maya:
        out["maya_simulated"] = {
            **maya,
            "summary": f"{maya['summary']} with simulated logs",
            "value": {**maya["value"], "simulate_history": True},
        }
    return out


def evaluate_examples() -> dict[str, dict[str, Any]]:
    """Maya and the marathoner scoring the same chicken, rice and broccoli meal."""
    meal = [
        {"key": "chicken_breast_roasted", "grams": 150},
        {"key": "rice_white_cooked", "grams": 200},
        {"key": "broccoli_boiled", "grams": 100},
    ]
    examples = plan_examples()
    return {
        name: {**examples[name], "value": {"request": examples[name]["value"], "items": meal}}
        for name in ("maya", "marathon_fatloss")
        if name in examples
    }
