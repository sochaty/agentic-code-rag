"""Route -> (plan -> execute in parallel) x rounds. Grading, budget and answering come in M4-M5."""

from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel

from agentic_rag.agent.calls import Observation, SemanticSearch, ToolCall, call_key, execute
from agentic_rag.agent.planner import Plan, plan_next
from agentic_rag.agent.router import Route, route_question
from agentic_rag.llm import LLM, Usage
from agentic_rag.workspace import Workspace

MAX_ROUNDS = 3
MAX_PARALLEL = 6


class Round(BaseModel):
    number: int
    plan: Plan | None  # None on the direct route
    observations: list[Observation]
    skipped_repeats: int = 0


class Exploration(BaseModel):
    question: str
    route: Route
    rounds: list[Round]
    usage: Usage

    @property
    def observations(self) -> list[Observation]:
        return [obs for r in self.rounds for obs in r.observations]

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
                first = obs.render().splitlines()
                preview = "\n      ".join(first[:6])
                more = f"\n      ... ({len(first) - 6} more lines)" if len(first) > 6 else ""
                out.append(f"  > [{obs.elapsed_ms} ms] {preview}{more}")
        u = self.usage
        out.append(
            f"\n{u.calls} model calls · {u.input_tokens + u.cache_read_tokens} in / "
            f"{u.output_tokens} out tokens · ${u.cost_usd:.4f}"
        )
        return "\n".join(out)


def _run_parallel(ws: Workspace, calls: list[ToolCall]) -> list[Observation]:
    if not calls:
        return []
    with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL, len(calls))) as pool:
        return list(pool.map(lambda call: execute(ws, call), calls))


def explore(
    ws: Workspace,
    llm: LLM,
    question: str,
    *,
    cheap_model: str,
    heavy_model: str,
    max_rounds: int = MAX_ROUNDS,
) -> Exploration:
    route, usage = route_question(llm, cheap_model, question)

    if route.route == "direct":
        search = SemanticSearch(
            tool="semantic_search", query=question, scope="all", include_tests=False
        )
        only = Round(number=1, plan=None, observations=_run_parallel(ws, [search]))
        return Exploration(question=question, route=route, rounds=[only], usage=usage)

    rounds: list[Round] = []
    seen: set[str] = set()
    observations: list[Observation] = []
    for number in range(1, max_rounds + 1):
        plan, plan_usage = plan_next(llm, heavy_model, question, route, observations, number)
        usage = usage + plan_usage
        fresh: list[ToolCall] = []
        for step in plan.steps:  # drop repeats, both of earlier rounds and within this one
            key = call_key(step.call)
            if key not in seen:
                seen.add(key)
                fresh.append(step.call)
        skipped = len(plan.steps) - len(fresh)
        results = _run_parallel(ws, fresh)
        observations += results
        rounds.append(
            Round(number=number, plan=plan, observations=results, skipped_repeats=skipped)
        )
        if plan.done or not fresh:
            break
    return Exploration(question=question, route=route, rounds=rounds, usage=usage)
