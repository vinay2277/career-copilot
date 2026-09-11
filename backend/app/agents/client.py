"""The single seam between the agents and whichever LLM provider is configured.

All seven agents call `structured_call` and nothing else, so supporting a second
provider is confined to this file. `LLM_PROVIDER` in the environment picks
between them.

What differs between the two, and how it is handled:

- **Effort.** Anthropic takes `output_config.effort` on every current model, and
  the agents tune it per task. OpenAI has no equivalent on general models;
  reasoning models accept `reasoning_effort`, which is opt-in via
  `OPENAI_REASONING_EFFORT` so it is never sent to a model that would reject it.
- **Prompt caching.** Anthropic needs an explicit `cache_control` breakpoint.
  OpenAI caches long prefixes automatically, so `cache_system` is a no-op there.
- **Errors.** The two SDKs raise parallel but unrelated exception types. Both
  are mapped onto `AgentError`, so every route handler has one thing to catch.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Literal, TypeVar

from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

Effort = Literal["low", "medium", "high", "xhigh", "max"]


class AgentError(RuntimeError):
    """An agent call failed in a way the caller should surface, not swallow."""


def _no_credentials_message() -> str:
    """Actionable text naming the variable to set for the active provider."""
    if settings.llm_provider == "anthropic":
        return (
            "No Anthropic credentials found, so the AI features are "
            "unavailable. Set ANTHROPIC_API_KEY in backend/.env and restart "
            "the server, or run `ant auth login`."
        )
    return (
        "No OpenAI credentials found, so the AI features are unavailable. "
        "Set OPENAI_API_KEY in backend/.env and restart the server."
    )


NO_CREDENTIALS_SUFFIX = (
    " Everything that doesn't call the model — scoring, the board, skill ROI, "
    "what-if and analytics — works without this."
)


def no_credentials() -> str:
    return _no_credentials_message() + NO_CREDENTIALS_SUFFIX


# --------------------------------------------------------------------------- #
# Clients
# --------------------------------------------------------------------------- #


@lru_cache
def get_openai_client():
    """The process-wide OpenAI client."""
    from openai import OpenAI

    if settings.openai_api_key:
        return OpenAI(api_key=settings.openai_api_key)
    return OpenAI()  # falls back to OPENAI_API_KEY in the environment


@lru_cache
def get_anthropic_client():
    """The process-wide Anthropic client.

    Passing no `api_key` lets the SDK resolve credentials itself — env var, or
    an `ant auth login` profile — so local dev needs no key in `.env`.
    """
    import anthropic

    if settings.anthropic_api_key:
        return anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return anthropic.Anthropic()


def credentials_available() -> bool:
    """Whether a model call could authenticate right now.

    The two SDKs fail at different points, so each needs its own probe:

    - OpenAI raises `OpenAIError` from the *constructor* when no key resolves.
    - Anthropic constructs happily and only raises — a bare `TypeError` — when
      it builds the request headers.

    Used by `/health` so the UI can warn before the user fills in a form and
    clicks. Anything that isn't recognizably a credentials failure reports
    available, leaving the real call to give the accurate error rather than
    mislabelling it here.
    """
    if settings.llm_provider == "anthropic":
        import anthropic

        try:
            get_anthropic_client()._validate_headers({}, {})
        except TypeError:
            return False
        except anthropic.AnthropicError:
            return False
        except Exception:
            return True
        return True

    import openai

    try:
        return bool(get_openai_client().api_key)
    except openai.OpenAIError:
        return False
    except Exception:
        return True


# --------------------------------------------------------------------------- #
# Provider implementations
# --------------------------------------------------------------------------- #


def _call_openai(
    *,
    system: str,
    user: str,
    output_model: type[T],
    max_tokens: int,
) -> T:
    import openai

    try:
        client = get_openai_client()
    except openai.OpenAIError as e:
        # The constructor is where a missing key surfaces, so it needs the same
        # guard as the request itself — otherwise this escapes as a 500.
        raise AgentError(no_credentials()) from e

    kwargs: dict[str, object] = {
        "model": settings.openai_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": output_model,
        "max_completion_tokens": max_tokens,
    }
    # Reasoning models take this; general models reject it. Opt-in only.
    if settings.openai_reasoning_effort:
        kwargs["reasoning_effort"] = settings.openai_reasoning_effort

    try:
        completion = client.chat.completions.parse(**kwargs)
    except openai.AuthenticationError as e:
        raise AgentError(no_credentials()) from e
    except openai.BadRequestError as e:
        raise AgentError(f"Malformed request to the model: {e}") from e
    except openai.PermissionDeniedError as e:
        raise AgentError(
            f"That API key cannot use '{settings.openai_model}'. Set "
            f"OPENAI_MODEL in backend/.env to a model your account has access "
            f"to. ({e})"
        ) from e
    except openai.NotFoundError as e:
        raise AgentError(
            f"Model '{settings.openai_model}' does not exist or is not "
            f"available to this account. Set OPENAI_MODEL in backend/.env. ({e})"
        ) from e
    except openai.RateLimitError as e:
        raise AgentError(f"Rate limited by OpenAI; retry shortly. ({e})") from e
    except openai.APIStatusError as e:
        raise AgentError(f"OpenAI error {e.status_code}: {e}") from e
    except openai.APIConnectionError as e:
        raise AgentError("Could not reach the OpenAI API.") from e
    except openai.OpenAIError as e:
        # Catch-all so an SDK failure can never surface as a 500.
        raise AgentError(f"OpenAI client error: {e}") from e

    choice = completion.choices[0]

    if choice.message.refusal:
        raise AgentError(f"The model declined this request: {choice.message.refusal}")

    if choice.finish_reason == "length":
        raise AgentError(
            "The model hit the output limit before finishing. Retry, or raise "
            "max_tokens for this agent."
        )

    usage = completion.usage
    if usage is not None:
        cached = getattr(
            getattr(usage, "prompt_tokens_details", None), "cached_tokens", None
        )
        logger.info(
            "agent call provider=openai model=%s in=%s cached=%s out=%s",
            settings.openai_model,
            usage.prompt_tokens,
            cached,
            usage.completion_tokens,
        )

    if choice.message.parsed is None:
        raise AgentError("The model returned no parseable structured output.")

    return choice.message.parsed


def _call_anthropic(
    *,
    system: str,
    user: str | list[dict],
    output_model: type[T],
    effort: Effort,
    max_tokens: int,
    cache_system: bool,
) -> T:
    import anthropic

    try:
        client = get_anthropic_client()
    except anthropic.AnthropicError as e:
        raise AgentError(no_credentials()) from e

    messages = [{"role": "user", "content": user}]

    system_blocks: list[dict] = [{"type": "text", "text": system}]
    if cache_system:
        system_blocks[0]["cache_control"] = {"type": "ephemeral"}

    try:
        response = client.messages.parse(
            model=settings.anthropic_model,
            max_tokens=max_tokens,
            system=system_blocks,
            messages=messages,
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            output_format=output_model,
        )
    except anthropic.AuthenticationError as e:
        raise AgentError(no_credentials()) from e
    except anthropic.BadRequestError as e:
        raise AgentError(f"Malformed request to the model: {e.message}") from e
    except anthropic.NotFoundError as e:
        raise AgentError(
            f"Model '{settings.anthropic_model}' is not available to this "
            f"account. Set ANTHROPIC_MODEL in backend/.env. ({e})"
        ) from e
    except anthropic.RateLimitError as e:
        retry_after = e.response.headers.get("retry-after", "60")
        raise AgentError(
            f"Rate limited by the model API; retry in {retry_after}s."
        ) from e
    except anthropic.APIStatusError as e:
        raise AgentError(f"Model API error {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise AgentError("Could not reach the model API.") from e
    except TypeError as e:
        # The SDK raises a bare TypeError from _validate_headers when no
        # credential source resolves — not an AnthropicError, so it would
        # otherwise escape this handler as an opaque 500.
        if "authentication method" in str(e):
            raise AgentError(no_credentials()) from e
        raise
    except anthropic.AnthropicError as e:
        raise AgentError(f"Model client error: {e}") from e

    if response.stop_reason == "refusal":
        detail = (
            getattr(response.stop_details, "explanation", None) or "no detail given"
        )
        raise AgentError(f"The model declined this request: {detail}")

    usage = response.usage
    logger.info(
        "agent call provider=anthropic model=%s effort=%s in=%s cached=%s out=%s",
        settings.anthropic_model,
        effort,
        usage.input_tokens,
        usage.cache_read_input_tokens,
        usage.output_tokens,
    )

    if response.parsed_output is None:
        raise AgentError("The model returned no parseable structured output.")

    return response.parsed_output


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #


def structured_call(
    *,
    system: str,
    user: str | list[dict],
    output_model: type[T],
    effort: Effort = "high",
    max_tokens: int = 16000,
    cache_system: bool = True,
) -> T:
    """Call the configured provider and get back a validated `output_model`.

    `system` is cached where the provider supports an explicit breakpoint: agent
    system prompts are long, static, and hit on every request, which is exactly
    the shape prompt caching pays for. The volatile part — the job text, the
    profile — goes in `user`, after that breakpoint.

    `effort` applies to Anthropic only; see the module docstring.

    Raises `AgentError` on refusal, on missing credentials, and on any API
    failure, so route handlers turn one exception type into one HTTP status.
    """
    if settings.llm_provider == "anthropic":
        return _call_anthropic(
            system=system,
            user=user,
            output_model=output_model,
            effort=effort,
            max_tokens=max_tokens,
            cache_system=cache_system,
        )

    if not isinstance(user, str):
        # Only the Anthropic path takes content blocks today. Failing loudly
        # beats silently sending a stringified list as the prompt.
        raise AgentError(
            "The OpenAI path takes a plain string prompt; got content blocks."
        )

    return _call_openai(
        system=system,
        user=user,
        output_model=output_model,
        max_tokens=max_tokens,
    )
