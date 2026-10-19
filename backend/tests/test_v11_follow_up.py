"""v1.1: read the code that pointer-only evidence points at, before deciding it's enough."""

from agentic_rag.agent.calls import ExactSearch, ReadSource, SymbolGraph, execute
from agentic_rag.agent.follow_up import MAX_READS, follow_up_reads
from agentic_rag.agent.options import FULL, AgentOptions
from agentic_rag.evaluation.configs import CONFIGS
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
