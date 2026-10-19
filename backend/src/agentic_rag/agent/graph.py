"""The agent as an explicit LangGraph state machine.

    route ─direct─> direct_search ──────────────────────────────┐
      └─agentic─> plan ─> execute ─> grade ─> check ─> (plan…)   │
                    └──────────────────────────┴─> explored <────┘
    explored ─(answer wanted)─> synthesize ─> verify ─(unsupported, budget left)─> repair ─┐
                                    ^─────────────────────────────────────────────────────┘

Each node is a thin wrapper around a function that is unit-tested on its own (router,
planner, grading, sufficiency, synthesis, verification). Nodes emit typed events, so every
consumer — CLI, API, UI, eval — sees the same run.
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from agentic_rag.agent import events as ev
from agentic_rag.agent.answer import (
    Answer,
    CheckedClaim,
    Draft,
    repair_calls,
    synthesize,
    verify,
)
from agentic_rag.agent.budget import Budget, BudgetTracker
from agentic_rag.agent.calls import Observation, SemanticSearch, ToolCall, call_key, execute
from agentic_rag.agent.explore import (
    _BUDGET_STOP,
    MAX_PARALLEL,
    MAX_ROUNDS,
    Exploration,
    Round,
    StopReason,
    _grade_round,
)
from agentic_rag.agent.planner import plan_next
from agentic_rag.agent.router import Route, route_question
from agentic_rag.agent.sufficiency import check_sufficiency
from agentic_rag.llm import LLM
from agentic_rag.search.rerank import Reranker
from agentic_rag.workspace import Workspace

RECURSION_LIMIT = 60  # far above the longest path (~20 steps); a guard, not a tuning knob


class State(TypedDict, total=False):
    question: str
    want_answer: bool
    max_rounds: int
    route: Route
    rounds: list[Round]
    seen: list[str]
    pending: list[ToolCall]
    stop: StopReason | None
    draft: Draft
    checked: list[CheckedClaim]
    extra: list[Observation]  # gathered by the repair pass
    attempt: int
    repaired: bool


@dataclass
class Deps:
    ws: Workspace
    llm: LLM
    cheap: str
    heavy: str
    tracker: BudgetTracker
    reranker: Reranker
    emit: ev.Emitter


def _gathered(state: State) -> list[Observation]:
    return [obs for r in state.get("rounds", []) for obs in r.observations]


def _run_calls(deps: Deps, round_no: int, calls: list[ToolCall]) -> list[Observation]:
    """Run calls in parallel, emitting start/finish events as they happen; keep call order."""
    if not calls:
        return []
    for i, call in enumerate(calls):
        deps.emit(ev.ToolStarted(round=round_no, index=i, call=call))
    results: list[Observation | None] = [None] * len(calls)
    with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL, len(calls))) as pool:
        futures = {pool.submit(execute, deps.ws, call): i for i, call in enumerate(calls)}
        for future in as_completed(futures):
            i = futures[future]
            results[i] = future.result()
            deps.emit(ev.ToolFinished(round=round_no, index=i, observation=results[i]))
    return [obs for obs in results if obs is not None]


def build_graph(deps: Deps) -> Any:
    def route(state: State) -> State:
        decision, usage = route_question(deps.llm, deps.cheap, state["question"])
        deps.tracker.charge(usage)
        deps.emit(
            ev.Routed(category=decision.category, route=decision.route, reason=decision.reason)
        )
        return {"route": decision, "rounds": [], "seen": [], "stop": None}

    def direct_search(state: State) -> State:
        call = SemanticSearch(
            tool="semantic_search", query=state["question"], scope="all", include_tests=False
        )
        raw = _run_calls(deps, 1, [call])
        observations, grades, rewrites = _grade_round(
            deps.ws, deps.llm, deps.cheap, deps.reranker, state["question"], raw, deps.tracker
        )
        if grades:
            deps.emit(
                ev.Graded(
                    round=1, grades=grades, rewrites=[(r.original, r.rewritten) for r in rewrites]
                )
            )
        only = Round(
            number=1, plan=None, observations=observations, grades=grades, rewrites=rewrites
        )
        return {"rounds": [only], "stop": "direct"}

    def plan(state: State) -> State:
        if limit := deps.tracker.exhausted():
            return {"stop": _BUDGET_STOP[limit]}
        number = len(state["rounds"]) + 1
        proposed, usage = plan_next(
            deps.llm, deps.heavy, state["question"], state["route"], _gathered(state), number
        )
        deps.tracker.charge(usage)
        seen = list(state["seen"])
        fresh: list[ToolCall] = []
        for step in proposed.steps:  # drop repeats, both of earlier rounds and within this one
            key = call_key(step.call)
            if key not in seen:
                seen.append(key)
                fresh.append(step.call)
        skipped = len(proposed.steps) - len(fresh)
        deps.emit(ev.Planned(round=number, plan=proposed, skipped_repeats=skipped))
        current = Round(number=number, plan=proposed, observations=[], skipped_repeats=skipped)
        return {"rounds": [*state["rounds"], current], "seen": seen, "pending": fresh}

    def execute_calls(state: State) -> State:
        current = state["rounds"][-1]
        raw = _run_calls(deps, current.number, state["pending"])
        observations, grades, rewrites = _grade_round(
            deps.ws, deps.llm, deps.cheap, deps.reranker, state["question"], raw, deps.tracker
        )
        if grades:
            deps.emit(
                ev.Graded(
                    round=current.number,
                    grades=grades,
                    rewrites=[(r.original, r.rewritten) for r in rewrites],
                )
            )
        updated = current.model_copy(
            update={"observations": observations, "grades": grades, "rewrites": rewrites}
        )
        stop: StopReason | None = None
        assert current.plan is not None
        if not state["pending"]:
            stop = "planner_done" if current.plan.done else "no_new_calls"
        elif current.plan.done:
            stop = "planner_done"
        elif current.number >= state["max_rounds"]:
            stop = "max_rounds"
        elif limit := deps.tracker.exhausted():
            stop = _BUDGET_STOP[limit]
        return {"rounds": [*state["rounds"][:-1], updated], "stop": stop}

    def check(state: State) -> State:
        first = state["rounds"][0].plan
        verdict, usage = check_sufficiency(
            deps.llm,
            deps.cheap,
            state["question"],
            first.sub_questions if first else [],
            _gathered(state),
        )
        deps.tracker.charge(usage)
        current = state["rounds"][-1]
        deps.emit(ev.Checked(round=current.number, sufficiency=verdict))
        updated = current.model_copy(update={"sufficiency": verdict})
        return {
            "rounds": [*state["rounds"][:-1], updated],
            "stop": "sufficient" if verdict.sufficient else None,
        }

    def explored(state: State) -> State:
        deps.emit(
            ev.ExplorationDone(
                stop_reason=state["stop"] or "max_rounds", rounds=len(state["rounds"])
            )
        )
        return {}

    def synthesize_node(state: State) -> State:
        attempt = state.get("attempt", 0) + 1
        evidence = _gathered(state) + state.get("extra", [])
        draft, usage = synthesize(deps.llm, deps.heavy, state["question"], evidence)
        deps.tracker.charge(usage)
        deps.emit(
            ev.Synthesized(
                attempt=attempt, direct_answer=draft.direct_answer, claims=len(draft.claims)
            )
        )
        return {"draft": draft, "attempt": attempt}

    def verify_node(state: State) -> State:
        evidence = _gathered(state) + state.get("extra", [])
        checked, usage = verify(deps.ws, deps.llm, deps.cheap, state["draft"].claims, evidence)
        deps.tracker.charge(usage)
        deps.emit(
            ev.Verified(
                attempt=state["attempt"],
                supported=sum(c.verdict == "supported" for c in checked),
                partial=sum(c.verdict == "partial" for c in checked),
                unsupported=sum(c.verdict == "unsupported" for c in checked),
            )
        )
        return {"checked": checked}

    def repair(state: State) -> State:
        unsupported = [c for c in state["checked"] if c.verdict == "unsupported"]
        calls: list[ToolCall] = list(repair_calls(unsupported))
        deps.emit(ev.Repairing(claims=[c.text for c in unsupported], calls=calls))
        extra = _run_calls(deps, 0, calls)  # round 0 marks repair-pass calls
        return {"extra": [*state.get("extra", []), *extra], "repaired": True}

    # ---- edges -------------------------------------------------------------------------

    def after_route(state: State) -> str:
        return "direct_search" if state["route"].route == "direct" else "plan"

    def after_plan(state: State) -> str:
        return "explored" if state.get("stop") else "execute"

    def after_execute(state: State) -> str:
        return "explored" if state.get("stop") else "check"

    def after_check(state: State) -> str:
        return "explored" if state.get("stop") else "plan"

    def after_explored(state: State) -> str:
        return "synthesize" if state["want_answer"] else END

    def after_verify(state: State) -> str:
        unsupported = any(c.verdict == "unsupported" for c in state["checked"])
        if unsupported and not state.get("repaired") and not deps.tracker.exhausted():
            return "repair"
        return END

    graph = StateGraph(State)
    graph.add_node("route", route)
    graph.add_node("direct_search", direct_search)
    graph.add_node("plan", plan)
    graph.add_node("execute", execute_calls)
    graph.add_node("check", check)
    graph.add_node("explored", explored)
    graph.add_node("synthesize", synthesize_node)
    graph.add_node("verify", verify_node)
    graph.add_node("repair", repair)

    graph.add_edge(START, "route")
    graph.add_conditional_edges("route", after_route, ["direct_search", "plan"])
    graph.add_edge("direct_search", "explored")
    graph.add_conditional_edges("plan", after_plan, ["execute", "explored"])
    graph.add_conditional_edges("execute", after_execute, ["check", "explored"])
    graph.add_conditional_edges("check", after_check, ["plan", "explored"])
    graph.add_conditional_edges("explored", after_explored, ["synthesize", END])
    graph.add_edge("synthesize", "verify")
    graph.add_conditional_edges("verify", after_verify, ["repair", END])
    graph.add_edge("repair", "synthesize")
    return graph.compile()


def mermaid() -> str:
    """The graph as a Mermaid diagram (for the README and the blog)."""
    dummy: Any = None
    deps = Deps(dummy, dummy, "", "", dummy, dummy, ev.Emitter(None, lambda: (0.0, 0)))
    return str(build_graph(deps).get_graph().draw_mermaid())


def run(
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
    want_answer: bool = True,
    sink: ev.Sink | None = None,
) -> tuple[State, BudgetTracker, float, ev.Emitter]:
    """Run the graph; returns the final state, tracker, wall-clock seconds and the emitter."""
    if tracker is None:
        if budget is None:
            raise ValueError("run() needs a budget or a tracker")
        tracker = BudgetTracker(budget)
    started = time.perf_counter()
    spend = tracker  # bound for the lambda: mypy can't narrow `tracker` inside it
    emit = ev.Emitter(sink, lambda: (spend.usage.cost_usd, spend.tokens))
    b = tracker.budget
    emit(
        ev.RunStarted(
            question=question,
            max_tokens=b.max_tokens,
            max_seconds=b.max_seconds,
            max_cost_usd=b.max_cost_usd,
        )
    )
    try:
        ws.warm_up()  # load models up front, not inside the first parallel round
        deps = Deps(ws, llm, cheap_model, heavy_model, tracker, reranker or ws.reranker, emit)
        initial: State = {
            "question": question,
            "want_answer": want_answer,
            "max_rounds": max_rounds,
        }
        final: State = build_graph(deps).invoke(
            initial, config={"recursion_limit": RECURSION_LIMIT}
        )
    except Exception as error:
        emit(ev.Failed(error=f"{type(error).__name__}: {error}"))
        raise
    return final, tracker, time.perf_counter() - started, emit


def exploration_of(state: State, tracker: BudgetTracker) -> Exploration:
    return Exploration(
        question=state["question"],
        route=state["route"],
        rounds=state.get("rounds", []),
        usage=tracker.usage,
        stop_reason=state.get("stop") or "max_rounds",
        budget=tracker.summary(),
    )


def run_exploration(ws: Workspace, llm: LLM, question: str, **kwargs: Any) -> Exploration:
    state, tracker, _, emit = run(ws, llm, question, want_answer=False, **kwargs)
    result = exploration_of(state, tracker)
    emit(ev.Finished(stop_reason=result.stop_reason))
    return result


def answer_summary(answer: Answer) -> dict[str, Any]:
    """The answer without the exploration: consumers already received it event by event."""
    data = answer.model_dump(mode="json", exclude={"exploration"})
    data["route"] = answer.exploration.route.model_dump(mode="json") | {
        "route": answer.exploration.route.route
    }
    data["rounds"] = len(answer.exploration.rounds)
    data["stop_reason"] = answer.exploration.stop_reason
    return data


def run_answer(ws: Workspace, llm: LLM, question: str, **kwargs: Any) -> Answer:
    state, tracker, seconds, emit = run(ws, llm, question, want_answer=True, **kwargs)
    checked = state["checked"]
    answer = Answer(
        question=question,
        direct_answer=state["draft"].direct_answer,
        claims=[c for c in checked if c.verdict != "unsupported"],
        removed=[c for c in checked if c.verdict == "unsupported"],
        caveats=state["draft"].caveats,
        insufficient=state["draft"].insufficient,
        repaired=bool(state.get("repaired")),
        exploration=exploration_of(state, tracker),
        usage=tracker.usage,
        latency_s=round(seconds, 1),
        budget=tracker.summary(),
    )
    emit(ev.Finished(stop_reason=answer.exploration.stop_reason, answer=answer_summary(answer)))
    return answer


__all__ = ["Deps", "State", "build_graph", "mermaid", "run", "run_answer", "run_exploration"]
