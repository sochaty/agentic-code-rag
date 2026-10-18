"""The five tools the agent (and the CLI, and the MCP server) use to read a codebase.

Each returns a typed result with `render()`: the exact text a model sees as the tool output.
"""

from agentic_rag.tools.exact import GrepResult, exact_search
from agentic_rag.tools.graph import GraphResult, find_symbols, symbol_graph
from agentic_rag.tools.history import HistoryResult, git_history
from agentic_rag.tools.semantic import SearchResult, semantic_search
from agentic_rag.tools.source import SourceRange, read_source

__all__ = [
    "GraphResult",
    "GrepResult",
    "HistoryResult",
    "SearchResult",
    "SourceRange",
    "exact_search",
    "find_symbols",
    "git_history",
    "read_source",
    "semantic_search",
    "symbol_graph",
]
