from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any

import pytest

from agentic_rag.config import Settings
from agentic_rag.llm import (
    PRICES,
    AnthropicLLM,
    Completion,
    ConfigError,
    Effort,
    OpenAICompatibleLLM,
    Usage,
    cost,
    make_llm,
    price_of,
)
from agentic_rag.naive import naive_answer
from agentic_rag.workspace import Workspace


class FakeLLM:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[dict[str, Any]] = []

    def complete(
        self,
        *,
        model: str,
        system: str,
        messages: Sequence[dict[str, Any]],
        max_tokens: int = 16000,
        effort: Effort | None = None,
    ) -> Completion:
        self.calls.append({"model": model, "system": system, "messages": list(messages)})
        usage = Usage(input_tokens=1000, output_tokens=100, cost_usd=0.003, calls=1)
        return Completion(text=self.text, model=model, usage=usage, stop_reason="end_turn")


def test_cost_per_million_tokens() -> None:
    assert cost("claude-sonnet-5-5", 1_000_000, 1_000_000) == pytest.approx(12.0)
    assert cost("claude-haiku-5-5", 1_000_000, 0) == pytest.approx(0.10)
    assert cost("claude-sonnet-5-5", 0, 0, cache_read=1_000_000) == pytest.approx(0.20)
    assert cost("unknown-model", 10, 10) == 0.0


def test_usage_adds_up() -> None:
    total = Usage(input_tokens=1, cost_usd=0.5, calls=1) + Usage(
        output_tokens=2, cost_usd=0.25, calls=1
    )
    assert (total.input_tokens, total.output_tokens, total.cost_usd, total.calls) == (1, 2, 0.75, 2)


def test_naive_answer_builds_numbered_context_and_parses_citations(sample_ws: Workspace) -> None:
    llm = FakeLLM("normalize upper-cases the SKU [1]. Also [99] which does not exist.")
    answer = naive_answer(sample_ws, "What does normalize do?", llm, "claude-sonnet-5-5", k=3)

    prompt = llm.calls[0]["messages"][0]["content"]
    assert prompt.startswith("Question: What does normalize do?")
    assert "[1] " in prompt and "[3] " in prompt
    assert answer.cited == [1]  # out-of-range [99] dropped
    assert len(answer.sources) == 3
    assert answer.usage.cost_usd == 0.003
    rendered = answer.render()
    assert "Sources:" in rendered and "[1] " in rendered and "[2] " not in rendered


def _response(model: str) -> SimpleNamespace:
    return SimpleNamespace(
        content=[
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text="hi"),
        ],
        stop_reason="end_turn",
        model=model,
        usage=SimpleNamespace(
            input_tokens=200,
            output_tokens=50,
            cache_read_input_tokens=None,
            cache_creation_input_tokens=0,
        ),
    )


def test_anthropic_llm_routes_sonnet_through_server_fallback() -> None:
    seen: dict[str, Any] = {}

    def beta_create(**kwargs: Any) -> SimpleNamespace:
        seen["beta"] = kwargs
        return _response("claude-sonnet-5-5")

    def create(**kwargs: Any) -> SimpleNamespace:
        seen["plain"] = kwargs
        return _response("claude-haiku-5-5")

    client = SimpleNamespace(
        beta=SimpleNamespace(messages=SimpleNamespace(create=beta_create)),
        messages=SimpleNamespace(create=create),
    )
    llm = AnthropicLLM(client)  # type: ignore[arg-type]

    sonnet = llm.complete(model="claude-sonnet-5-5", system="s", messages=[], effort="medium")
    assert seen["beta"]["fallbacks"] == "default"
    assert seen["beta"]["betas"] == ["server-side-fallback-2026-07-01"]
    assert seen["beta"]["output_config"] == {"effort": "medium"}
    assert sonnet.text == "hi"
    assert sonnet.usage.cost_usd == pytest.approx(cost("claude-sonnet-5-5", 200, 50))

    llm.complete(model="claude-haiku-5-5", system="s", messages=[])
    assert "fallbacks" not in seen["plain"]


# ---- OpenAI-compatible adapter and provider selection -----------------------------------


def _chat_response(model: str, cached: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        model=model,
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="hello", refusal=None), finish_reason="stop"
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=1000,
            completion_tokens=200,
            prompt_tokens_details=SimpleNamespace(cached_tokens=cached),
        ),
    )


def test_openai_adapter_sends_system_effort_and_bills_cached_tokens() -> None:
    seen: dict[str, Any] = {}

    def create(**kwargs: Any) -> SimpleNamespace:
        seen.update(kwargs)
        return _chat_response("gpt-6.1-sol-2026-09-01", cached=400)  # dated snapshot id

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    llm = OpenAICompatibleLLM(client)  # type: ignore[arg-type]
    result = llm.complete(
        model="gpt-6.1-sol",
        system="be brief",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=500,
        effort="low",
    )
    assert seen["messages"][0] == {"role": "system", "content": "be brief"}
    assert seen["max_completion_tokens"] == 500
    assert seen["reasoning_effort"] == "low"
    assert result.text == "hello"
    assert (result.usage.input_tokens, result.usage.cache_read_tokens) == (600, 400)
    # 600 x $2 + 400 x $0.10 (cached) + 200 x $10, per million
    assert result.usage.cost_usd == pytest.approx((600 * 2 + 400 * 0.10 + 200 * 10) / 1e6)


def test_unknown_models_cost_zero_instead_of_a_guess() -> None:
    assert price_of("gpt-6-luna-2026-08-01") == PRICES["gpt-6-luna"]
    assert cost("llama3.2", 1000, 1000) == 0.0


def _settings(**env: Any) -> Settings:
    return Settings(_env_file=None, **env)


def test_provider_defaults_and_overrides() -> None:
    openai_settings = _settings()
    assert (openai_settings.cheap_model, openai_settings.heavy_model) == (
        "gpt-6-luna",
        "gpt-6.1-sol",
    )
    claude = _settings(provider="anthropic")
    assert claude.heavy_model == "claude-sonnet-5-5"
    assert _settings(model_heavy="gpt-5.4-mini").heavy_model == "gpt-5.4-mini"


def test_make_llm_picks_the_provider_and_explains_bad_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert isinstance(make_llm(_settings(OPENAI_API_KEY="sk-test")), OpenAICompatibleLLM)
    assert isinstance(
        make_llm(_settings(provider="anthropic", ANTHROPIC_API_KEY="sk-ant-test")), AnthropicLLM
    )
    # Ollama-style servers need no key.
    local = make_llm(_settings(openai_base_url="http://localhost:11434/v1"))
    assert isinstance(local, OpenAICompatibleLLM)

    with pytest.raises(ConfigError, match="rename it"):
        make_llm(_settings(ANTHROPIC_API_KEY="sk-proj-abc"))
    with pytest.raises(ConfigError, match="sk-ant-"):
        make_llm(_settings(provider="anthropic", ANTHROPIC_API_KEY="sk-proj-abc"))
