"""Application settings, loaded from the environment."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- LLM ---
    # Left empty when the process authenticates via an `ant auth login` profile;
    # the Anthropic SDK resolves credentials itself in that case.
    anthropic_api_key: str = ""

    # Every agent runs on the same model. Effort is tuned per agent instead,
    # so one cache namespace covers the whole app.
    llm_model: str = "claude-opus-5"

    # --- Database ---
    database_url: str = "sqlite:///./career_copilot.db"

    # --- Server ---
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:5173"

    # --- Ingestion ---
    tesseract_cmd: str = ""
    max_upload_mb: int = 15

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
