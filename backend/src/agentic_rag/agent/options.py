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
    grading: Grading = "full"  # rerank_only: no LLM for borderline hits; off: keep every hit
    rewrite: bool = True  # rewrite a query once when every hit was dropped
    sufficiency: bool = True  # off: keep planning until the planner stops or rounds run out
    verify: bool = True  # off: keep every synthesized claim, unchecked
    plan_effort: Effort = "medium"
    synth_effort: Effort = "medium"


FULL = AgentOptions()
