from typing import Any

import anyio
import pytest

from agentic_rag import tools
from agentic_rag.config import Settings
from agentic_rag.mcp_server import build_server
from agentic_rag.workspace import Workspace

from .test_agent_m3 import ConstReranker, ScriptedLLM, _route
from .test_agent_m5 import code, draft, verdicts


def _server(ws: Workspace, llm: ScriptedLLM | None = None) -> Any:
    return build_server(
        Settings(_env_file=None, index="sample"),  # type: ignore[call-arg]
        ws=ws,
        llm=llm or ScriptedLLM(),
        reranker=ConstReranker(5.0),
        warm_in_background=False,
    )


def _call(server: Any, name: str, args: dict[str, Any]) -> str:
    result = anyio.run(server.call_tool, name, args)
    return "\n".join(block.text for block in result.content)


def test_lists_six_tools_with_honest_annotations(sample_ws: Workspace) -> None:
    listed = {t.name: t for t in anyio.run(_server(sample_ws).list_tools)}
    assert set(listed) == {
        "semantic_search",
        "exact_search",
        "symbol_graph",
        "git_history",
        "read_source",
        "ask",
    }
    for name in ["semantic_search", "exact_search", "symbol_graph", "git_history", "read_source"]:
        assert listed[name].annotations.read_only_hint is True
        assert listed[name].annotations.open_world_hint is False  # local index only
    assert listed["ask"].annotations.open_world_hint is True  # calls a model API
    assert "few US cents" in (listed["ask"].description or "")
    schema = listed["symbol_graph"].input_schema
    assert "callers" in str(schema["properties"]["relation"])


@pytest.mark.parametrize(
    ("name", "args", "expected"),
    [
        ("exact_search", {"term": "REGISTRY"}, lambda ws: tools.exact_search(ws, "REGISTRY")),
        (
            "symbol_graph",
            {"symbol": "normalize", "relation": "callers"},
            lambda ws: tools.symbol_graph(ws, "normalize", "callers"),
        ),
        (
            "git_history",
            {"target": "src/shop/util.py"},
            lambda ws: tools.git_history(ws, "src/shop/util.py"),
        ),
        (
            "read_source",
            {"path": "src/shop/util.py", "start_line": 5, "end_line": 6},
            lambda ws: tools.read_source(ws, "src/shop/util.py", 5, 6),
        ),
    ],
)
def test_tools_return_what_the_cli_prints(
    sample_ws: Workspace, name: str, args: dict[str, Any], expected: Any
) -> None:
    assert _call(_server(sample_ws), name, args) == expected(sample_ws).render()


def test_semantic_search_clamps_k(sample_ws: Workspace) -> None:
    text = _call(_server(sample_ws), "semantic_search", {"query": "normalize", "k": 999})
    assert text.count("\n[") + text.startswith("[") <= 15


def test_ask_runs_the_agent(sample_ws: Workspace) -> None:
    llm = ScriptedLLM(
        _route("lookup"),
        draft(("`normalize` upper-cases the SKU.", [code("src/shop/util.py", 5, 6)])),
        verdicts((0, "supported")),
    )
    text = _call(_server(sample_ws, llm), "ask", {"question": "What does normalize do?"})
    assert text.startswith("It upper-cases the SKU.")
    assert "[src/shop/util.py:5-6]" in text


def test_manifest_resource(sample_ws: Workspace) -> None:
    contents = anyio.run(_server(sample_ws).read_resource, "index://manifest")
    text = "".join(getattr(c, "content", "") or getattr(c, "text", "") for c in contents)
    assert '"name": "sample"' in text
