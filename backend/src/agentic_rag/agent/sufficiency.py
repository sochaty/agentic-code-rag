"""Sufficiency check: is every sub-question answered by the evidence so far?

Runs on the cheap model after each round. A "yes" stops the loop before another heavy
planner call — the fix for the M3 run that kept searching after round 2 had the answer.
"""

from pydantic import BaseModel

from agentic_rag.agent.calls import Observation
from agentic_rag.agent.structured import complete_structured
from agentic_rag.llm import LLM, Usage


class SubAnswer(BaseModel):
    sub_question: str
    answered: bool
    evidence: list[int]  # observation numbers that answer it
    missing: str  # what's still needed, or "" when answered


class Sufficiency(BaseModel):
    sub_answers: list[SubAnswer]
    sufficient: bool


SYSTEM = """You check whether gathered evidence is enough to answer a question about a codebase.

For each sub-question, decide if the numbered observations answer it with concrete evidence
(code, call-graph results, commits, or an exhaustive search showing something is absent).
Cite the observation numbers. If not answered, say briefly what is missing.
Rules:
- Absence is answerable: if exact searches for several plausible spellings found nothing and
  the docs search shows nothing relevant, "no, it isn't there" counts as answered. The same
  goes for "do the docs say X?": if the searched docs don't mention X, that is the answer.
- A sub-question only knowledge outside this repository could answer (third-party packages,
  other projects) counts as answered; put "outside the repository" in missing.
- Don't demand more than the question asks for.
Set sufficient=true only if every sub-question is answered."""


def check_sufficiency(
    llm: LLM,
    model: str,
    question: str,
    sub_questions: list[str],
    observations: list[Observation],
) -> tuple[Sufficiency, Usage]:
    numbered = "\n\n".join(f"[{i}] {obs.render()}" for i, obs in enumerate(observations, 1))
    subs = "\n".join(f"- {q}" for q in sub_questions) or f"- {question}"
    return complete_structured(
        llm,
        model=model,
        system=SYSTEM,
        user=f"Question: {question}\n\nSub-questions:\n{subs}\n\nObservations:\n\n{numbered}",
        schema=Sufficiency,
        effort="low",
        max_tokens=4000,
    )
