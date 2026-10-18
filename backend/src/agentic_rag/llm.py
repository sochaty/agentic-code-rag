"""Model access behind a small interface, with token and cost accounting on every call.

Two adapters:
- OpenAICompatibleLLM: OpenAI, plus anything speaking the Chat Completions API (Ollama,
  OpenRouter, OmniRoute, ...) via a custom base URL.
- AnthropicLLM: Claude.

The agent never calls a provider SDK directly, and it calls tools itself (the graph decides),
so it only needs plain or JSON completions — which every provider supports.
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Literal, NamedTuple, Protocol

from pydantic import BaseModel

if TYPE_CHECKING:
    import anthropic
    import openai

    from agentic_rag.config import Settings

Effort = Literal["low", "medium", "high", "xhigh", "max"]


class Price(NamedTuple):
    """USD per million tokens."""

    input: float
    output: float
    cache_read: float
    cache_write: float = 0.0


def _anthropic(inp: float, out: float) -> Price:
    return Price(inp, out, cache_read=inp * 0.1, cache_write=inp * 1.25)


# Checked against the providers' pricing pages on 2026-10-18; update when they change.
# OpenAI: short-context (<=272K input) standard tier. Anthropic: Haiku 5.5 doubles past 100K.
PRICES: dict[str, Price] = {
    "gpt-6.1-sol": Price(2.00, 10.00, cache_read=0.10),
    "gpt-6-sol": Price(2.00, 10.00, cache_read=0.20),
    "gpt-6-luna": Price(0.10, 0.50, cache_read=0.01),
    "gpt-6-astra": Price(10.00, 50.00, cache_read=1.00),
    "gpt-5.4-mini": Price(0.75, 4.50, cache_read=0.075),
    "gpt-5.4-nano": Price(0.20, 1.25, cache_read=0.02),
    "claude-haiku-5-5": _anthropic(0.10, 0.50),
    "claude-sonnet-5-5": _anthropic(2.00, 10.00),
    "claude-opus-5-5": _anthropic(4.00, 20.00),
    "claude-sonnet-5": _anthropic(2.00, 10.00),
    "claude-opus-4-8": _anthropic(5.00, 25.00),
    "claude-haiku-4-5": _anthropic(1.00, 5.00),
}
# Claude models that accept the server-side refusal fallback (`fallbacks: "default"`).
_SERVER_FALLBACK = frozenset({"claude-sonnet-5-5", "claude-opus-5-5"})


def price_of(model: str) -> Price | None:
    """Exact id, else the longest known prefix (APIs report dated snapshots like `x-2026-09-01`)."""
    if model in PRICES:
        return PRICES[model]
    known = [name for name in PRICES if model.startswith(name)]
    return PRICES[max(known, key=len)] if known else None


class Usage(BaseModel):
    input_tokens: int = 0  # uncached input
    output_tokens: int = 0  # includes reasoning tokens
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
    """0.0 for unknown models (e.g. a local Ollama model) rather than a wrong guess."""
    p = price_of(model)
    if p is None:
        return 0.0
    return (
        inp * p.input + out * p.output + cache_read * p.cache_read + cache_write * p.cache_write
    ) / 1_000_000


def _usage(model: str, inp: int, out: int, cache_read: int, cache_write: int) -> Usage:
    return Usage(
        input_tokens=inp,
        output_tokens=out,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
        cost_usd=cost(model, inp, out, cache_read, cache_write),
        calls=1,
    )


class Completion(BaseModel):
    text: str
    model: str
    usage: Usage
    stop_reason: str | None = None


class LLM(Protocol):
    """`json_schema`, when given, asks the provider to constrain the reply to that schema."""

    def complete(
        self,
        *,
        model: str,
        system: str,
        messages: Sequence[dict[str, Any]],
        max_tokens: int = 16000,
        effort: Effort | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> Completion: ...


class OpenAICompatibleLLM:
    """Chat Completions: OpenAI by default, or any compatible server via `base_url`."""

    def __init__(self, client: "openai.OpenAI") -> None:
        self.client = client

    def complete(
        self,
        *,
        model: str,
        system: str,
        messages: Sequence[dict[str, Any]],
        max_tokens: int = 16000,
        effort: Effort | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> Completion:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "system", "content": system}, *messages],
            # Reasoning models count their hidden reasoning against this budget too.
            "max_completion_tokens": max_tokens,
        }
        if effort:
            kwargs["reasoning_effort"] = effort
        if json_schema:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "response", "schema": json_schema, "strict": True},
            }
        response: Any = self.client.chat.completions.create(**kwargs)

        choice = response.choices[0]
        text = choice.message.content or ""
        if not text and getattr(choice.message, "refusal", None):
            text = f"[The model declined to answer: {choice.message.refusal}]"
        u = response.usage
        details = getattr(u, "prompt_tokens_details", None) if u else None
        cached = (details.cached_tokens or 0) if details else 0
        served_by = str(response.model)
        return Completion(
            text=text,
            model=served_by,
            stop_reason=choice.finish_reason,
            # prompt_tokens includes the cached part; bill that at the cached rate.
            usage=_usage(
                served_by,
                (u.prompt_tokens - cached) if u else 0,
                u.completion_tokens if u else 0,
                cached,
                0,
            ),
        )


class AnthropicLLM:
    def __init__(self, client: "anthropic.Anthropic") -> None:
        self.client = client

    def complete(
        self,
        *,
        model: str,
        system: str,
        messages: Sequence[dict[str, Any]],
        max_tokens: int = 16000,
        effort: Effort | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> Completion:
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": list(messages),
        }
        output_config: dict[str, Any] = {}
        if effort:
            output_config["effort"] = effort
        if json_schema:
            output_config["format"] = {"type": "json_schema", "schema": json_schema}
        if output_config:
            kwargs["output_config"] = output_config
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
        served_by = str(response.model)
        return Completion(
            text=text,
            model=served_by,
            stop_reason=response.stop_reason,
            usage=_usage(
                served_by,
                u.input_tokens,
                u.output_tokens,
                u.cache_read_input_tokens or 0,
                u.cache_creation_input_tokens or 0,
            ),
        )


class ConfigError(ValueError):
    """Missing or wrong credentials; the message says how to fix it."""


def make_llm(settings: "Settings") -> LLM:
    if settings.provider == "anthropic":
        import anthropic

        key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else ""
        if not key.startswith("sk-ant-"):
            raise ConfigError(
                "ACR_PROVIDER=anthropic needs ANTHROPIC_API_KEY=sk-ant-... "
                "(console.anthropic.com/settings/keys)"
            )
        return AnthropicLLM(anthropic.Anthropic(api_key=key))

    import openai

    key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else ""
    if settings.openai_base_url:  # Ollama and friends often need no real key
        return OpenAICompatibleLLM(
            openai.OpenAI(api_key=key or "not-needed", base_url=settings.openai_base_url)
        )
    if not key.startswith("sk-"):
        misplaced = settings.anthropic_api_key and settings.anthropic_api_key.get_secret_value()
        hint = (
            " Your .env has an OpenAI-style key under ANTHROPIC_API_KEY — rename it."
            if misplaced and misplaced.startswith("sk-proj-")
            else ""
        )
        raise ConfigError(f"ACR_PROVIDER=openai needs OPENAI_API_KEY=sk-... in .env.{hint}")
    return OpenAICompatibleLLM(openai.OpenAI(api_key=key))
