from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any

import pytest

from agentic_rag.llm import AnthropicLLM, Completion, Effort, Usage, cost
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
