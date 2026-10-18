FROM node:22-alpine AS frontend
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.12.13 AS uv
FROM python:3.12-slim
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH"
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src/ ./src/
COPY migrations/ ./migrations/
COPY alembic.ini ./
COPY scripts/import_history.py scripts/import_community_ratings.py ./scripts/
COPY data/historical_import_corrections.json data/historical_import_2024_2025.json data/community_rating_aliases.json ./data/
COPY --from=frontend /frontend/dist ./frontend/dist
RUN uv sync --frozen --no-dev && useradd --create-home app && chown -R app:app /app
ENV UV_NO_SYNC=1
USER app
EXPOSE 8000
CMD ["/app/.venv/bin/fczhk", "serve"]
