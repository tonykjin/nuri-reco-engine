# The engine API: uvicorn on port 8000 (spec §11.1).
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependencies first, so code changes don't reinstall them.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

# The package stays an editable install: foods.py reads data/foods.json and api/examples.py reads
# tests/personas relative to the source tree.
COPY src ./src
COPY api ./api
COPY data/foods.json ./data/foods.json
COPY tests/personas ./tests/personas
RUN uv sync --locked --no-dev

RUN useradd --create-home --uid 10001 nuri
USER nuri

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"]
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
