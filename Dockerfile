# syntax=docker/dockerfile:1

# ---- Stage 1: build the dashboard's React SPA ------------------------------
# A separate stage so the final image never needs Node at all, just the
# built static output `dashboard/app.py` already expects to find at
# dashboard-frontend/dist (see FRONTEND_DIST in that file).
FROM node:22-slim AS frontend-build
WORKDIR /app/dashboard-frontend
COPY dashboard-frontend/package.json dashboard-frontend/package-lock.json ./
RUN npm ci
COPY dashboard-frontend/ ./
RUN npm run build

# ---- Stage 2: the bot + dashboard runtime ----------------------------------
# One image, two entrypoints (see CMD below and docker-compose.yml): the
# bot and dashboard processes share the exact same requirements.txt and
# common/ data layer already, there's nothing a second image would buy
# beyond a bit of layer duplication.
FROM python:3.11-slim AS runtime
WORKDIR /app

RUN useradd --create-home --uid 1000 appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appuser bot/ ./bot/
COPY --chown=appuser:appuser common/ ./common/
COPY --chown=appuser:appuser dashboard/ ./dashboard/
COPY --chown=appuser:appuser schema.sql run_bot.py run_dashboard.py ./
COPY --chown=appuser:appuser --from=frontend-build /app/dashboard-frontend/dist ./dashboard-frontend/dist

USER appuser

# Runs as the bot by default; docker-compose.yml overrides this command
# for the dashboard service.
CMD ["python", "run_bot.py"]
