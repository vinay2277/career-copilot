"""Application settings, loaded from the environment."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- LLM ---
    # Which provider the agents talk to: "openai" or "anthropic". Every agent
    # goes through one function, so this is the only switch needed.
    llm_provider: Literal["openai", "anthropic"] = "openai"

    # --- OpenAI ---
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    # Hard ceiling on completion tokens, applied to every request. Agents ask
    # for what their task needs; some ask for more than a given model allows,
    # and exceeding it is a 400 rather than a truncation. gpt-4o's limit is
    # 16384. Raise this for a model that supports more.
    openai_max_output_tokens: int = 16384
    # Only reasoning models (o-series and later) accept a reasoning effort.
    # Left unset so it is never sent to a model that would reject it.
    openai_reasoning_effort: str = ""

    # --- Anthropic ---
    # Left empty when the process authenticates via an `ant auth login` profile;
    # the Anthropic SDK resolves credentials itself in that case.
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5"

    @property
    def llm_model(self) -> str:
        """The model the active provider will use."""
        if self.llm_provider == "anthropic":
            return self.anthropic_model
        return self.openai_model

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
