"""Model access behind a small interface, with token and cost accounting on every call."""

from collections.abc import Sequence
from typing import Any, Literal, Protocol

import anthropic
from pydantic import BaseModel

Effort = Literal["low", "medium", "high", "xhigh", "max"]

# USD per million tokens: (input, output). Cache reads bill at 10% of input, writes at 125%.
# Haiku 5.5's rate doubles past 100K-token prompts; prompts here stay far below that.
# Older entries cover models a server-side fallback may route to.
PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-haiku-4-5": (1.00, 5.00),
}
# Models that accept the server-side refusal fallback (`fallbacks: "default"`).
_SERVER_FALLBACK = frozenset({"claude-sonnet-5-5", "claude-opus-5-5"})


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    calls: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
            cost_usd=self.cost_usd + other.cost_usd,
            calls=self.calls + other.calls,
        )


def cost(model: str, inp: int, out: int, cache_read: int = 0, cache_write: int = 0) -> float:
    price_in, price_out = PRICES.get(model, (0.0, 0.0))
    return (
        inp * price_in
        + out * price_out
        + cache_read * price_in * 0.1
        + cache_write * price_in * 1.25
    ) / 1_000_000


class Completion(BaseModel):
    text: str
    model: str
    usage: Usage
    stop_reason: str | None = None


class LLM(Protocol):
    def complete(
        self,
        *,
        model: str,
        system: str,
        messages: Sequence[dict[str, Any]],
        max_tokens: int = 16000,
        effort: Effort | None = None,
    ) -> Completion: ...


class AnthropicLLM:
    def __init__(self, client: anthropic.Anthropic | None = None) -> None:
        self.client = client or anthropic.Anthropic()

    def complete(
        self,
        *,
        model: str,
        system: str,
        messages: Sequence[dict[str, Any]],
        max_tokens: int = 16000,
        effort: Effort | None = None,
    ) -> Completion:
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": list(messages),
        }
        if effort:
            kwargs["output_config"] = {"effort": effort}
        if model in _SERVER_FALLBACK:
            # On a policy decline the API re-runs the request on a fallback model in the same call.
            response: Any = self.client.beta.messages.create(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
            )
        else:
            response = self.client.messages.create(**kwargs)

        text = "".join(block.text for block in response.content if block.type == "text")
        if response.stop_reason == "refusal" and not text:
            text = "[The model declined to answer this question.]"
        u = response.usage
        cache_read = u.cache_read_input_tokens or 0
        cache_write = u.cache_creation_input_tokens or 0
        served_by = str(response.model)
        return Completion(
            text=text,
            model=served_by,
            stop_reason=response.stop_reason,
            usage=Usage(
                input_tokens=u.input_tokens,
                output_tokens=u.output_tokens,
                cache_read_tokens=cache_read,
                cache_write_tokens=cache_write,
                cost_usd=cost(served_by, u.input_tokens, u.output_tokens, cache_read, cache_write),
                calls=1,
            ),
        )
