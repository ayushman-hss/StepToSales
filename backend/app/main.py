from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import init_db
from .alerts import alerts
from .live import runner
from .routers import alerts as alerts_router, assistant, auth, dashboard, live, products, bundles, pools

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Local convenience. In prod, run `alembic upgrade head` in your deploy step.
    init_db()
    if settings.live_simulator:
        runner.start()
    if settings.alerts_enabled:
        alerts.start()
    yield
    await alerts.stop()
    await runner.stop()


app = FastAPI(title="Footfall Dashboard API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    """For the host's health check and any keep-awake ping."""
    return {"status": "ok"}


STATIC = Path(settings.static_dir) if settings.static_dir else None
if STATIC is None or not (STATIC / "index.html").is_file():
    @app.get("/")
    def root():
        return {"status": "ok", "docs": "/docs"}

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(live.router)
app.include_router(alerts_router.router)
app.include_router(assistant.router)
app.include_router(products.router)
app.include_router(bundles.router)
app.include_router(pools.router)


# ---- the website, when this process serves it too -------------------------------
#: The build's /assets files have a content hash in their names, so a browser
#: may keep them forever. Everything else -- index.html above all -- must be
#: checked on every visit, or a browser keeps showing the old app after a
#: deploy (index.html had no cache header, and browsers guessed a lifetime).
IMMUTABLE = "public, max-age=31536000, immutable"
REVALIDATE = "no-cache"


class HashedAssets(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = IMMUTABLE
        return response


if STATIC is not None and (STATIC / "index.html").is_file():
    app.mount("/assets", HashedAssets(directory=STATIC / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def website(path: str):
        """Files from the build as they are; every other path is a page of the
        single-page app (/dashboard, /pos, ...), so it gets index.html."""
        if path.startswith("api/"):
            raise HTTPException(404, "Not found")
        file = (STATIC / path).resolve()
        if path and file.is_file() and STATIC.resolve() in file.parents:
            return FileResponse(file, headers={"Cache-Control": REVALIDATE})
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": REVALIDATE})
