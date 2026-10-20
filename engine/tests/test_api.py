"""API contract tests (spec §10 endpoints table): every persona on /v1/plan and /v1/score/profile,
the error shape, CORS, the dry_run budget and the committed openapi.json."""

import json
import statistics
import time
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.examples import persona_requests
from api.main import app
from nuri_reco.export_openapi import OPENAPI_JSON, render
from nuri_reco.models import LoamScoreProfile, PlanResponse

PERSONAS = Path(__file__).parent / "personas"
NAMES = sorted(p.stem for p in PERSONAS.glob("*.json"))
client = TestClient(app, raise_server_exceptions=False)


@cache
def persona(name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    raw = json.loads((PERSONAS / f"{name}.json").read_text(encoding="utf-8"))
    return raw, raw.pop("expect")


def assert_error(resp: Any, status: int, code: str) -> dict[str, Any]:
    assert resp.status_code == status, resp.text
    body: dict[str, Any] = resp.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details"}
    assert body["error"]["code"] == code
    assert body["error"]["message"]
    return body


# --- /v1/plan and /v1/score/profile for every persona ---


@pytest.mark.parametrize("name", NAMES)
def test_plan(name: str) -> None:
    body, expect = persona(name)
    resp = client.post("/v1/plan", json=body)
    assert resp.status_code == 200, resp.text
    out = PlanResponse.model_validate(resp.json())
    assert out.status == expect["status"]
    if out.status == "blocked":
        assert out.phases == [] and out.patterns == [] and out.foods == []
    else:
        assert out.phases and out.patterns and out.foods
    assert out.goal_summary.headline
    assert out.citations


@pytest.mark.parametrize("name", NAMES)
def test_plan_dry_run(name: str) -> None:
    body, expect = persona(name)
    resp = client.post("/v1/plan", params={"dry_run": "true"}, json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    for key in ("safety", "phases", "feasibility", "goal_summary", "loam_score_profile"):
        assert key in data
    assert data["patterns"] == [] and data["foods"] == []
    assert data["status"] == expect["status"]
    if data["status"] != "blocked":
        assert all(p["targets_by_day_type"] for p in data["phases"])


@pytest.mark.parametrize("name", NAMES)
def test_score_profile(name: str) -> None:
    body, expect = persona(name)
    resp = client.post("/v1/score/profile", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert set(data) == set(LoamScoreProfile.model_fields)
    out = LoamScoreProfile.model_validate(data)
    full = client.post("/v1/plan", params={"dry_run": "true"}, json=body).json()
    assert data == full["loam_score_profile"]
    assert (out.by_phase == []) == (expect["status"] == "blocked")


def test_dry_run_is_fast_enough_for_a_slider() -> None:
    body, _ = persona("marathon_fatloss")
    client.post("/v1/plan", params={"dry_run": "true"}, json=body)  # warm the knowledge base
    times = []
    for _ in range(5):
        start = time.perf_counter()
        resp = client.post("/v1/plan", params={"dry_run": "true"}, json=body)
        times.append((time.perf_counter() - start) * 1000)
        assert resp.status_code == 200
    assert statistics.median(times) < 150, f"dry_run took {statistics.median(times):.0f} ms"


# --- The other endpoints ---


def test_health() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.parametrize("path", ["/v1/score/evaluate", "/v1/recommendations/day"])
def test_not_implemented_yet(path: str) -> None:
    assert_error(client.post(path, json={}), 501, "not_implemented")


@pytest.mark.parametrize(
    ("name", "status"), [("maya", "ok"), ("glp1_t2d_strength", "rd_review"), ("under18", "blocked")]
)
def test_safety_check(name: str, status: str) -> None:
    body, _ = persona(name)
    resp = client.post("/v1/safety/check", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == status
    assert data["calorie_floor"]["rule_id"] == "GUARD.CALORIE_FLOOR"
    if status == "blocked":
        assert data["blocks"] and all(b["rule_ids"] and b["why"] for b in data["blocks"])
    assert "phases" not in data and "targets_by_day_type" not in json.dumps(data)


def test_recommend_foods() -> None:
    body, _ = persona("marathon_fatloss")
    request = {
        "request": body,
        "context": {"meal_slot": "pre_race", "day_type": "long"},
        "limit": 5,
    }
    resp = client.post("/v1/recommendations/foods", json=request)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "ok"
    assert len(data["foods"]) == 5
    for food in data["foods"]:
        assert food["provenance"] == "recommended" and food["rule_ids"] and food["why"]
        assert "peanut" not in food["name"].lower()
    assert data["citations"]


def test_recommend_foods_when_blocked() -> None:
    body, _ = persona("under18")
    resp = client.post("/v1/recommendations/foods", json={"request": body})
    assert resp.status_code == 200
    assert resp.json() == {"status": "blocked", "foods": [], "citations": []}


@pytest.mark.parametrize("name", ["goals", "patterns", "guardrails", "score_weights"])
def test_knowledge(name: str) -> None:
    resp = client.get(f"/v1/knowledge/{name}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["spec_section"]
    assert "citation_ids" in json.dumps(data)


def test_unknown_knowledge_file() -> None:
    assert_error(client.get("/v1/knowledge/secrets"), 404, "not_found")


# --- Errors ---


def test_validation_error_shape() -> None:
    body, _ = persona("maya")
    bad = {**body, "profile": {**body["profile"], "age": -1}}
    data = assert_error(client.post("/v1/plan", json=bad), 422, "validation_error")
    assert data["error"]["details"][0]["loc"] == ["body", "profile", "age"]


def test_unknown_field_is_rejected() -> None:
    body, _ = persona("maya")
    assert_error(client.post("/v1/plan", json={**body, "screen": 3}), 422, "validation_error")


def test_unknown_goal_type() -> None:
    body, _ = persona("maya")
    bad = {**body, "goals": [{"type": "fly", "priority": 1}]}
    data = assert_error(client.post("/v1/plan", json=bad), 422, "unknown_goal_type")
    assert data["error"]["details"][0]["loc"] == ["body", "goals", 0, "type"]


def test_engine_value_error_is_a_422() -> None:
    body, _ = persona("maya")
    bad = {**body, "profile": {**body["profile"], "activity": "couch"}}
    data = assert_error(client.post("/v1/plan", json=bad), 422, "invalid_request")
    assert "couch" in data["error"]["message"]


def test_malformed_json() -> None:
    resp = client.post(
        "/v1/plan", content=b"{not json", headers={"content-type": "application/json"}
    )
    assert_error(resp, 422, "validation_error")


def test_wrong_method() -> None:
    assert_error(client.get("/v1/plan"), 405, "method_not_allowed")


# --- CORS ---


def test_cors_allows_the_web_app() -> None:
    resp = client.options(
        "/v1/plan",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"},
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_rejects_other_origins() -> None:
    resp = client.get("/health", headers={"Origin": "https://example.com"})
    assert "access-control-allow-origin" not in resp.headers


# --- OpenAPI ---


def test_openapi_json_is_up_to_date() -> None:
    assert OPENAPI_JSON.read_text(encoding="utf-8") == render(), (
        "engine/openapi.json is stale: run `uv run python -m nuri_reco.export_openapi`"
    )


def test_every_persona_is_an_openapi_example() -> None:
    schema = app.openapi()
    for path in ("/v1/plan", "/v1/score/profile", "/v1/safety/check"):
        content = schema["paths"][path]["post"]["requestBody"]["content"]["application/json"]
        assert sorted(content["examples"]) == NAMES
        assert next(iter(content["examples"])) == "maya"
    assert persona_requests()["maya"] == persona("maya")[0]


def test_schema_is_domain_level() -> None:
    text = render().lower()
    for word in ("onboarding", "screen", "slider", "button"):
        assert word not in text, f"openapi.json mentions {word!r}"
