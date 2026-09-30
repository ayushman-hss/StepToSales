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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
