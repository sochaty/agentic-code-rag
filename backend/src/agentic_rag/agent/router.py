"""Router: is one search enough, or does this question need the agent loop?

Runs on the cheap model at low effort — it costs a fraction of a cent and saves the full
loop on easy questions.
"""

from typing import Literal

from pydantic import BaseModel

from agentic_rag.agent.structured import complete_structured
from agentic_rag.llm import LLM, Usage

Category = Literal[
    "lookup",  # what does X do / where is X defined
    "conceptual",  # how does a feature work, explained in docs and code
    "identifier",  # a specific config key, error message, or name
    "call_graph",  # who calls X, what X calls, class hierarchy
    "history",  # when or why something changed
    "existence",  # does X exist / is X supported (the answer may be "no")
    "multi_part",  # several of the above at once
]


class Route(BaseModel):
    category: Category
    route: Literal["direct", "agentic"]
    reason: str


SYSTEM = """You triage questions about a software repository before anyone searches it.

Pick the category, then the route:
- "direct": a single search will almost certainly surface the answer in one place
  (e.g. what one function does, a concept documented in one section).
- "agentic": the answer needs relationships (callers, call chains, inheritance), history
  (when/why something changed), proof of absence ("does X exist?" may need "no"), or
  several facts combined.
When unsure, choose "agentic". Keep the reason to one short sentence."""


def route_question(llm: LLM, model: str, question: str) -> tuple[Route, Usage]:
    return complete_structured(
        llm,
        model=model,
        system=SYSTEM,
        user=f"Question: {question}",
        schema=Route,
        effort="low",
        max_tokens=2000,
    )
