import json
from collections.abc import Sequence
from typing import Any

import pytest
from pydantic import ValidationError

from agentic_rag import tools
from agentic_rag.agent.budget import Budget
from agentic_rag.agent.calls import ExactSearch, GitHistory, ReadSource, SymbolGraph, execute
from agentic_rag.agent.explore import Exploration, explore
from agentic_rag.agent.options import AgentOptions
from agentic_rag.agent.planner import Plan
from agentic_rag.agent.router import Route
from agentic_rag.agent.structured import complete_structured, extract_json, strict_schema
from agentic_rag.llm import Completion, Effort, Usage
from agentic_rag.workspace import Workspace


class ScriptedLLM:
    """Replies with queued texts in order and records every request."""

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.requests: list[dict[str, Any]] = []

    def complete(
        self,
        *,
        model: str,
        system: str,
        messages: Sequence[dict[str, Any]],
        max_tokens: int = 16000,
        effort: Effort | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> Completion:
        self.requests.append(
            {"model": model, "system": system, "messages": list(messages), "schema": json_schema}
        )
        usage = Usage(input_tokens=100, output_tokens=10, cost_usd=0.001, calls=1)
        return Completion(text=self.replies.pop(0), model=model, usage=usage)


def _route(category: str = "call_graph") -> str:
    return json.dumps({"category": category, "reason": "test"})


def _plan(steps: list[dict[str, Any]], done: bool = False) -> str:
    return json.dumps(
        {
            "sub_questions": ["who calls normalize?"],
            "steps": [{"call": s, "purpose": "test"} for s in steps],
            "done": done,
            "rationale": "test plan",
        }
    )


NO_FOLLOW_UP = AgentOptions(follow_up=False)
CALLERS = {"tool": "symbol_graph", "symbol": "normalize", "relation": "callers"}
GREP = {
    "tool": "exact_search",
    "term": "normalize",
    "whole_word": True,
    "path_prefix": None,
    "include_tests": False,
}


# ---- structured output ------------------------------------------------------------------


def test_strict_schema_closes_objects_and_rewrites_unions() -> None:
    schema = strict_schema(Plan)
    text = json.dumps(schema)
    assert '"oneOf"' not in text and '"const"' not in text and '"default"' not in text
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["sub_questions", "steps", "done", "rationale"]
    exact = schema["$defs"]["ExactSearch"]
    assert exact["required"] == ["tool", "term", "whole_word", "path_prefix", "include_tests"]
    assert exact["properties"]["tool"]["enum"] == ["exact_search"]


def test_extract_json_tolerates_fences_and_prose() -> None:
    assert extract_json('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert extract_json('Sure! {"a": 1} hope that helps') == '{"a": 1}'


def test_structured_output_repairs_once_then_gives_up() -> None:
    llm = ScriptedLLM('{"category": "nonsense"}', _route())
    route, usage = complete_structured(
        llm, model="m", system="s", user="u", schema=Route, effort="low"
    )
    assert route.route == "agentic"
    assert usage.calls == 2
    assert llm.requests[0]["schema"]["additionalProperties"] is False
    assert "invalid" in llm.requests[1]["messages"][-1]["content"]

    with pytest.raises(ValidationError):
        complete_structured(ScriptedLLM("{}", "{}"), model="m", system="s", user="u", schema=Route)


# ---- tool calls -------------------------------------------------------------------------


def test_execute_renders_like_the_cli(sample_ws: Workspace) -> None:
    obs = execute(
        sample_ws, SymbolGraph(tool="symbol_graph", symbol="normalize", relation="callers")
    )
    assert obs.error is None
    assert obs.text == tools.symbol_graph(sample_ws, "normalize", "callers").render()
    assert obs.render().startswith("symbol_graph(symbol='normalize', relation='callers')")


def test_execute_turns_failures_into_observations(sample_ws: Workspace) -> None:
    bad = execute(sample_ws, GitHistory(tool="git_history", target="src/shop", limit=0))
    assert bad.error is None and "Add VERSION" in bad.text  # limit clamped to >= 1
    escape = execute(
        sample_ws, ReadSource(tool="read_source", path="../x", start_line=1, end_line=2)
    )
    assert "outside the repository" in escape.text


def test_whole_word_exact_search(sample_ws: Workspace) -> None:
    partial = tools.exact_search(sample_ws, "Cart", include_tests=False)
    word = tools.exact_search(sample_ws, "Cart", include_tests=False, whole_word=True)
    assert word.total_matches <= partial.total_matches
    sub = ExactSearch(
        tool="exact_search", term="art", whole_word=True, path_prefix=None, include_tests=True
    )
    assert "No literal matches" in execute(sample_ws, sub).text  # "Cart" doesn't count


# ---- explore loop -----------------------------------------------------------------------

BIG = Budget(max_tokens=10**9, max_seconds=10**6, max_cost_usd=10**6)


class ConstReranker:
    model_name = "const"

    def __init__(self, score: float) -> None:
        self.value = score

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        return [self.value] * len(passages)


def run(ws: Workspace, llm: ScriptedLLM, question: str, **kwargs: Any) -> Exploration:
    return explore(
        ws,
        llm,
        question,
        cheap_model="c",
        heavy_model="h",
        budget=kwargs.pop("budget", BIG),
        reranker=kwargs.pop("reranker", ConstReranker(5.0)),
        **kwargs,
    )


def sufficiency(sufficient: bool) -> str:
    return json.dumps(
        {
            "sub_answers": [
                {
                    "sub_question": "who calls normalize?",
                    "answered": sufficient,
                    "evidence": [1] if sufficient else [],
                    "missing": "" if sufficient else "the next hop",
                }
            ],
            "sufficient": sufficient,
        }
    )


def test_direct_route_runs_one_search(sample_ws: Workspace) -> None:
    llm = ScriptedLLM(_route("lookup"))
    result = run(sample_ws, llm, "what does normalize do?")
    assert [r.plan for r in result.rounds] == [None]
    assert result.observations[0].call.tool == "semantic_search"
    assert result.stop_reason == "direct"
    assert llm.requests[0]["model"] == "c"  # router on the cheap model


def test_agentic_rounds_feed_observations_back_and_skip_repeats(sample_ws: Workspace) -> None:
    llm = ScriptedLLM(
        _route(),
        _plan([CALLERS, GREP, CALLERS]),  # duplicate within a round
        sufficiency(False),
        _plan([CALLERS, {**CALLERS, "symbol": "helper"}]),  # repeat from round 1 + one new
        sufficiency(False),
        _plan([], done=True),
    )
    # follow-up reads are tested in test_v11_follow_up.py; here only the planner's calls count
    result = run(sample_ws, llm, "who calls normalize?", options=NO_FOLLOW_UP)

    assert [len(r.observations) for r in result.rounds] == [2, 1, 0]
    assert [r.skipped_repeats for r in result.rounds] == [1, 1, 0]
    assert [req["model"] for req in llm.requests] == ["c", "h", "c", "h", "c", "h"]
    second_plan_prompt = llm.requests[3]["messages"][0]["content"]
    assert "Round: 2" in second_plan_prompt and "shop.util.helper" in second_plan_prompt
    assert result.usage.calls == 6
    assert result.stop_reason == "planner_done"
    assert "planner: done" in result.render()


def test_round_limit_stops_the_loop(sample_ws: Workspace) -> None:
    llm = ScriptedLLM(
        _route(),
        _plan([CALLERS]),
        sufficiency(False),
        _plan([GREP]),
        _plan([{**GREP, "term": "helper"}]),
    )
    result = run(sample_ws, llm, "q", max_rounds=2)
    assert len(result.rounds) == 2
    assert result.stop_reason == "max_rounds"
    assert len(llm.replies) == 1  # third plan never requested; no check after the last round


def test_code_not_the_model_decides_the_route() -> None:
    from agentic_rag.agent.router import Route

    assert "route" not in strict_schema(Route)["properties"]  # the model can't pick it
    direct = {"lookup", "conceptual"}
    for category in [
        "lookup",
        "conceptual",
        "identifier",
        "call_graph",
        "history",
        "existence",
        "multi_part",
    ]:
        route = Route.model_validate({"category": category, "reason": "r"})
        assert route.route == ("direct" if category in direct else "agentic"), category
