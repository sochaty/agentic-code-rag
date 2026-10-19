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
            "Reranker grading only: no LLM for borderline hits",
            AgentOptions(grading="rerank_only"),
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

DEFAULT_SUITE = list(CONFIGS)
