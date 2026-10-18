"""Router: is one search enough, or does this question need the agent loop?

The cheap model only *classifies* the question; code maps the category to a route. Letting
the model pick the route directly was unstable: the same "Does Flask have built-in rate
limiting?" went agentic on one run and direct on the next, and a single search can't prove
that something is absent.
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

# Only these are answerable from one search; everything else needs the loop.
DIRECT: frozenset[Category] = frozenset({"lookup", "conceptual"})


class Route(BaseModel):
    category: Category
    reason: str

    @property
    def route(self) -> Literal["direct", "agentic"]:
        return "direct" if self.category in DIRECT else "agentic"


SYSTEM = """You classify questions about a software repository before anyone searches it.

Categories:
- lookup: what one specific function, class or file does, or where it is defined.
  "What does preprocess_request do?"
- conceptual: how a feature works, as explained in docs and code.
  "How are teardown functions run after a request?"
- identifier: about a specific config key, error message or name.
  "What is SESSION_COOKIE_SAMESITE for?"
- call_graph: who calls something, what it calls, or a class hierarchy.
  "Who calls handle_user_exception?"
- history: when or why something changed. "Why was X added?"
- existence: whether something exists or is supported — the answer may be "no".
  "Does Flask have built-in rate limiting?" "Is X supported?" "Can Flask do Y out of the box?"
- multi_part: combines several of the above.

If a question fits existence, history or call_graph, choose that over lookup or conceptual.
Give a one-sentence reason."""


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
