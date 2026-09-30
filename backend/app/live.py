"""The one live-mode runner for this API process."""
from .config import settings
from .db import engine
from .services.live.runner import LiveRunner

runner = LiveRunner(engine, seed=settings.live_seed)
