from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://footfall:footfall@localhost:5432/footfall"

    #: Keep every shop trading in the background (see services/live). Turn off
    #: with LIVE_SIMULATOR=false; run it in one API process only.
    live_simulator: bool = True
    #: Seeds the simulator, so a demo run can be replayed exactly.
    live_seed: str = "steptosales"
    #: Comma-separated browser origins allowed to call the API directly. Not
    #: needed when the frontend is served from the same host or via the Vite
    #: proxy; needed for a separately hosted frontend.
    cors_origins: str = "http://localhost:5173"
    #: Watch every shop's day and raise alerts (shown on the Phone alerts
    #: page). Like the simulator, run it in one API process only.
    alerts_enabled: bool = True
    #: From @BotFather. Empty: alerts are still recorded, just not sent.
    telegram_bot_token: str = ""
    #: Only for a self-hosted Bot API server; leave as is otherwise.
    telegram_api_url: str = "https://api.telegram.org"

    #: Where the built frontend lives (frontend/dist). When set, the API also
    #: serves the website, so one service is the whole app. Empty in development,
    #: where Vite serves the frontend.
    static_dir: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("database_url")
    @classmethod
    def _psycopg(cls, url: str) -> str:
        """Hosts hand out postgres://... or postgresql://...; SQLAlchemy needs
        to be told to use the psycopg 3 driver this project installs."""
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url

settings = Settings()
