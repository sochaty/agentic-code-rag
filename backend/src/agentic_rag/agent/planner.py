"""Planner: decide which tool calls to run next, given what has been found so far.

The same planner handles the first round and every follow-up: it sees the observations
gathered so far and either plans what is still missing or says it is done.
"""

from pydantic import BaseModel

from agentic_rag.agent.calls import CATALOG, Observation, ToolCall
from agentic_rag.agent.router import Route
from agentic_rag.agent.structured import complete_structured
from agentic_rag.llm import LLM, Effort, Usage

MAX_STEPS = 6


class Step(BaseModel):
    call: ToolCall
    purpose: str


class Plan(BaseModel):
    sub_questions: list[str]
    steps: list[Step]
    done: bool
    rationale: str


SYSTEM = f"""You plan how to investigate a question about a software repository.

You can't read the repository directly. You choose tool calls; they run, and you see the
results in the next round. All calls in one round run in parallel, so a call can't use
another call's result from the same round.

Tools:
{CATALOG}

Strategy:
- Break the question into sub-questions, then plan the calls that answer them.
- "Who calls X" / "what does X call": symbol_graph first. Follow chains one hop per round.
- "Does X exist / is X supported": exact_search several plausible spellings (whole_word
  where it avoids partial matches) plus semantic_search over docs. Absence needs evidence.
- "When / why did X change": git_history on the symbol or file, plus
  semantic_search(scope="changelog").
- Identifiers and config keys: exact_search before semantic_search.
- Use read_source when you need the actual lines to answer or cite.
- At most {MAX_STEPS} calls per round. Don't repeat a call you've already made.
- Set done=true, with no steps, once the observations are enough to answer every
  sub-question — or when further calls won't help. Never pad a plan."""


def _user_prompt(
    question: str, route: Route, observations: list[Observation], round_no: int
) -> str:
    parts = [f"Question: {question}", f"Category: {route.category}", f"Round: {round_no}"]
    if observations:
        parts.append("Observations so far:")
        parts += [f"--- [{i}] {obs.render()}" for i, obs in enumerate(observations, 1)]
    else:
        parts.append("No observations yet: this is the first round.")
    return "\n\n".join(parts)


def plan_next(
    llm: LLM,
    model: str,
    question: str,
    route: Route,
    observations: list[Observation],
    round_no: int,
    effort: Effort = "medium",
) -> tuple[Plan, Usage]:
    plan, usage = complete_structured(
        llm,
        model=model,
        system=SYSTEM,
        user=_user_prompt(question, route, observations, round_no),
        schema=Plan,
        effort=effort,
    )
    plan.steps = plan.steps[:MAX_STEPS]
    return plan, usage
