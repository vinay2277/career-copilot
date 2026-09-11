"""Shared Anthropic client and the structured-output helper every agent uses.

One client, one model, effort tuned per agent. Keeping the model fixed means a
single prompt-cache namespace for the whole app; `effort` is the knob for
trading cost against depth, which is cheaper than juggling model tiers.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Literal, TypeVar

import anthropic
from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

Effort = Literal["low", "medium", "high", "xhigh", "max"]


class AgentError(RuntimeError):
    """An agent call failed in a way the caller should surface, not swallow."""


#: Shown whenever credentials cannot be resolved. The SDK's own message is
#: accurate but says nothing about where to put a key in *this* project.
NO_CREDENTIALS = (
    "No Anthropic credentials found, so the AI features are unavailable. "
    "Set ANTHROPIC_API_KEY in backend/.env and restart the server, or run "
    "`ant auth login`. Everything that doesn't call the model — scoring, the "
    "board, skill ROI, what-if and analytics — works without this."
)


@lru_cache
def get_client() -> anthropic.Anthropic:
    """The process-wide Anthropic client.

    Passing no `api_key` lets the SDK resolve credentials itself — env var, or an
    `ant auth login` profile — so local dev needs no key in `.env`.
    """
    if settings.anthropic_api_key:
        return anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return anthropic.Anthropic()


def credentials_available() -> bool:
    """Whether a model call could authenticate right now.

    Construction succeeds with no credentials — the SDK only resolves them when
    a request is built — so this probes the resolution path directly rather than
    trusting a successful `Anthropic()`. Used by `/health` so the UI can warn
    before the user fills in a form and clicks.
    """
    try:
        get_client()._validate_headers({}, {})
    except TypeError:
        return False
    except Exception:
        # Any other failure is not a credentials problem; let the real call
        # report it rather than mislabelling it here.
        return True
    return True


def structured_call(
    *,
    system: str,
    user: str | list[dict],
    output_model: type[T],
    effort: Effort = "high",
    max_tokens: int = 16000,
    cache_system: bool = True,
) -> T:
    """Call Claude and get back a validated instance of `output_model`.

    `system` is cached by default: agent system prompts are long, static, and
    hit on every request, which is exactly the shape prompt caching pays for.
    The volatile part (the job text, the profile) goes in `user`, after the
    cache breakpoint.

    Raises `AgentError` on refusal or on any API failure, so route handlers can
    turn one exception type into one HTTP status.
    """
    client = get_client()
    # `user` is either a plain string or a list of content blocks; the API
    # accepts both shapes for `content` as-is.
    messages = [{"role": "user", "content": user}]

    system_blocks: list[dict] = [{"type": "text", "text": system}]
    if cache_system:
        system_blocks[0]["cache_control"] = {"type": "ephemeral"}

    try:
        response = client.messages.parse(
            model=settings.llm_model,
            max_tokens=max_tokens,
            system=system_blocks,
            messages=messages,
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            output_format=output_model,
        )
    except anthropic.BadRequestError as e:
        raise AgentError(f"Malformed request to the model: {e.message}") from e
    except anthropic.AuthenticationError as e:
        raise AgentError(
            "Anthropic credentials missing or invalid. Set ANTHROPIC_API_KEY "
            "or run `ant auth login`."
        ) from e
    except anthropic.RateLimitError as e:
        retry_after = e.response.headers.get("retry-after", "60")
        raise AgentError(f"Rate limited by the model API; retry in {retry_after}s.") from e
    except anthropic.APIStatusError as e:
        raise AgentError(f"Model API error {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise AgentError("Could not reach the model API.") from e
    except TypeError as e:
        # The SDK raises a bare TypeError from _validate_headers when no
        # credential source resolves — not an AnthropicError, so it would
        # otherwise escape this handler as an opaque 500.
        if "authentication method" in str(e):
            raise AgentError(NO_CREDENTIALS) from e
        raise
    except anthropic.AnthropicError as e:
        # Catch-all for SDK errors that aren't APIStatusError subclasses, so an
        # agent failure is always an AgentError and never a 500.
        raise AgentError(f"Model client error: {e}") from e

    if response.stop_reason == "refusal":
        detail = getattr(response.stop_details, "explanation", None) or "no detail given"
        raise AgentError(f"The model declined this request: {detail}")

    usage = response.usage
    logger.info(
        "agent call model=%s effort=%s in=%s cached=%s out=%s",
        settings.llm_model,
        effort,
        usage.input_tokens,
        usage.cache_read_input_tokens,
        usage.output_tokens,
    )

    if response.parsed_output is None:
        raise AgentError("The model returned no parseable structured output.")

    return response.parsed_output
