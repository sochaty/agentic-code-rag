"""Read the code that pointer-only evidence points at — deterministic, no model call.

v1's eval showed the agent's partial answers had one cause: it answered from *where* things
are, not *what they say*. A call-graph edge says full_dispatch_request calls dispatch_request
but not that it only does so when preprocess_request returned None; a grep hit gives the line
of an error message but not the import that fails before it; a semantic hit cut off after 40
lines hides the early return in Flask.run. The sufficiency check accepted those pointers as
answers. So after each round, before the check, the agent reads a few of the places its
evidence points at:

- symbol_graph callers: the caller around the call; callees/definition: the symbol's body
- exact_search hits: the function around the hit (or the doc section)
- semantic hits that survived grading but were cut off: the rest of the chunk

At most MAX_READS per round, each at most MAX_SPAN lines. Pointers are taken in that order of
kind (graph edges are what v1 answered from most often), and within a kind one per observation
before any observation's second, so one search can't use up the reads. Anything already shown,
by an earlier read or by a semantic hit shown in full, is skipped.
"""

from pathlib import PurePosixPath

from agentic_rag.agent.calls import Observation, ReadSource
from agentic_rag.workspace import Workspace

MAX_READS = 3
MAX_SPAN = 100  # lines per read; longer bodies are windowed around the line of interest
COVERED = 0.6  # a span counts as shown when this share of it was already shown
_BEFORE = 30  # window: lines kept above the line of interest
_GREP_HITS = 4  # grep hits considered per search (the rest are usually repeats)
_EDGES = 3  # graph edges considered per call
_GRAPH, _GREP, _SEMANTIC = 0, 1, 2  # pointer priority, most valuable first

Span = tuple[str, int, int]


def _window(path: str, start: int, end: int, focus: int | None) -> Span:
    if end - start + 1 <= MAX_SPAN:
        return (path, start, end)
    top = start if focus is None else max(start, focus - _BEFORE)
    return (path, top, min(end, top + MAX_SPAN - 1))


def _around(ws: Workspace, path: str, line: int) -> Span:
    """The innermost function around a line; else the doc section; else a plain window."""
    if (fn := ws.function_at(path, line)) is not None:
        return _window(path, fn.start_line, fn.end_line, line)
    if (section := ws.section_span(path, line)) is not None:
        return _window(path, *section, line)
    return (path, max(1, line - 10), line + 20)


def _pointers(ws: Workspace, obs: Observation) -> list[tuple[int, Span]]:
    """(priority, span) for each place this observation points at but doesn't show."""
    spans: list[tuple[int, Span]] = []
    if obs.graph is not None and obs.graph.symbol is not None:
        target = obs.graph.symbol
        if obs.graph.relation == "callers":
            for rel in obs.graph.related[:_EDGES]:
                if rel.symbol is not None:
                    s = rel.symbol
                    focus = rel.line or s.start_line
                    spans.append((_GRAPH, _window(s.path, s.start_line, s.end_line, focus)))
        elif obs.graph.relation in ("callees", "definition"):
            spans.append((_GRAPH, _window(target.path, target.start_line, target.end_line, None)))
    if obs.grep is not None:
        for g in obs.grep.hits[:_GREP_HITS]:
            spans.append((_GREP, _around(ws, g.path, g.line)))
    if obs.search is not None:  # only hits that survived grading
        for hit in obs.search.hits:
            if hit.more_lines:  # the first lines are already in the observation
                rest = hit.end_line - hit.more_lines + 1
                spans.append((_SEMANTIC, _window(hit.path, rest, hit.end_line, None)))
    return spans


def shown(observations: list[Observation]) -> list[Span]:
    """Line ranges whose full text the agent has already seen: reads and shown semantic hits."""
    spans: list[Span] = []
    for o in observations:
        if o.error:
            continue
        if isinstance(o.call, ReadSource):
            spans.append((o.call.path, o.call.start_line, o.call.end_line))
        if o.search is not None:
            for hit in o.search.hits:
                spans.append((hit.path, hit.start_line, hit.end_line - hit.more_lines))
    return spans


def covered(span: Span, seen: list[Span]) -> bool:
    """True when most of `span` was already shown (by one range or several together)."""
    path, start, end = span
    unseen = set(range(start, end + 1))
    for other_path, other_start, other_end in seen:
        if other_path == path and other_start <= end and other_end >= start:
            unseen -= set(range(max(start, other_start), min(end, other_end) + 1))
    return len(unseen) <= (1 - COVERED) * (end - start + 1)


def follow_up_reads(
    ws: Workspace, round_obs: list[Observation], earlier: list[Observation]
) -> list[ReadSource]:
    """read_source calls for what this round's evidence points at but hasn't shown."""
    seen = shown([*earlier, *round_obs])
    ranked: list[tuple[int, int, int, Span]] = []  # (priority, rank in its observation, obs, span)
    for i, obs in enumerate(round_obs):
        if obs.error:
            continue
        per_kind: dict[int, int] = {}
        for priority, span in _pointers(ws, obs):
            rank = per_kind.get(priority, 0)
            per_kind[priority] = rank + 1
            ranked.append((priority, rank, i, span))
    reads: list[ReadSource] = []
    for _, _, _, span in sorted(ranked, key=lambda r: r[:3]):
        if len(reads) >= MAX_READS:
            break
        if covered(span, seen) or ws.read_lines(PurePosixPath(span[0])) is None:
            continue
        seen.append(span)
        reads.append(
            ReadSource(tool="read_source", path=span[0], start_line=span[1], end_line=span[2])
        )
    return reads
