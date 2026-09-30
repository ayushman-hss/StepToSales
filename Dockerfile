# One image for the whole app: the API serves the website too.
#
#   docker build -t steptosales .
#   docker run -p 8000:8000 -e DATABASE_URL=postgresql://user:pass@host/db steptosales
#
# On start it loads the demo data into an empty database (once), or applies
# migrations to an existing one, then runs a single API process -- the live
# simulator and the Telegram bot must run in exactly one.

# ---- 1. build the website -------------------------------------------------------
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- 2. the API, serving the built website -----------------------------------------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    STATIC_DIR=/app/frontend/dist
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt
COPY backend/ ./
COPY --from=web /web/dist /app/frontend/dist
EXPOSE 8000
CMD ["sh", "scripts/start.sh"]
