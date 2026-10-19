"""Grade an answer against the gold answer and key facts, and tell hallucination from abstention.

The judge sees the gold answer and key facts, so it doesn't have to know Flask: it checks
agreement, not truth. Abstaining ("can't tell from the evidence") is scored as wrong but
counted separately from contradicting the gold — the difference the blog cares about.
"""

from typing import Literal

from pydantic import BaseModel

from agentic_rag.agent.structured import complete_structured
from agentic_rag.evaluation.dataset import EvalQuestion
from agentic_rag.llm import LLM, Usage

Grade = Literal["correct", "partial", "incorrect", "abstained"]
SCORES: dict[Grade, float] = {"correct": 1.0, "partial": 0.5, "incorrect": 0.0, "abstained": 0.0}


class Judgement(BaseModel):
    grade: Grade
    facts_present: list[int]  # indexes into key_facts that the answer states
    contradictions: list[str]  # statements that conflict with the gold answer or facts
    reason: str

    @property
    def score(self) -> float:
        return SCORES[self.grade]


SYSTEM = """You grade answers to questions about a code repository against a reference.

You get the question, a gold answer, numbered key facts, and the candidate answer.
- correct: states the gold answer's substance and all key facts (wording may differ;
  extra true detail is fine).
- partial: right direction but misses key facts, or is right only in part.
- incorrect: wrong, or contradicts the gold answer.
- abstained: says it can't determine the answer and doesn't commit to one.
List which key facts the answer states (by number), and quote any statements that
contradict the gold answer or key facts. Judge only against the reference."""


def judge(
    llm: LLM, model: str, question: EvalQuestion, answer_text: str
) -> tuple[Judgement, Usage]:
    facts = "\n".join(f"[{i}] {fact}" for i, fact in enumerate(question.key_facts))
    user = (
        f"Question: {question.question}\n\nGold answer: {question.gold_answer}\n\n"
        f"Key facts:\n{facts}\n\nCandidate answer:\n{answer_text}"
    )
    return complete_structured(
        llm, model=model, system=SYSTEM, user=user, schema=Judgement, effort="low", max_tokens=4000
    )
