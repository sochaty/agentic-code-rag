"""The configurations compared: the naive baseline, the full agent, and one-switch ablations."""

from dataclasses import dataclass, field
from typing import Literal

from agentic_rag.agent.options import FULL, AgentOptions


@dataclass(frozen=True)
class Config:
    name: str
    mode: Literal["naive", "agent"]
    description: str
    options: AgentOptions = field(default=FULL)


CONFIGS: dict[str, Config] = {
    c.name: c
    for c in [
        Config("naive", "naive", "Single-pass RAG: one dense search, one answer"),
        Config("full", "agent", "The full agent"),
        Config(
            "no_router",
            "agent",
            "Skip the router: every question runs the full loop",
            AgentOptions(use_router=False),
        ),
        Config(
            "no_grading",
            "agent",
            "Keep every semantic hit: no reranker, no LLM grading",
            AgentOptions(grading="off"),
        ),
        Config(
            "rerank_only",
            "agent",
            "Reranker grading only: no model call in grading (the default since v1.1)",
            AgentOptions(grading="rerank_only"),
        ),
        Config(
            "llm_grading",
            "agent",
            "Borderline hits graded by the cheap model (the v1 default)",
            AgentOptions(grading="full"),
        ),
        Config(
            "no_follow_up",
            "agent",
            "Don't read the code that search hits and graph edges point at (as in v1)",
            AgentOptions(follow_up=False),
        ),
        Config(
            "no_sufficiency",
            "agent",
            "No sufficiency check: plan until the planner stops",
            AgentOptions(sufficiency=False),
        ),
        Config(
            "no_verify",
            "agent",
            "No claim verification: keep every synthesized claim",
            AgentOptions(verify=False),
        ),
        Config(
            "low_effort",
            "agent",
            "Planner and synthesizer at low reasoning effort",
            AgentOptions(plan_effort="low", synth_effort="low"),
        ),
    ]
}

# `--configs all`: every configuration that differs from `full`. Since v1.1 rerank_only *is* the
# default, so it stays defined (v1's results are labelled with it) but isn't run twice.
DEFAULT_SUITE = [
    name
    for name, c in CONFIGS.items()
    if name == "full" or c.mode != "agent" or c.options != CONFIGS["full"].options
]
