"""Feature switches for the agent, so the eval can turn off one piece at a time.

The defaults are the full agent. Every ablation is the same graph with exactly one switch
flipped, which is what makes "what does each piece buy?" a fair comparison.
"""

from dataclasses import dataclass
from typing import Literal

from agentic_rag.llm import Effort

Grading = Literal["full", "rerank_only", "off"]


@dataclass(frozen=True)
class AgentOptions:
    use_router: bool = True  # off: skip the router call, always run the full loop
    # full: borderline reranker scores go to the cheap model. v1's eval found that call bought
    # nothing measurable, so since v1.1 the reranker decides alone. off: keep every hit.
    grading: Grading = "rerank_only"
    rewrite: bool = True  # rewrite a query once when every hit was dropped
    sufficiency: bool = True  # off: keep planning until the planner stops or rounds run out
    follow_up: bool = True  # off: don't read the code that grep hits and graph edges point at
    verify: bool = True  # off: keep every synthesized claim, unchecked
    plan_effort: Effort = "medium"
    synth_effort: Effort = "medium"


FULL = AgentOptions()
