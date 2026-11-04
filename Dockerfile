# Cloud Run image. Continuous deploy: Cloud Run > Connect repository > Developer Connect > Dockerfile.
FROM python:3.11-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .
# The snapshot ships with the image (data/autopsy.duckdb). If DATA_GCS_URI is set instead, entrypoint fetches it.
ENV PATH="/app/.venv/bin:$PATH" PORT=8080
CMD ["sh", "-c", "python scripts/fetch_snapshot.py && uvicorn app:app --host 0.0.0.0 --port ${PORT} --timeout-keep-alive 620"]
