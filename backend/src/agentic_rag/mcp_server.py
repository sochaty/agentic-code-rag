"""MCP server: the same five tools (and the whole agent) for Claude Code, Cursor, and friends.

    acr mcp                      # stdio — what desktop clients launch
    acr mcp --transport http     # streamable HTTP on :8001/mcp

The read-only tools cost nothing: they search the local index. `ask` runs the full agent
and calls a model API. On stdio, stdout belongs to the protocol — nothing here prints.
"""

import json
import threading
from collections.abc import Callable
from typing import Literal

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from agentic_rag import tools
from agentic_rag.agent.budget import Budget
from agentic_rag.config import Settings
from agentic_rag.llm import LLM, make_llm
from agentic_rag.search.rerank import Reranker
from agentic_rag.tools.graph import Relation
from agentic_rag.tools.semantic import Scope
from agentic_rag.workspace import Workspace

MAX_K = 15

INSTRUCTIONS = """Read-only tools over one indexed git repository ({index}), plus `ask`.

Pick the tool by question shape:
- "who calls X / what does X call / class hierarchy" -> symbol_graph
- identifiers, config keys, error messages, "does X exist?" -> exact_search (try spellings)
- "how does X work" / unknown names -> semantic_search
- "when / why did X change" -> git_history on the symbol or file
- then read_source for the exact lines to quote.
`ask` runs a full research agent (several model calls, a few US cents) and returns an answer
whose every claim is verified against cited file:line ranges. Prefer the cheap tools when you
can do the reasoning yourself."""

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False)
CALLS_MODEL = ToolAnnotations(read_only_hint=True, idempotent_hint=False, open_world_hint=True)


def build_server(
    settings: Settings,
    *,
    ws: Workspace | None = None,
    llm: LLM | None = None,
    reranker: Reranker | None = None,
    warm_in_background: bool = True,
) -> MCPServer:
    """Pass `ws`/`llm`/`reranker` to inject them (tests); otherwise built on first use."""
    lock = threading.Lock()
    loaded = _Loaded(ws, llm)

    def workspace() -> Workspace:
        with lock:
            if loaded.ws is None:
                opened = Workspace.open(settings.index, settings)
                opened.warm_up()
                loaded.ws = opened
            return loaded.ws

    def model() -> LLM:
        with lock:
            if loaded.llm is None:
                loaded.llm = make_llm(settings)
            return loaded.llm

    if ws is None and warm_in_background:
        # Clients expect a fast handshake: load the index and models while they connect.
        threading.Thread(target=workspace, daemon=True).start()

    async def off_loop(work: Callable[[], str]) -> str:
        return await anyio.to_thread.run_sync(work)

    server = MCPServer(
        name="agentic-code-rag",
        instructions=INSTRUCTIONS.format(index=settings.index),
    )

    @server.tool(annotations=READ_ONLY)
    async def semantic_search(
        query: str,
        scope: Scope = "all",
        k: int = 6,
        include_tests: bool = False,
    ) -> str:
        """Hybrid meaning + keyword search over code chunks, doc sections and changelog entries.

        scope: "all" | "code" | "docs" | "changelog". Best for "how does X work" and for finding
        code when you don't know its name. Results show path:start-end for every hit.
        """
        k = max(1, min(k, MAX_K))
        return await off_loop(
            lambda: tools.semantic_search(workspace(), query, scope, k, include_tests).render()
        )

    @server.tool(annotations=READ_ONLY)
    async def exact_search(
        term: str,
        whole_word: bool = False,
        path_prefix: str | None = None,
        include_tests: bool = True,
    ) -> str:
        """Literal search over every tracked text file (code, docs, config, templates).

        Case-sensitive when the term has capitals. Reports how many files were searched, so
        "no matches" is evidence of absence. whole_word avoids partial matches.
        """
        return await off_loop(
            lambda: tools.exact_search(
                workspace(),
                term,
                include_tests=include_tests,
                path_prefix=path_prefix,
                whole_word=whole_word,
            ).render()
        )

    @server.tool(annotations=READ_ONLY)
    async def symbol_graph(symbol: str, relation: Relation = "definition") -> str:
        """Static call graph: "definition" | "callers" | "callees" | "members" | "superclasses" |
        "subclasses".

        symbol may be a bare name, `Class.method` or a full qualname. Every edge says how it
        was resolved: exact > receiver > heuristic > ambiguous > external > unresolved.
        """
        return await off_loop(lambda: tools.symbol_graph(workspace(), symbol, relation).render())

    @server.tool(annotations=READ_ONLY)
    async def git_history(target: str, limit: int = 10) -> str:
        """Commits that touched a file, folder or symbol, newest first.

        For a symbol it follows the symbol's own lines through history and shows the lines
        each commit changed there.
        """
        limit = max(1, min(limit, 30))
        return await off_loop(lambda: tools.git_history(workspace(), target, limit).render())

    @server.tool(annotations=READ_ONLY)
    async def read_source(path: str, start_line: int = 1, end_line: int | None = None) -> str:
        """Exact numbered lines from a repository file (at most 200 per call)."""
        return await off_loop(
            lambda: tools.read_source(workspace(), path, start_line, end_line).render()
        )

    @server.tool(annotations=CALLS_MODEL)
    async def ask(question: str, max_rounds: int = 3) -> str:
        """Research a question with the full agent and return a verified, cited answer.

        Plans tool calls, grades evidence, writes claims and checks each against the cited
        lines. Calls the configured model provider: several model calls, a few US cents.
        """
        from agentic_rag.agent.graph import run_answer

        budget = Budget(
            max_tokens=settings.budget_max_tokens,
            max_seconds=settings.budget_max_seconds,
            max_cost_usd=settings.budget_max_cost_usd,
        )

        def work() -> str:
            answer = run_answer(
                workspace(),
                model(),
                question,
                cheap_model=settings.cheap_model,
                heavy_model=settings.heavy_model,
                budget=budget,
                max_rounds=max(1, min(max_rounds, 3)),
                reranker=reranker,
            )
            return answer.render()

        return await off_loop(work)

    @server.resource("index://manifest", mime_type="application/json")
    def manifest() -> str:
        """What this server indexes: repository, ref, languages, symbol and commit counts."""
        return json.dumps(workspace().index.manifest, indent=2)

    return server


Transport = Literal["stdio", "http"]


class _Loaded:
    """What's been loaded so far; filled lazily so the MCP handshake stays fast."""

    def __init__(self, ws: Workspace | None, llm: LLM | None) -> None:
        self.ws = ws
        self.llm = llm


def serve(settings: Settings, transport: Transport, host: str, port: int) -> None:
    server = build_server(settings)
    if transport == "stdio":
        server.run("stdio")
    else:
        server.run("streamable-http", host=host, port=port)
