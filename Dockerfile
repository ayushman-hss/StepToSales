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
# Exactly the versions in the lockfile, and no package's install scripts:
# the build needs none (Vite and Tailwind ship prebuilt native binaries).
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- 2. the API, serving the built website -----------------------------------------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    STATIC_DIR=/app/frontend/dist
WORKDIR /app/backend
# requirements.lock pins every package, dependencies included, with hashes;
# wheels only, so no package runs setup code while installing.
COPY backend/requirements.lock ./
RUN pip install --require-hashes --only-binary :all: -r requirements.lock
# Run as an ordinary user. It owns backend/ because the first boot writes the
# generated demo spreadsheets there.
RUN useradd --create-home --uid 10001 app && chown app:app /app/backend
COPY --chown=app:app backend/ ./
COPY --from=web /web/dist /app/frontend/dist
USER app
EXPOSE 8000
CMD ["sh", "scripts/start.sh"]
