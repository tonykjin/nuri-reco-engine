"""FastAPI app for the Nuri recommendation engine."""

from fastapi import FastAPI

app = FastAPI(title="Nuri Recommendation Engine")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
