# The NewsLens backend image: used for both the API and the worker (see compose.yaml).
FROM python:3.13.17-slim

# uv installs the exact package versions recorded in uv.lock.
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"
WORKDIR /app

COPY pyproject.toml uv.lock LICENSE ./
RUN uv sync --frozen --no-dev --no-install-project

COPY newslens ./newslens
COPY schema ./schema

# Run as an ordinary user, not root.
RUN useradd --system --uid 10001 newslens
USER newslens

EXPOSE 8000
CMD ["python", "-m", "newslens.serve"]
