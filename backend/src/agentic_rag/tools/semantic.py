"""semantic_search: find code and docs by meaning (hybrid dense + BM25)."""

from typing import Literal

from pydantic import BaseModel

from agentic_rag.ingest.models import ChunkKind
from agentic_rag.workspace import Workspace

Scope = Literal["all", "code", "docs", "changelog"]
SNIPPET_LINES = 40
_KINDS: dict[Scope, set[ChunkKind] | None] = {
    "all": None,
    "code": {"code"},
    "docs": {"doc"},
    "changelog": {"changelog"},
}


class SearchHit(BaseModel):
    chunk_id: str
    path: str
    start_line: int
    end_line: int
    title: str
    kind: ChunkKind
    score: float
    text: str
    more_lines: int = 0


class SearchResult(BaseModel):
    query: str
    scope: Scope
    hits: list[SearchHit]

    def render(self) -> str:
        if not self.hits:
            return f"No results for {self.query!r} in {self.scope}."
        blocks = []
        for i, hit in enumerate(self.hits, 1):
            block = f"[{i}] {hit.path}:{hit.start_line}-{hit.end_line}  {hit.title}  ({hit.kind})\n"
            block += hit.text
            if hit.more_lines:
                shown_to = hit.end_line - hit.more_lines
                block += (
                    f"\n... {hit.more_lines} more lines: "
                    f"read_source({hit.path!r}, {shown_to + 1}, {hit.end_line})"
                )
            blocks.append(block)
        return "\n\n".join(blocks)


def semantic_search(
    ws: Workspace, query: str, scope: Scope = "all", k: int = 6, include_tests: bool = False
) -> SearchResult:
    hits = []
    for scored in ws.search.hybrid(query, k, _KINDS[scope], include_tests):
        lines = scored.chunk.text.splitlines()
        hits.append(
            SearchHit(
                chunk_id=scored.chunk.id,
                path=scored.chunk.path,
                start_line=scored.chunk.start_line,
                end_line=scored.chunk.end_line,
                title=scored.chunk.title,
                kind=scored.chunk.kind,
                score=round(scored.score, 4),
                text="\n".join(lines[:SNIPPET_LINES]),
                more_lines=max(len(lines) - SNIPPET_LINES, 0),
            )
        )
    return SearchResult(query=query, scope=scope, hits=hits)
