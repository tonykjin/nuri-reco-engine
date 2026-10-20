# Nuri recommendation engine

Goal-aware nutrition plans for Nuri (Loam Labs). `engine/` is a standalone Python package and
FastAPI service; `web/` is a Next.js demo that calls it. The API contract is
[`engine/openapi.json`](engine/openapi.json).

## Run with Docker

Needs Docker Desktop running.

```
docker compose up --build
```

- Engine API: http://localhost:8000 (docs at http://localhost:8000/docs)
- Web demo: http://localhost:3000

Check the engine is up:

```
curl http://localhost:8000/health
# {"status":"ok"}
```

Stop everything with `docker compose down`.

The web app reaches the engine through `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`).
It's the engine's address as the browser sees it, and Next.js inlines it at build time, so set it
before building:

```
NEXT_PUBLIC_API_URL=https://engine.example.com docker compose up --build
```

## Run locally

```
cd engine && uv run pytest                                          # all tests incl. golden personas
cd engine && uv run uvicorn api.main:app --reload --port 8000
cd engine && uv run python -m nuri_reco.export_openapi              # writes engine/openapi.json
cd web && npm run dev                                               # http://localhost:3000
```

See [CLAUDE.md](CLAUDE.md) for the invariants and workflow.
