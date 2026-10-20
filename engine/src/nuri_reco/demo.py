"""Dev script: run a golden persona (or any PlanRequest JSON file) and print the PlanResponse.

uv run python -m nuri_reco.demo maya
uv run python -m nuri_reco.demo path/to/request.json
"""

import argparse
import json
import sys
from pathlib import Path

from nuri_reco.engine import plan
from nuri_reco.models import PlanRequest

PERSONAS = Path(__file__).resolve().parents[2] / "tests" / "personas"


def load_request(name_or_path: str) -> PlanRequest:
    path = Path(name_or_path)
    if not path.suffix:
        path = PERSONAS / f"{name_or_path}.json"
    if not path.exists():
        known = ", ".join(sorted(p.stem for p in PERSONAS.glob("*.json")))
        raise SystemExit(f"no persona or file {name_or_path!r}; personas: {known}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw.pop("expect", None)
    return PlanRequest.model_validate(raw)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m nuri_reco.demo", description=__doc__)
    parser.add_argument("persona", help="persona name (e.g. maya) or a PlanRequest JSON path")
    args = parser.parse_args(argv)
    response = plan(load_request(args.persona))
    # Copy uses characters like "≤"; don't depend on the console's code page.
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    print(response.model_dump_json(indent=2, exclude_none=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
