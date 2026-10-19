"""v1.1: read the code that pointer-only evidence points at, before deciding it's enough."""

from agentic_rag.agent.budget import Budget
from agentic_rag.agent.calls import (
    ExactSearch,
    Observation,
    ReadSource,
    SemanticSearch,
    SymbolGraph,
    execute,
)
from agentic_rag.agent.follow_up import MAX_READS, follow_up_reads
from agentic_rag.agent.options import FULL, AgentOptions
from agentic_rag.evaluation.configs import CONFIGS
from agentic_rag.tools.semantic import SearchHit, SearchResult
from agentic_rag.workspace import Workspace

from .test_agent_m3 import CALLERS, ScriptedLLM, _plan, _route, run, sufficiency


def _spans(reads: list[ReadSource]) -> list[tuple[str, int, int]]:
    return [(r.path, r.start_line, r.end_line) for r in reads]


def test_callers_edge_reads_the_caller_around_the_call(sample_ws: Workspace) -> None:
    obs = execute(
        sample_ws, SymbolGraph(tool="symbol_graph", symbol="normalize", relation="callers")
    )
    spans = _spans(follow_up_reads(sample_ws, [obs], []))
    assert ("src/shop/util.py", 1, 2) in spans  # helper's body, where it calls normalize


def test_grep_hit_reads_the_enclosing_function(sample_ws: Workspace) -> None:
    grep = ExactSearch(
        tool="exact_search",
        term="strip().upper()",
        whole_word=False,
        path_prefix=None,
        include_tests=False,
    )
    spans = _spans(follow_up_reads(sample_ws, [execute(sample_ws, grep)], []))
    assert spans[0] == ("src/shop/util.py", 5, 6)  # normalize, not just the matching line


def test_reads_are_capped_and_never_repeat_earlier_reads(sample_ws: Workspace) -> None:
    obs = execute(
        sample_ws, SymbolGraph(tool="symbol_graph", symbol="normalize", relation="callers")
    )
    first = follow_up_reads(sample_ws, [obs], [])
    assert 0 < len(first) <= MAX_READS
    earlier = [execute(sample_ws, r) for r in first]
    assert follow_up_reads(sample_ws, [obs], earlier) == []


def test_follow_up_reads_run_in_the_same_round_and_are_not_replanned(sample_ws: Workspace) -> None:
    llm = ScriptedLLM(_route(), _plan([CALLERS]), sufficiency(True))
    result = run(sample_ws, llm, "who calls normalize?")
    [only] = result.rounds
    tools = [o.call.tool for o in only.observations]
    assert tools[0] == "symbol_graph" and "read_source" in tools[1:]
    assert llm.replies == []  # exactly route, plan, sufficiency: the reads cost no model call


def test_switch_and_defaults() -> None:
    assert FULL.follow_up and FULL.grading == "rerank_only"
    assert CONFIGS["no_follow_up"].options == AgentOptions(follow_up=False)
    assert CONFIGS["llm_grading"].options.grading == "full"


# ---- PR #14 review --------------------------------------------------------------------------


def _truncated_search(paths: list[str]) -> Observation:
    """A semantic_search observation whose hits were all cut off (each has more lines)."""
    call = SemanticSearch(tool="semantic_search", query="q", scope="all", include_tests=False)
    hits = [
        SearchHit(
            chunk_id=f"c{i}",
            path=p,
            start_line=1,
            end_line=20,
            title=p,
            kind="code",
            score=1.0,
            text="...",
            more_lines=10,
        )
        for i, p in enumerate(paths)
    ]
    return Observation(
        call=call, text="", elapsed_ms=1, search=SearchResult(query="q", scope="all", hits=hits)
    )


def test_graph_edges_get_reads_before_semantic_tails(sample_ws: Workspace) -> None:
    semantic = _truncated_search(["src/shop/cart.py", "src/shop/base.py", "README.md"])
    callers = execute(
        sample_ws, SymbolGraph(tool="symbol_graph", symbol="normalize", relation="callers")
    )
    reads = follow_up_reads(sample_ws, [semantic, callers], [])  # semantic arrives first
    assert callers.graph is not None
    edges = [r.symbol for r in callers.graph.related if r.symbol is not None]
    callers_files = {s.path for s in edges}
    assert len(reads) == MAX_READS
    # the edges take the slots first, although their observation came second
    first_edges = min(len(edges), MAX_READS)
    assert all(r.path in callers_files for r in reads[:first_edges])
    assert ("src/shop/util.py", 1, 2) in _spans(reads)  # helper, where it calls normalize


def test_code_shown_by_a_semantic_hit_is_not_read_again(sample_ws: Workspace) -> None:
    call = SemanticSearch(tool="semantic_search", query="q", scope="code", include_tests=False)
    full = SearchHit(
        chunk_id="n",
        path="src/shop/util.py",
        start_line=5,
        end_line=6,
        title="normalize",
        kind="code",
        score=1.0,
        text="def normalize(sku):\n    return sku.strip().upper()",
    )
    semantic = Observation(
        call=call, text="", elapsed_ms=1, search=SearchResult(query="q", scope="code", hits=[full])
    )
    grep = ExactSearch(
        tool="exact_search",
        term="strip().upper()",
        whole_word=False,
        path_prefix=None,
        include_tests=False,
    )
    assert follow_up_reads(sample_ws, [execute(sample_ws, grep)], [semantic]) == []


def test_no_follow_up_reads_once_the_budget_is_spent(sample_ws: Workspace) -> None:
    llm = ScriptedLLM(_route(), _plan([CALLERS]))
    tight = Budget(max_tokens=10**9, max_seconds=10**6, max_cost_usd=0.0015)  # 2 calls = $0.002
    result = run(sample_ws, llm, "who calls normalize?", budget=tight)
    [only] = result.rounds
    assert [o.call.tool for o in only.observations] == ["symbol_graph"]
    assert result.stop_reason == "budget_cost"


def test_planner_reads_overlapping_what_was_read_are_skipped(sample_ws: Workspace) -> None:
    llm = ScriptedLLM(
        _route(),
        _plan([CALLERS]),
        sufficiency(False),
        _plan(
            [{"tool": "read_source", "path": "src/shop/util.py", "start_line": 1, "end_line": 3}]
        ),
        sufficiency(True),
    )
    result = run(sample_ws, llm, "who calls normalize?")
    # round 1's follow-up already read util.py:1-2, so 1-3 is a repeat with a different range
    assert result.rounds[1].skipped_repeats == 1


def test_rerank_only_makes_no_model_call_and_isnt_run_twice() -> None:
    from agentic_rag.evaluation.configs import CONFIGS, DEFAULT_SUITE

    assert CONFIGS["rerank_only"].options == CONFIGS["full"].options
    assert "rerank_only" not in DEFAULT_SUITE
    assert {"naive", "full", "llm_grading", "no_follow_up"} <= set(DEFAULT_SUITE)


def test_eval_run_rejects_an_unknown_split() -> None:
    from typer.testing import CliRunner

    from agentic_rag.cli import app

    result = CliRunner().invoke(app, ["eval", "run", "x", "--split", "held-out"])
    assert result.exit_code != 0
