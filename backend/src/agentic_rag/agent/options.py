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
    # full: borderline reranker scores go to the cheap model, and a search whose hits were all
    # dropped is rewritten once. rerank_only: the reranker decides alone, with no model call
    # (so no rewrite). v1's eval measured rerank_only as accurate as full and cheaper, so it is
    # the default since v1.1. off: keep every hit.
    grading: Grading = "rerank_only"
    rewrite: bool = True  # with grading="full": rewrite a query once when every hit was dropped
    sufficiency: bool = True  # off: keep planning until the planner stops or rounds run out
    follow_up: bool = True  # off: don't read the code that grep hits and graph edges point at
    verify: bool = True  # off: keep every synthesized claim, unchecked
    plan_effort: Effort = "medium"
    synth_effort: Effort = "medium"


FULL = AgentOptions()
