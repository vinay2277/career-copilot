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
    # Legacy single shared password, superseded by real accounts. Read but
    # never used: it stays declared only so an existing deployment that still
    # sets APP_PASSWORD starts rather than failing on an unexpected variable.
    app_password: str = ""

    # Whether an organization must be verified before it can post roles or view
    # candidates. False is for a pilot where you know every recruiter; anywhere
    # public it should be true, or anyone can post a fake role and harvest
    # student contact details.
    require_org_verification: bool = True

    # A hosted deployment often has no shell, and the multi-tenancy migration
    # adopts a pre-existing profile onto an account with no usable password.
    # Setting both of these at startup makes that account signable-in without
    # one. Clear them once you are in — while set, the password is reapplied on
    # every restart, so a change made in the app reverts at the next deploy.
    bootstrap_admin_email: str = ""
    bootstrap_admin_password: str = ""
    # Role given to an account the bootstrap *creates*. Defaults to student so
    # an existing deployment's behaviour does not change underneath it. Set to
    # "admin" with a fresh email address to make yourself an administrator who
    # can approve organizations; an account that already exists keeps whatever
    # role it has, so this can never silently promote or demote anyone.
    bootstrap_admin_role: str = "student"
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
    # Password guessing. Keyed by IP rather than by account — keying it by
    # account would let an attacker register and reset their own budget.
    rate_limit_login_per_hour: int = 10

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
