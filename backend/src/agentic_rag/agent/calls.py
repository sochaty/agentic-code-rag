"""Typed tool calls the planner emits, and their execution.

The planner can only ask for these shapes (the JSON schema enforces it), so a plan is always
runnable. Each call renders to the same text the CLI prints.
"""

import time
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from agentic_rag import tools
from agentic_rag.tools.exact import GrepResult
from agentic_rag.tools.graph import GraphResult, Relation
from agentic_rag.tools.semantic import Scope, SearchResult
from agentic_rag.workspace import Workspace

# Keeps one noisy search result from flooding the planner's context. read_source is exempt:
# it's already bounded (200 lines), and clipping it once hid the exact lines a run needed.
MAX_OBSERVATION_CHARS = 6000


class SemanticSearch(BaseModel):
    tool: Literal["semantic_search"]
    query: str
    scope: Scope
    include_tests: bool


class ExactSearch(BaseModel):
    tool: Literal["exact_search"]
    term: str
    whole_word: bool
    path_prefix: str | None
    include_tests: bool


class SymbolGraph(BaseModel):
    tool: Literal["symbol_graph"]
    symbol: str
    relation: Relation


class GitHistory(BaseModel):
    tool: Literal["git_history"]
    target: str
    limit: int


class ReadSource(BaseModel):
    tool: Literal["read_source"]
    path: str
    start_line: int
    end_line: int


ToolCall = Annotated[
    SemanticSearch | ExactSearch | SymbolGraph | GitHistory | ReadSource,
    Field(discriminator="tool"),
]

CATALOG = """\
semantic_search(query, scope, include_tests)
  Hybrid meaning + keyword search over code chunks, doc sections and changelog entries.
  scope: "all" | "code" | "docs" | "changelog". Best for "how does X work", concepts, and
  finding where something is implemented when you don't know its name.
exact_search(term, whole_word, path_prefix, include_tests)
  Literal search over every tracked file (code, docs, config, templates). Case-sensitive when
  the term has capitals. Best for identifiers, config keys, error messages, and proving
  something does NOT exist (search several spellings; whole_word avoids partial matches).
symbol_graph(symbol, relation)
  Static call graph. relation: "definition" | "callers" | "callees" | "members" |
  "superclasses" | "subclasses". symbol can be a bare name, `Class.method`, or a full
  qualname. Each result says how it was resolved (exact > receiver > heuristic > ambiguous >
  external > unresolved). Best for "who calls X", "what does X call", class hierarchies.
  Every relation already starts with the symbol's location, signature and docstring, so
  don't request "definition" alongside another relation for the same symbol.
git_history(target, limit)
  Commits touching a file, folder, or symbol (follows the symbol's lines through history).
  Best for "when / why did X change". Pair with semantic_search(scope="changelog").
read_source(path, start_line, end_line)
  Exact numbered lines (max 200). Use after another tool points at a location and you need
  the actual code to answer or cite. Read the symbol's own line range (other tools report
  it) rather than a wide window around it."""


def call_key(call: ToolCall) -> str:
    return call.model_dump_json()


class Observation(BaseModel):
    call: ToolCall
    text: str
    error: str | None = None
    elapsed_ms: int
    # Structured results, internal only (serialised events already carry `text`): semantic
    # hits so grading can filter them and re-render; grep hits and graph edges so the agent
    # can read the code they point at (agent/follow_up.py).
    search: SearchResult | None = Field(default=None, exclude=True)
    grep: GrepResult | None = Field(default=None, exclude=True)
    graph: GraphResult | None = Field(default=None, exclude=True)

    @property
    def key(self) -> str:
        return call_key(self.call)

    def render(self) -> str:
        args = ", ".join(f"{k}={v!r}" for k, v in self.call.model_dump().items() if k != "tool")
        return f"{self.call.tool}({args})\n{self.error or self.text}"


def execute(ws: Workspace, call: ToolCall) -> Observation:
    started = time.perf_counter()
    search: SearchResult | None = None
    grep: GrepResult | None = None
    graph: GraphResult | None = None
    try:
        match call:
            case SemanticSearch():
                search = tools.semantic_search(
                    ws, call.query, call.scope, include_tests=call.include_tests
                )
                text = search.render()
            case ExactSearch():
                grep = tools.exact_search(
                    ws,
                    call.term,
                    include_tests=call.include_tests,
                    path_prefix=call.path_prefix,
                    whole_word=call.whole_word,
                )
                text = grep.render()
            case SymbolGraph():
                graph = tools.symbol_graph(ws, call.symbol, call.relation)
                text = graph.render()
            case GitHistory():
                text = tools.git_history(ws, call.target, max(1, min(call.limit, 30))).render()
            case ReadSource():
                text = tools.read_source(ws, call.path, call.start_line, call.end_line).render()
        error = None
    except Exception as exc:  # a failing tool is an observation, not a crash
        text, error = "", f"{call.tool} failed: {type(exc).__name__}: {exc}"
    if len(text) > MAX_OBSERVATION_CHARS and not isinstance(call, ReadSource):
        text = (
            text[:MAX_OBSERVATION_CHARS]
            + "\n... [truncated: narrow the search, or read_source the exact lines you need]"
        )
    elapsed = int((time.perf_counter() - started) * 1000)
    return Observation(
        call=call,
        text=text,
        error=error,
        elapsed_ms=elapsed,
        search=search,
        grep=grep,
        graph=graph,
    )
