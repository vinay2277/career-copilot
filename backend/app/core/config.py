"""Application settings, loaded from the environment."""

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
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
    # Managed Postgres providers (Render, Railway, Heroku, Fly) all hand out a
    # `postgres://` URL, which SQLAlchemy 2 rejects outright — it wants an
    # explicit driver. Normalized below rather than left as a manual step,
    # because the failure is a startup crash with an opaque dialect error and
    # it would catch every single person deploying this.
    database_url: str = "sqlite:///./career_copilot.db"

    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+psycopg://", 1)
        # `postgresql://` alone resolves to psycopg2, which isn't installed;
        # pin it to psycopg 3, which is.
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value

    # --- Server ---
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:5173"

    # --- Access control ---
    # Empty disables the gate entirely, which is what makes local development
    # frictionless. Set it for anything reachable from outside your machine:
    # without it, whoever has the URL can read the résumé and spend the API key.
    # Legacy single-user gate. Superseded by real accounts and kept only so an
    # existing deployment doesn't break on upgrade; unused once accounts exist.
    app_password: str = ""

    # Whether an organization must be verified before it can post roles or view
    # candidates. False is for a pilot where you know every recruiter; anywhere
    # public it should be true, or anyone can post a fake role and harvest
    # student contact details.
    require_org_verification: bool = True
    # Signs the session cookie. Must be stable across restarts or everyone is
    # logged out on every deploy; must be secret or the cookie is forgeable.
    secret_key: str = ""
    session_days: int = 30
    # Send the cookie only over HTTPS. Leave false for plain-http localhost,
    # true anywhere real.
    cookie_secure: bool = False

    # --- Rate limits (per client, per window) ---
    # The AI endpoints spend money on every call, so they get their own much
    # tighter budget than ordinary reads.
    rate_limit_ai_per_hour: int = 40
    rate_limit_api_per_minute: int = 120
    # Brute-forcing one shared password is the obvious attack on this design.
    rate_limit_login_per_hour: int = 10

    @property
    def auth_enabled(self) -> bool:
        return bool(self.app_password)

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
