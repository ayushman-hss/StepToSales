from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import init_db
from .routers import dashboard, products, bundles, pools
from .routers import auth, dashboard, products, bundles, pools

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Local convenience. In prod, run `alembic upgrade head` in your deploy step.
    init_db()
    yield


app = FastAPI(title="Footfall Dashboard API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"status": "ok", "docs": "/docs"}

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(dashboard.router)
app.include_router(products.router)
app.include_router(bundles.router)
app.include_router(pools.router)