# The audit needs a real browser, so the image carries Chromium and the fonts a page expects.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# libatomic1 is what playwright's own node driver needs on a slim image; the browser's system
# libraries arrive with `playwright install --with-deps` below.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates libatomic1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies first: the layer survives code edits.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY . .
RUN uv sync --frozen --no-dev \
    && uv run playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

# One process per container: the deployments this file targets run a single instance.
CMD ["uv", "run", "uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
