"""Per-question budget: tokens, wall-clock time and dollars. Whichever runs out first wins.

The loop asks `exhausted()` before every model call, so a question can overshoot by at most
one call — never by a whole extra round.
"""

import time

from pydantic import BaseModel

from agentic_rag.llm import Usage


class Budget(BaseModel):
    max_tokens: int
    max_seconds: float
    max_cost_usd: float


class BudgetTracker:
    def __init__(self, budget: Budget) -> None:
        self.budget = budget
        self.usage = Usage()
        self._started = time.perf_counter()

    def charge(self, usage: Usage) -> None:
        self.usage = self.usage + usage

    @property
    def tokens(self) -> int:
        u = self.usage
        return u.input_tokens + u.cache_read_tokens + u.cache_write_tokens + u.output_tokens

    @property
    def seconds(self) -> float:
        return time.perf_counter() - self._started

    def exhausted(self) -> str | None:
        """The name of the limit that ran out, or None."""
        if self.tokens >= self.budget.max_tokens:
            return "tokens"
        if self.seconds >= self.budget.max_seconds:
            return "time"
        if self.usage.cost_usd >= self.budget.max_cost_usd:
            return "cost"
        return None

    def summary(self) -> str:
        b = self.budget
        return (
            f"{self.tokens:,}/{b.max_tokens:,} tokens · {self.seconds:.1f}/{b.max_seconds:.0f}s · "
            f"${self.usage.cost_usd:.4f}/${b.max_cost_usd:.2f}"
        )
