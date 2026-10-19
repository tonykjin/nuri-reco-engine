PROJECT: Nuri recommendation engine (Loam Labs). Repo: C:\Users\tonyj\dev\nuri-reco-engine
SPEC: Notion "Recommendation Engine — Goal Matrix & Build Plan (v0.1)" (child of Nuri Master PRD).
      The matrices (A-F) on that page are the source of truth; engine/src/nuri_reco/knowledge/*.yaml mirrors them.
STACK: Python 3.12 + uv + FastAPI + pydantic v2 (engine/), Next.js App Router + TS + Tailwind (web/).

INVARIANTS (never break):
1. Safety (Matrix F) runs first and overrides every goal. Blocked cases return no targets.
2. Every output item has provenance="recommended", rule_ids and a plain-language why. No medical claims.
3. Knowledge is data, not code: thresholds live in YAML with ids + citation_ids + verify flag.
4. Engine is pure and deterministic: no I/O inside stages, no persistence, caller passes full profile.
5. One primary energy direction per phase; protein stays high in every phase; general health always on.
6. Taste is a re-rank inside a health-scored set, never the primary sort.
7. Missing nutrient data stays missing (never treated as 0).
8. Every plan returns goal_summary + loam_score_profile (Matrix G, section 7b); score weights sum to 100
   and condition goals never get their signature components blended down.
9. The API is UI-agnostic. Onboarding answer -> PlanRequest mapping lives only in
   web/lib/onboarding/mapAnswers.ts. The web app holds no nutrition logic.

ENDPOINTS: /v1/plan (?dry_run=true) · /v1/score/profile · /v1/score/evaluate (M6) ·
  /v1/recommendations/foods · /v1/recommendations/day · /v1/safety/check · /v1/knowledge/* · /health
DEMO: web/app/onboarding/[step] (14 screens, section 11.3) -> web/app/results (goals panel,
  Loam Score panel, dev drawer).

COMMANDS:
  cd engine && uv run pytest            # all tests incl. golden personas
  cd engine && uv run uvicorn api.main:app --reload --port 8000
  cd engine && uv run python -m nuri_reco.export_openapi > openapi.json
  cd web && npm run gen:api && npm run dev   # http://localhost:3000

GOLDEN PERSONAS: engine/tests/personas/*.json (Maya, novice recomp, marathon+fatloss,
  wedding-8wk clamp, hybrid, GLP-1+T2D+strength, vegan muscle, blocked x3).

WORKFLOW: follow the Notion page "Build Runbook — Reco Engine (prompts + PR checkoffs)":
session opener -> task prompt -> PR -> checkoff -> merge -> closing prompt.
1 task = 1 branch = 1 PR. Update the task status + session log below after each merge.
