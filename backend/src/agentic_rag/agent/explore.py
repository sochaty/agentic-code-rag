"""The investigation loop (answering comes in M5):

    route -> [plan -> run calls in parallel -> grade semantic hits (rewrite if all miss)
              -> enough evidence?] x rounds

Every model call first asks the budget; the run records why it stopped.
"""

from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from pydantic import BaseModel

from agentic_rag.agent.budget import Budget, BudgetTracker
from agentic_rag.agent.calls import Observation, SemanticSearch, ToolCall, call_key, execute
from agentic_rag.agent.grade import HitGrade, grade_and_maybe_rewrite
from agentic_rag.agent.planner import Plan, plan_next
from agentic_rag.agent.router import Route, route_question
from agentic_rag.agent.sufficiency import Sufficiency, check_sufficiency
from agentic_rag.llm import LLM, Usage
from agentic_rag.search.rerank import Reranker
from agentic_rag.workspace import Workspace

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


def _run_parallel(ws: Workspace, calls: list[ToolCall]) -> list[Observation]:
    if not calls:
        return []
    with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL, len(calls))) as pool:
        return list(pool.map(lambda call: execute(ws, call), calls))


def _grade_round(
    ws: Workspace,
    llm: LLM,
    cheap_model: str,
    reranker: Reranker,
    question: str,
    observations: list[Observation],
    tracker: BudgetTracker,
) -> tuple[list[Observation], list[HitGrade], list[Rewrite]]:
    graded_obs: list[Observation] = []
    grades: list[HitGrade] = []
    rewrites: list[Rewrite] = []
    for obs in observations:
        if not isinstance(obs.call, SemanticSearch) or obs.search is None:
            graded_obs.append(obs)
            continue
        # Out of budget: the reranker still runs (it's free); borderline hits stay unverified.
        allowed_llm = None if tracker.exhausted() else llm
        result, usage = grade_and_maybe_rewrite(
            ws, allowed_llm, cheap_model, reranker, question, obs
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
) -> Exploration:
    """Pass `budget` for a fresh tracker, or `tracker` to share one with later steps."""
    if tracker is None:
        if budget is None:
            raise ValueError("explore() needs a budget or a tracker")
        tracker = BudgetTracker(budget)
    ws.warm_up()  # load models up front, not inside the first parallel round
    reranker = reranker or ws.reranker
    route, usage = route_question(llm, cheap_model, question)
    tracker.charge(usage)

    def finish(rounds: list[Round], reason: StopReason) -> Exploration:
        return Exploration(
            question=question,
            route=route,
            rounds=rounds,
            usage=tracker.usage,
            stop_reason=reason,
            budget=tracker.summary(),
        )

    if route.route == "direct":
        search = SemanticSearch(
            tool="semantic_search", query=question, scope="all", include_tests=False
        )
        observations, grades, rewrites = _grade_round(
            ws, llm, cheap_model, reranker, question, _run_parallel(ws, [search]), tracker
        )
        only = Round(
            number=1, plan=None, observations=observations, grades=grades, rewrites=rewrites
        )
        return finish([only], "direct")

    rounds: list[Round] = []
    seen: set[str] = set()
    gathered: list[Observation] = []
    for number in range(1, max_rounds + 1):
        if limit := tracker.exhausted():
            return finish(rounds, _BUDGET_STOP[limit])
        plan, plan_usage = plan_next(llm, heavy_model, question, route, gathered, number)
        tracker.charge(plan_usage)

        fresh: list[ToolCall] = []
        for step in plan.steps:  # drop repeats, both of earlier rounds and within this one
            key = call_key(step.call)
            if key not in seen:
                seen.add(key)
                fresh.append(step.call)
        results, grades, rewrites = _grade_round(
            ws, llm, cheap_model, reranker, question, _run_parallel(ws, fresh), tracker
        )
        gathered += results
        current = Round(
            number=number,
            plan=plan,
            observations=results,
            skipped_repeats=len(plan.steps) - len(fresh),
            grades=grades,
            rewrites=rewrites,
        )
        rounds.append(current)

        if not fresh:
            return finish(rounds, "planner_done" if plan.done else "no_new_calls")
        if plan.done:
            return finish(rounds, "planner_done")
        if number == max_rounds:
            break
        if limit := tracker.exhausted():
            return finish(rounds, _BUDGET_STOP[limit])
        verdict, check_usage = check_sufficiency(
            llm,
            cheap_model,
            question,
            rounds[0].plan.sub_questions if rounds[0].plan else [],
            gathered,
        )
        tracker.charge(check_usage)
        current.sufficiency = verdict
        if verdict.sufficient:
            return finish(rounds, "sufficient")
    return finish(rounds, "max_rounds")
