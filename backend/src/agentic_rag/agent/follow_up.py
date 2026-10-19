"""Read the code that pointer-only evidence points at — deterministic, no model call.

v1's eval showed the agent's partial answers had one cause: it answered from *where* things
are, not *what they say*. A call-graph edge says full_dispatch_request calls dispatch_request
but not that it only does so when preprocess_request returned None; a grep hit gives the line
of an error message but not the import that fails before it; a semantic hit cut off after 40
lines hides the early return in Flask.run. The sufficiency check accepted those pointers as
answers. So after each round, before the check, the agent reads a few of the places its
evidence points at:

- semantic hits that survived grading but were cut off: the rest of the chunk
- exact_search hits: the function around the hit (or the doc section)
- symbol_graph callers: the caller around the call; callees/definition: the symbol's body

At most MAX_READS per round, each at most MAX_SPAN lines, skipping anything already read.
"""

from pathlib import PurePosixPath

from agentic_rag.agent.calls import Observation, ReadSource
from agentic_rag.ingest.models import Symbol
from agentic_rag.workspace import Workspace

MAX_READS = 3
MAX_SPAN = 100  # lines per read; longer bodies are windowed around the line of interest
_BEFORE = 30  # window: lines kept above the line of interest
_GREP_HITS = 4  # grep hits considered per search (the rest are usually repeats)
_EDGES = 3  # graph edges considered per call


Span = tuple[str, int, int]


def _symbols_by_path(ws: Workspace) -> dict[str, list[Symbol]]:
    by_path: dict[str, list[Symbol]] = {}
    for s in ws.index.symbols:
        if s.kind in ("function", "method"):
            by_path.setdefault(s.path, []).append(s)
    return by_path


def _window(path: str, start: int, end: int, focus: int | None) -> Span:
    if end - start + 1 <= MAX_SPAN:
        return (path, start, end)
    top = start if focus is None else max(start, focus - _BEFORE)
    return (path, top, min(end, top + MAX_SPAN - 1))


def _around(ws: Workspace, symbols: dict[str, list[Symbol]], path: str, line: int) -> Span:
    """The innermost function around a line; else the doc section; else a plain window."""
    inside = [s for s in symbols.get(path, []) if s.start_line <= line <= s.end_line]
    if inside:
        s = min(inside, key=lambda s: s.end_line - s.start_line)
        return _window(path, s.start_line, s.end_line, line)
    sections = [
        c
        for c in ws.index.chunks
        if c.path == path and c.kind != "code" and c.start_line <= line <= c.end_line
    ]
    if sections:
        c = min(sections, key=lambda c: c.end_line - c.start_line)
        return _window(path, c.start_line, c.end_line, line)
    return (path, max(1, line - 10), line + 20)


def _pointers(ws: Workspace, obs: Observation, symbols: dict[str, list[Symbol]]) -> list[Span]:
    spans: list[Span] = []
    if obs.search is not None:  # only hits that survived grading
        for hit in obs.search.hits:
            if hit.more_lines:  # the first lines are already in the observation
                rest = hit.end_line - hit.more_lines + 1
                spans.append(_window(hit.path, rest, hit.end_line, None))
    if obs.grep is not None:
        for g in obs.grep.hits[:_GREP_HITS]:
            spans.append(_around(ws, symbols, g.path, g.line))
    if obs.graph is not None and obs.graph.symbol is not None:
        target = obs.graph.symbol
        if obs.graph.relation == "callers":
            for rel in obs.graph.related[:_EDGES]:
                if rel.symbol is not None:
                    focus = rel.line or rel.symbol.start_line
                    spans.append(
                        _window(rel.symbol.path, rel.symbol.start_line, rel.symbol.end_line, focus)
                    )
        elif obs.graph.relation in ("callees", "definition"):
            spans.append(_window(target.path, target.start_line, target.end_line, None))
    return spans


def _covered(span: Span, seen: list[Span]) -> bool:
    path, start, end = span
    for other_path, other_start, other_end in seen:
        if other_path == path:
            overlap = min(end, other_end) - max(start, other_start) + 1
            if overlap >= 0.6 * (end - start + 1):
                return True
    return False


def follow_up_reads(
    ws: Workspace, round_obs: list[Observation], earlier: list[Observation]
) -> list[ReadSource]:
    """read_source calls for what this round's evidence points at but hasn't shown."""
    symbols = _symbols_by_path(ws)
    seen: list[Span] = [
        (o.call.path, o.call.start_line, o.call.end_line)
        for o in [*earlier, *round_obs]
        if isinstance(o.call, ReadSource) and not o.error
    ]
    reads: list[ReadSource] = []
    for obs in round_obs:
        if obs.error:
            continue
        for span in _pointers(ws, obs, symbols):
            if len(reads) >= MAX_READS:
                return reads
            if _covered(span, seen) or ws.read_lines(PurePosixPath(span[0])) is None:
                continue
            seen.append(span)
            reads.append(
                ReadSource(tool="read_source", path=span[0], start_line=span[1], end_line=span[2])
            )
    return reads
