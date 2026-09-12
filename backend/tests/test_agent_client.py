"""Tests for the provider seam.

No network and no credentials: the SDK call is stubbed out, and what's under
test is the dispatch, the credential probe, and the error mapping — the parts
that decide whether a failure reaches the user as a usable message or as a 500.
"""

from __future__ import annotations

from types import SimpleNamespace

import openai
import pytest
from pydantic import BaseModel

from app.agents import client as agent_client
from app.agents.client import AgentError, structured_call
from app.core.config import settings


class Reply(BaseModel):
    answer: str


@pytest.fixture(autouse=True)
def reset_clients():
    """Clear the cached clients so each test sees fresh settings."""
    agent_client.get_openai_client.cache_clear()
    agent_client.get_anthropic_client.cache_clear()
    yield
    agent_client.get_openai_client.cache_clear()
    agent_client.get_anthropic_client.cache_clear()


def openai_completion(
    *,
    parsed: Reply | None = Reply(answer="ok"),
    refusal: str | None = None,
    finish_reason: str = "stop",
):
    """The shape `chat.completions.parse` returns."""
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(parsed=parsed, refusal=refusal),
                finish_reason=finish_reason,
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=100,
            completion_tokens=20,
            prompt_tokens_details=SimpleNamespace(cached_tokens=64),
        ),
    )


def stub_openai(monkeypatch, result=None, raises: Exception | None = None):
    """Point the OpenAI path at a stub and record what it was called with."""
    seen: dict[str, object] = {}

    def fake_parse(**kwargs):
        seen.update(kwargs)
        if raises is not None:
            raise raises
        return result if result is not None else openai_completion()

    monkeypatch.setattr(
        agent_client,
        "get_openai_client",
        lambda: SimpleNamespace(
            api_key="sk-test",
            chat=SimpleNamespace(completions=SimpleNamespace(parse=fake_parse)),
        ),
    )
    return seen


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #


def test_openai_is_the_default_provider():
    assert settings.llm_provider == "openai"


def test_openai_path_sends_system_and_user_separately(monkeypatch):
    seen = stub_openai(monkeypatch)
    result = structured_call(
        system="You are a transcriber.", user="Extract this.", output_model=Reply
    )

    assert result.answer == "ok"
    assert [m["role"] for m in seen["messages"]] == ["system", "user"]
    assert seen["messages"][0]["content"] == "You are a transcriber."
    assert seen["response_format"] is Reply


def test_openai_path_does_not_send_anthropic_only_params(monkeypatch):
    """`effort`, thinking and cache_control would all be 400s on OpenAI."""
    seen = stub_openai(monkeypatch)
    structured_call(system="s", user="u", output_model=Reply, effort="xhigh")

    assert "output_config" not in seen
    assert "thinking" not in seen
    assert "reasoning_effort" not in seen  # unset by default


def test_max_tokens_is_clamped_to_the_model_ceiling(monkeypatch):
    """Regression: an agent asking for 32000 was a hard 400 on gpt-4o.

    Anthropic's current models take 128K output tokens, gpt-4o takes 16384.
    Exceeding the limit is rejected outright rather than truncated, so the
    agents' own figures have to be capped on the way out.
    """
    monkeypatch.setattr(settings, "openai_max_output_tokens", 16384)
    seen = stub_openai(monkeypatch)
    structured_call(system="s", user="u", output_model=Reply, max_tokens=32000)
    assert seen["max_completion_tokens"] == 16384


def test_a_request_under_the_ceiling_is_left_alone(monkeypatch):
    monkeypatch.setattr(settings, "openai_max_output_tokens", 16384)
    seen = stub_openai(monkeypatch)
    structured_call(system="s", user="u", output_model=Reply, max_tokens=4000)
    assert seen["max_completion_tokens"] == 4000


def test_the_ceiling_is_configurable(monkeypatch):
    """A model that supports more output should be able to use it."""
    monkeypatch.setattr(settings, "openai_max_output_tokens", 100_000)
    seen = stub_openai(monkeypatch)
    structured_call(system="s", user="u", output_model=Reply, max_tokens=32000)
    assert seen["max_completion_tokens"] == 32000


def test_reasoning_effort_is_opt_in(monkeypatch):
    monkeypatch.setattr(settings, "openai_reasoning_effort", "high")
    seen = stub_openai(monkeypatch)
    structured_call(system="s", user="u", output_model=Reply)
    assert seen["reasoning_effort"] == "high"


def test_openai_path_rejects_content_blocks(monkeypatch):
    """Only the Anthropic path takes blocks; silently stringifying would be worse."""
    stub_openai(monkeypatch)
    with pytest.raises(AgentError, match="plain string prompt"):
        structured_call(
            system="s",
            user=[{"type": "text", "text": "hello"}],
            output_model=Reply,
        )


def test_model_property_follows_the_provider(monkeypatch):
    monkeypatch.setattr(settings, "openai_model", "gpt-4o-mini")
    monkeypatch.setattr(settings, "anthropic_model", "claude-opus-5")

    monkeypatch.setattr(settings, "llm_provider", "openai")
    assert settings.llm_model == "gpt-4o-mini"

    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    assert settings.llm_model == "claude-opus-5"


# --------------------------------------------------------------------------- #
# Credentials
# --------------------------------------------------------------------------- #


