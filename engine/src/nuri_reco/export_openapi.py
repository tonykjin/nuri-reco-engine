"""Write the API's OpenAPI schema to engine/openapi.json (the web app generates its client from it).

cd engine && uv run python -m nuri_reco.export_openapi            # writes openapi.json
cd engine && uv run python -m nuri_reco.export_openapi --stdout   # prints it instead
"""

import importlib
import json
import sys
from pathlib import Path
from typing import Any

ENGINE_DIR = Path(__file__).resolve().parents[2]
OPENAPI_JSON = ENGINE_DIR / "openapi.json"


def schema() -> dict[str, Any]:
    # The app lives in engine/api, outside the package; import it from the engine directory.
    if str(ENGINE_DIR) not in sys.path:
        sys.path.insert(0, str(ENGINE_DIR))
    app = importlib.import_module("api.main").app
    result: dict[str, Any] = app.openapi()
    return result


def render() -> str:
    return json.dumps(schema(), indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    text = render()
    if "--stdout" in args:
        sys.stdout.write(text)
        return
    OPENAPI_JSON.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OPENAPI_JSON}")


if __name__ == "__main__":
    main()
