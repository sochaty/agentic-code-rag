"""Typed events: what each step of a run did, in order. The single source for every consumer.

The CLI trace, the API's server-sent events, the web UI and the eval all read this stream,
so they can never disagree about what happened. Every event is JSON-serialisable.
"""

import time
from collections.abc import Callable
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from agentic_rag.agent.calls import Observation, ToolCall
from agentic_rag.agent.grade import HitGrade
from agentic_rag.agent.planner import Plan
from agentic_rag.agent.sufficiency import Sufficiency


class _Event(BaseModel):
    seq: int = 0  # assigned by the emitter
    at: float = 0.0  # seconds since the run started
    spent_usd: float = 0.0  # running total when the event fired
    spent_tokens: int = 0


class RunCreated(_Event):
    """Sent by the API before the run starts: the id to share or reopen the run with."""

    type: Literal["run_created"] = "run_created"
    id: str


class RunStarted(_Event):
    type: Literal["run_started"] = "run_started"
    question: str
    max_tokens: int
    max_seconds: float
    max_cost_usd: float


class Routed(_Event):
    type: Literal["routed"] = "routed"
    category: str
    route: Literal["direct", "agentic"]
    reason: str


class Planned(_Event):
    type: Literal["planned"] = "planned"
    round: int
    plan: Plan
    skipped_repeats: int


class ToolStarted(_Event):
    type: Literal["tool_started"] = "tool_started"
    round: int
    index: int  # position within the round
    call: ToolCall


class ToolFinished(_Event):
    type: Literal["tool_finished"] = "tool_finished"
    round: int
    index: int
    observation: Observation


class Graded(_Event):
    type: Literal["graded"] = "graded"
    round: int
    grades: list[HitGrade]
    rewrites: list[tuple[str, str]]


class Checked(_Event):
    type: Literal["checked"] = "checked"
    round: int
    sufficiency: Sufficiency


class ExplorationDone(_Event):
    type: Literal["exploration_done"] = "exploration_done"
    stop_reason: str
    rounds: int


class Synthesized(_Event):
    type: Literal["synthesized"] = "synthesized"
    attempt: int  # 2 after a repair
    direct_answer: str
    claims: int


class Verified(_Event):
    type: Literal["verified"] = "verified"
    attempt: int
    supported: int
    partial: int
    unsupported: int


class Repairing(_Event):
    type: Literal["repairing"] = "repairing"
    claims: list[str]
    calls: list[ToolCall]


class Finished(_Event):
    """The last event of every run. `answer` is the full Answer JSON when one was written."""

    type: Literal["finished"] = "finished"
    stop_reason: str
    answer: dict[str, object] | None = None


class Failed(_Event):
    type: Literal["failed"] = "failed"
    error: str


Event = Annotated[
    RunCreated
    | RunStarted
    | Routed
    | Planned
    | ToolStarted
    | ToolFinished
    | Graded
    | Checked
    | ExplorationDone
    | Synthesized
    | Verified
    | Repairing
    | Finished
    | Failed,
    Field(discriminator="type"),
]

Sink = Callable[[_Event], None]


class Emitter:
    """Stamps each event with order, time and spend, then hands it to the sink."""

    def __init__(self, sink: Sink | None, spent: Callable[[], tuple[float, int]]) -> None:
        self._sink = sink
        self._spent = spent
        self._seq = 0
        self._started = time.perf_counter()

    def __call__(self, event: _Event) -> None:
        if self._sink is None:
            return
        self._seq += 1
        usd, tokens = self._spent()
        event.seq = self._seq
        event.at = round(time.perf_counter() - self._started, 3)
        event.spent_usd = round(usd, 6)
        event.spent_tokens = tokens
        self._sink(event)