def test_missing_openai_key_is_reported_as_unavailable(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(
        agent_client, "get_openai_client", lambda: SimpleNamespace(api_key=None)
    )
    assert agent_client.credentials_available() is False


def test_present_openai_key_is_reported_as_available(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(
        agent_client, "get_openai_client", lambda: SimpleNamespace(api_key="sk-test")
    )
    assert agent_client.credentials_available() is True


def test_credential_message_names_the_right_variable(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "openai")
    assert "OPENAI_API_KEY" in agent_client.no_credentials()
    assert "ANTHROPIC_API_KEY" not in agent_client.no_credentials()

    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    assert "ANTHROPIC_API_KEY" in agent_client.no_credentials()


def test_credential_message_says_what_still_works(monkeypatch):
    """The scoring engine needs no model; the message must say so."""
    monkeypatch.setattr(settings, "llm_provider", "openai")
    assert "skill ROI" in agent_client.no_credentials()


# --------------------------------------------------------------------------- #
# Regression: the OpenAI SDK raises from the *constructor* when no key
# resolves, not from the request. A probe that only inspected the built client,
# and a broad `except Exception: return True`, together reported credentials as
# available when there were none — and the unguarded constructor call in
# _call_openai then surfaced as a 500 instead of a usable message.
# --------------------------------------------------------------------------- #


def raise_missing_key():
    raise openai.OpenAIError(
        "Missing credentials. Please pass an `api_key`, or set the "
        "`OPENAI_API_KEY` environment variable."
    )


def test_constructor_failure_reports_unavailable(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(agent_client, "get_openai_client", raise_missing_key)
    assert agent_client.credentials_available() is False


def test_constructor_failure_becomes_the_credentials_message(monkeypatch):
    """Must not escape as a 500 — this is the bug the user hit."""
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(agent_client, "get_openai_client", raise_missing_key)

    with pytest.raises(AgentError, match="OPENAI_API_KEY"):
        structured_call(system="s", user="u", output_model=Reply)


def test_anthropic_constructor_failure_is_also_guarded(monkeypatch):
    import anthropic

    def raise_anthropic():
        raise anthropic.AnthropicError("could not resolve credentials")

    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setattr(agent_client, "get_anthropic_client", raise_anthropic)

    assert agent_client.credentials_available() is False
    with pytest.raises(AgentError, match="ANTHROPIC_API_KEY"):
        structured_call(system="s", user="u", output_model=Reply)


# --------------------------------------------------------------------------- #
# Error mapping — nothing here may escape as a non-AgentError
# --------------------------------------------------------------------------- #


def api_error(cls, status: int):
    """Build an OpenAI APIStatusError subclass without a real HTTP round-trip."""
    return cls(
        message="boom",
        response=SimpleNamespace(status_code=status, headers={}, request=None),
        body=None,
    )


def test_auth_error_becomes_the_credentials_message(monkeypatch):
    stub_openai(monkeypatch, raises=api_error(openai.AuthenticationError, 401))
    with pytest.raises(AgentError, match="OPENAI_API_KEY"):
        structured_call(system="s", user="u", output_model=Reply)


def test_unavailable_model_names_the_setting(monkeypatch):
    monkeypatch.setattr(settings, "openai_model", "gpt-nonexistent")
    stub_openai(monkeypatch, raises=api_error(openai.NotFoundError, 404))
    with pytest.raises(AgentError, match="OPENAI_MODEL"):
        structured_call(system="s", user="u", output_model=Reply)


def test_permission_denied_names_the_setting(monkeypatch):
    stub_openai(monkeypatch, raises=api_error(openai.PermissionDeniedError, 403))
    with pytest.raises(AgentError, match="OPENAI_MODEL"):
        structured_call(system="s", user="u", output_model=Reply)


def test_rate_limit_becomes_an_agent_error(monkeypatch):
    stub_openai(monkeypatch, raises=api_error(openai.RateLimitError, 429))
    with pytest.raises(AgentError, match="Rate limited"):
        structured_call(system="s", user="u", output_model=Reply)


def test_connection_error_becomes_an_agent_error(monkeypatch):
    stub_openai(
        monkeypatch, raises=openai.APIConnectionError(request=None)  # type: ignore[arg-type]
    )
    with pytest.raises(AgentError, match="Could not reach"):
        structured_call(system="s", user="u", output_model=Reply)


def test_unexpected_sdk_error_still_becomes_an_agent_error(monkeypatch):
    """The catch-all: an SDK failure must never reach the route as a 500."""
    stub_openai(monkeypatch, raises=openai.OpenAIError("something new"))
    with pytest.raises(AgentError, match="OpenAI client error"):
        structured_call(system="s", user="u", output_model=Reply)


# --------------------------------------------------------------------------- #
# Response handling
# --------------------------------------------------------------------------- #


def test_refusal_is_surfaced(monkeypatch):
    stub_openai(
        monkeypatch,
        result=openai_completion(parsed=None, refusal="I can't help with that."),
    )
    with pytest.raises(AgentError, match="declined this request"):
        structured_call(system="s", user="u", output_model=Reply)


def test_truncated_output_is_not_returned_as_success(monkeypatch):
    """finish_reason 'length' means a half-built object; reject it."""
    stub_openai(monkeypatch, result=openai_completion(finish_reason="length"))
    with pytest.raises(AgentError, match="output limit"):
        structured_call(system="s", user="u", output_model=Reply)


def test_missing_parsed_output_is_an_error(monkeypatch):
    stub_openai(monkeypatch, result=openai_completion(parsed=None))
    with pytest.raises(AgentError, match="no parseable structured output"):
        structured_call(system="s", user="u", output_model=Reply)
