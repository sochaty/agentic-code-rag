import json
from collections.abc import Sequence

import pytest

from agentic_rag.agent.budget import Budget, BudgetTracker
from agentic_rag.agent.calls import SemanticSearch, execute
from agentic_rag.agent.grade import IRRELEVANT_AT, RELEVANT_AT, filter_observation, grade_hits
from agentic_rag.agent.options import AgentOptions
from agentic_rag.llm import Usage
from agentic_rag.search.rerank import OverlapReranker
from agentic_rag.workspace import Workspace

from .test_agent_m3 import (
    CALLERS,
    ConstReranker,
    ScriptedLLM,
    _plan,
    _route,
    run,
    sufficiency,
)

SEMANTIC = {
    "tool": "semantic_search",
    "query": "normalize sku",
    "scope": "code",
    "include_tests": False,
}


class ByTitleReranker:
    """Scores passages by whether their first line (the chunk title) is in `scores`."""

    model_name = "by-title"

    def __init__(self, scores: dict[str, float], default: float) -> None:
        self.scores, self.default = scores, default

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        return [self.scores.get(p.splitlines()[0], self.default) for p in passages]


def verdicts(*items: tuple[int, str]) -> str:
    return json.dumps({"verdicts": [{"index": i, "verdict": v} for i, v in items]})


# ---- budget -----------------------------------------------------------------------------


def test_budget_tracker_reports_which_limit_ran_out() -> None:
    tracker = BudgetTracker(Budget(max_tokens=1000, max_seconds=3600, max_cost_usd=0.01))
    assert tracker.exhausted() is None
    tracker.charge(Usage(input_tokens=600, output_tokens=500, cost_usd=0.001))
    assert tracker.exhausted() == "tokens"
    cost = BudgetTracker(Budget(max_tokens=10**9, max_seconds=3600, max_cost_usd=0.01))
    cost.charge(Usage(cost_usd=0.02))
    assert cost.exhausted() == "cost"
    assert "$0.0200/$0.01" in cost.summary()


def test_budget_stops_before_the_planner(sample_ws: Workspace) -> None:
    llm = ScriptedLLM(_route(), _plan([CALLERS]))
    tiny = Budget(max_tokens=50, max_seconds=3600, max_cost_usd=1.0)  # the router alone uses 110
    result = run(sample_ws, llm, "who calls normalize?", budget=tiny)
    assert result.stop_reason == "budget_tokens"
    assert result.rounds == []
    assert len(llm.replies) == 1  # planner never called


# ---- sufficiency ------------------------------------------------------------------------


def test_sufficient_evidence_stops_before_another_heavy_call(sample_ws: Workspace) -> None:
    llm = ScriptedLLM(_route(), _plan([CALLERS]), sufficiency(True), _plan([CALLERS]))
    result = run(sample_ws, llm, "who calls normalize?")
    assert result.stop_reason == "sufficient"
    assert len(result.rounds) == 1
    assert result.rounds[0].sufficiency is not None and result.rounds[0].sufficiency.sufficient
    assert [req["model"] for req in llm.requests] == ["c", "h", "c"]  # check ran on cheap model
    assert "1/1 sub-questions answered" in result.render()


# ---- grading ----------------------------------------------------------------------------


def test_reranker_settles_clear_cases_without_an_llm(sample_ws: Workspace) -> None:
    llm = ScriptedLLM(_route(), _plan([SEMANTIC], done=True))
    result = run(sample_ws, llm, "q", reranker=ConstReranker(RELEVANT_AT + 1))
    grades = result.rounds[0].grades
    assert grades and all(g.verdict == "relevant" and g.by == "reranker" for g in grades)
    assert len(llm.requests) == 2  # router + planner only


def test_borderline_hits_go_to_one_batched_llm_call(sample_ws: Workspace) -> None:
    obs = execute(sample_ws, SemanticSearch.model_validate(SEMANTIC))
    assert obs.search is not None
    titles = [h.title for h in obs.search.hits]
    assert len(titles) >= 3
    reranker = ByTitleReranker({titles[0]: 7.0, titles[1]: -9.0}, default=0.0)  # rest borderline
    borderline = len(titles) - 2
    llm = ScriptedLLM(
        verdicts(*[(i, "irrelevant" if i == 0 else "partial") for i in range(borderline)])
    )

    grades, usage = grade_hits(llm, "c", reranker, "question", "normalize sku", obs.search.hits)

    assert usage.calls == 1
    assert [(g.verdict, g.by) for g in grades[:3]] == [
        ("relevant", "reranker"),
        ("irrelevant", "reranker"),
        ("irrelevant", "llm"),
    ]
    filtered = filter_observation(obs, grades)
    assert filtered.search is not None and len(filtered.search.hits) == len(titles) - 2
    assert "2 hit(s) graded irrelevant and removed" in filtered.text


def test_without_budget_borderline_hits_are_kept_unverified(sample_ws: Workspace) -> None:
    obs = execute(sample_ws, SemanticSearch.model_validate(SEMANTIC))
    assert obs.search is not None
    grades, usage = grade_hits(None, "c", ConstReranker(0.0), "q", "normalize", obs.search.hits)
    assert usage.calls == 0
    assert {(g.verdict, g.by) for g in grades} == {("partial", "unverified")}


def test_all_misses_trigger_one_rewrite(sample_ws: Workspace) -> None:
    llm = ScriptedLLM(
        _route(),
        _plan([SEMANTIC], done=True),
        json.dumps({"query": "upper strip sku"}),  # the rewrite
    )
    # the rewrite is part of LLM grading; the default (rerank_only) makes no model call at all
    result = run(
        sample_ws,
        llm,
        "q",
        reranker=ConstReranker(IRRELEVANT_AT - 1),
        options=AgentOptions(grading="full"),
    )
    rnd = result.rounds[0]
    assert [(r.original, r.rewritten) for r in rnd.rewrites] == [
        ("normalize sku", "upper strip sku")
    ]
    assert rnd.observations[0].call.query == "upper strip sku"  # type: ignore[union-attr]
    assert "graded irrelevant and removed" in rnd.observations[0].text
    assert "rewrite: 'normalize sku' -> 'upper strip sku'" in result.render()


def test_overlap_reranker_orders_by_shared_tokens() -> None:
    scores = OverlapReranker().score("normalize sku", ["def normalize(sku)", "unrelated", "sku"])
    assert scores[0] > scores[2] > scores[1]
    assert scores[0] == pytest.approx(8.0) and scores[1] == pytest.approx(-8.0)


def test_read_source_observations_are_never_clipped(sample_ws: Workspace) -> None:
    from agentic_rag.agent import calls
    from agentic_rag.agent.calls import ReadSource

    original = calls.MAX_OBSERVATION_CHARS
    calls.MAX_OBSERVATION_CHARS = 20  # far smaller than the file
    try:
        read = execute(
            sample_ws,
            ReadSource(tool="read_source", path="src/shop/cart.py", start_line=1, end_line=46),
        )
        grep = execute(sample_ws, SemanticSearch.model_validate(SEMANTIC))
    finally:
        calls.MAX_OBSERVATION_CHARS = original
    assert "truncated" not in read.text and "return fmt(sum(self.items))" in read.text
    assert "read_source the exact lines you need" in grep.text


def test_file_reads_are_cached(sample_ws: Workspace) -> None:
    from pathlib import PurePosixPath

    first = sample_ws.read_lines(PurePosixPath("src/shop/util.py"))
    assert sample_ws.read_lines(PurePosixPath("src/shop/util.py")) is first
    assert sample_ws.read_lines(PurePosixPath("missing.py")) is None
