FROM node:22-alpine AS ui
WORKDIR /ui
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
RUN pip install --no-cache-dir uv
WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/app/.venv PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev
COPY backend/ ./
RUN uv sync --frozen --no-dev
COPY --from=ui /ui/dist /app/static
# API: uvicorn concierge.api:app   Worker: python -m concierge.worker   (see compose.yaml)
