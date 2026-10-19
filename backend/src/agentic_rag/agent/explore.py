"""Investigation results and the per-round grading step.

The loop itself is the LangGraph state machine in agent/graph.py; `explore()` runs it up to
the point where an answer would be written. The models here (Round, Exploration) are what a
run produces, and `_grade_round` is the grading step its nodes share.
"""

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

from agentic_rag.agent.budget import Budget, BudgetTracker
from agentic_rag.agent.calls import Observation, SemanticSearch
from agentic_rag.agent.grade import HitGrade, grade_and_maybe_rewrite
from agentic_rag.agent.options import FULL, AgentOptions
from agentic_rag.agent.planner import Plan
from agentic_rag.agent.router import Route
from agentic_rag.agent.sufficiency import Sufficiency
from agentic_rag.llm import LLM, Usage
from agentic_rag.search.rerank import Reranker
from agentic_rag.workspace import Workspace

if TYPE_CHECKING:
    from agentic_rag.agent.events import Sink

MAX_ROUNDS = 3
MAX_PARALLEL = 6

StopReason = Literal[
    "direct",  # router chose a single search
    "sufficient",  # the sufficiency check said every sub-question is answered
    "planner_done",  # the planner said it was done
    "no_new_calls",  # the planner only proposed calls it had already made
    "max_rounds",
    "budget_tokens",
    "budget_time",
    "budget_cost",
]
_BUDGET_STOP: dict[str, StopReason] = {
    "tokens": "budget_tokens",
    "time": "budget_time",
    "cost": "budget_cost",
}


class Rewrite(BaseModel):
    original: str
    rewritten: str


class Round(BaseModel):
    number: int
    plan: Plan | None  # None on the direct route
    observations: list[Observation]
    skipped_repeats: int = 0
    grades: list[HitGrade] = []
    rewrites: list[Rewrite] = []
    sufficiency: Sufficiency | None = None


class Exploration(BaseModel):
    question: str
    route: Route
    rounds: list[Round]
    usage: Usage
    stop_reason: StopReason
    budget: str  # human-readable spend vs limits

    @property
    def observations(self) -> list[Observation]:
        return [obs for r in self.rounds for obs in r.observations]

    @property
    def sub_questions(self) -> list[str]:
        first = next((r.plan for r in self.rounds if r.plan), None)
        return first.sub_questions if first else []

    def render(self) -> str:
        r = self.route
        out = [f"Route: {r.route} ({r.category}) — {r.reason}"]
        for rnd in self.rounds:
            out.append(f"\n=== Round {rnd.number}")
            if rnd.plan:
                if rnd.plan.sub_questions and rnd.number == 1:
                    out += [f"  sub-question: {q}" for q in rnd.plan.sub_questions]
                out.append(f"  plan: {rnd.plan.rationale}")
                out += [f"  - {s.call.tool}: {s.purpose}" for s in rnd.plan.steps]
                if rnd.plan.done and not rnd.plan.steps:
                    out.append("  planner: done")
            if rnd.skipped_repeats:
                out.append(f"  (skipped {rnd.skipped_repeats} repeated call(s))")
            for obs in rnd.observations:
                lines = obs.render().splitlines()
                preview = "\n      ".join(lines[:6])
                more = f"\n      ... ({len(lines) - 6} more lines)" if len(lines) > 6 else ""
                out.append(f"  > [{obs.elapsed_ms} ms] {preview}{more}")
            if rnd.grades:
                out.append("  grading: " + _grade_summary(rnd.grades))
            for rw in rnd.rewrites:
                out.append(f"  rewrite: {rw.original!r} -> {rw.rewritten!r}")
            if rnd.sufficiency:
                done = sum(a.answered for a in rnd.sufficiency.sub_answers)
                total = len(rnd.sufficiency.sub_answers)
                out.append(f"  sufficiency: {done}/{total} sub-questions answered")
                out += [
                    f"    missing: {a.missing}"
                    for a in rnd.sufficiency.sub_answers
                    if not a.answered
                ]
        u = self.usage
        out.append(f"\nStopped: {self.stop_reason}")
        out.append(
            f"{u.calls} model calls · {u.input_tokens + u.cache_read_tokens} in / "
            f"{u.output_tokens} out tokens · ${u.cost_usd:.4f}  (budget: {self.budget})"
        )
        return "\n".join(out)


def _grade_summary(grades: list[HitGrade]) -> str:
    kept = sum(g.verdict != "irrelevant" for g in grades)
    by_llm = sum(g.by == "llm" for g in grades)
    unverified = sum(g.by == "unverified" for g in grades)
    text = f"{len(grades)} hits -> kept {kept}, dropped {len(grades) - kept}"
    text += f" (reranker decided {len(grades) - by_llm - unverified}, LLM judged {by_llm}"
    return text + (f", {unverified} unverified)" if unverified else ")")


def _grade_round(
    ws: Workspace,
    llm: LLM,
    cheap_model: str,
    reranker: Reranker,
    question: str,
    observations: list[Observation],
    tracker: BudgetTracker,
    options: AgentOptions = FULL,
) -> tuple[list[Observation], list[HitGrade], list[Rewrite]]:
    if options.grading == "off":
        return observations, [], []
    graded_obs: list[Observation] = []
    grades: list[HitGrade] = []
    rewrites: list[Rewrite] = []
    for obs in observations:
        if not isinstance(obs.call, SemanticSearch) or obs.search is None:
            graded_obs.append(obs)
            continue
        # Out of budget: the reranker still runs (it's free); borderline hits stay unverified.
        # rerank_only: the same, by design: no model call in grading at all, so no rewrite
        # either. That is exactly the configuration v1's eval measured as rerank_only.
        allowed_llm = None if tracker.exhausted() or options.grading == "rerank_only" else llm
        result, usage = grade_and_maybe_rewrite(
            ws, allowed_llm, cheap_model, reranker, question, obs, options.rewrite
        )
        tracker.charge(usage)
        graded_obs.append(result.observation)
        grades += result.grades
        if result.rewritten_from is not None:
            assert isinstance(result.observation.call, SemanticSearch)
            rewrites.append(
                Rewrite(original=result.rewritten_from, rewritten=result.observation.call.query)
            )
    return graded_obs, grades, rewrites


def explore(
    ws: Workspace,
    llm: LLM,
    question: str,
    *,
    cheap_model: str,
    heavy_model: str,
    budget: Budget | None = None,
    tracker: BudgetTracker | None = None,
    max_rounds: int = MAX_ROUNDS,
    reranker: Reranker | None = None,
    sink: "Sink | None" = None,
    options: AgentOptions = FULL,
) -> Exploration:
    """Investigate without answering. Runs the agent graph (agent/graph.py) up to `explored`.

    Pass `budget` for a fresh tracker, or `tracker` to share one with later steps.
    """
    from agentic_rag.agent.graph import run_exploration

    return run_exploration(
        ws,
        llm,
        question,
        cheap_model=cheap_model,
        heavy_model=heavy_model,
        budget=budget,
        tracker=tracker,
        max_rounds=max_rounds,
        reranker=reranker,
        sink=sink,
        options=options,
    )
