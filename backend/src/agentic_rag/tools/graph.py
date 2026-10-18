"""symbol_graph: definitions and relationships, each labelled with how it was resolved."""

from typing import Literal

from pydantic import BaseModel

from agentic_rag.ingest.models import Edge, EdgeKind, Resolution, Symbol, SymbolKind
from agentic_rag.workspace import Workspace

Relation = Literal["definition", "callers", "callees", "members", "superclasses", "subclasses"]
MAX_RELATED = 50
MAX_CANDIDATES = 10
_CONFIDENCE: dict[Resolution, int] = {
    "exact": 0,
    "receiver": 1,
    "heuristic": 2,
    "ambiguous": 3,
    "external": 4,
    "unresolved": 5,
}
_KIND_ORDER: dict[SymbolKind, int] = {
    "class": 0,
    "function": 1,
    "method": 1,
    "module": 2,
    "variable": 3,
}


class SymbolInfo(BaseModel):
    id: str
    qualname: str
    kind: SymbolKind
    path: str
    start_line: int
    end_line: int
    signature: str | None = None
    docstring: str | None = None

    @classmethod
    def of(cls, s: Symbol) -> "SymbolInfo":
        return cls(
            id=s.id,
            qualname=s.qualname,
            kind=s.kind,
            path=s.path,
            start_line=s.start_line,
            end_line=s.end_line,
            signature=s.signature,
            docstring=s.docstring,
        )

    def location(self) -> str:
        return f"{self.path}:{self.start_line}-{self.end_line}"


class Related(BaseModel):
    name: str
    symbol: SymbolInfo | None
    edge_kind: EdgeKind
    resolution: Resolution
    line: int | None = None  # where the reference is written


class GraphResult(BaseModel):
    query: str
    relation: Relation
    symbol: SymbolInfo | None = None
    candidates: list[SymbolInfo] = []
    related: list[Related] = []
    total: int = 0

    def render(self) -> str:
        if self.symbol is None:
            if not self.candidates:
                return f"No symbol matches {self.query!r}."
            lines = [f"{self.query!r} is ambiguous; call again with one of these qualnames:"]
            lines += [f"  {c.qualname}  ({c.kind}, {c.location()})" for c in self.candidates]
            return "\n".join(lines)
        s = self.symbol
        out = [f"{s.qualname}  ({s.kind})  {s.location()}"]
        if s.signature:
            out.append(f"  {s.signature}")
        if s.docstring:
            summary = " ".join(s.docstring.split())  # one line: cheaper to read, for models too
            out.append(f'  "{summary[:200]}{"..." if len(summary) > 200 else ""}"')
        if self.relation == "definition":
            return "\n".join(out)
        shown = (
            f"showing {len(self.related)} of {self.total}"
            if self.total > len(self.related)
            else str(self.total)
        )
        out.append(f"{self.relation} ({shown}):")
        for r in self.related:
            where = (
                r.symbol.location()
                if r.symbol
                else "outside the repo"
                if r.resolution == "external"
                else "not statically resolvable"
            )
            via = (
                f" via {r.edge_kind}"
                if r.edge_kind not in ("calls", "contains", "inherits")
                else ""
            )
            at = f" (ref line {r.line})" if r.line else ""
            out.append(f"  {r.resolution:<10} {r.name}  {where}{via}{at}")
        return "\n".join(out)


def find_symbols(ws: Workspace, query: str) -> list[Symbol]:
    """Exact qualname, then dotted suffix (`Flask.run`), then bare name; best candidates first."""
    q = query.strip().removesuffix("()")
    symbols = ws.index.symbols
    matches = [s for s in symbols if q in (s.qualname, s.id)]
    if not matches:
        matches = [s for s in symbols if s.qualname.endswith("." + q)]
    if not matches:
        name = q.rpartition(".")[2].lower()
        matches = [s for s in symbols if s.name.lower() == name]
    return sorted(matches, key=lambda s: (s.is_test, _KIND_ORDER[s.kind], len(s.qualname)))


def _related(ws: Workspace, edge: Edge, outgoing: bool) -> Related:
    other_id = edge.dst if outgoing else edge.src
    other = ws.symbols_by_id.get(other_id)
    return Related(
        name=other.qualname if other else other_id,
        symbol=SymbolInfo.of(other) if other else None,
        edge_kind=edge.kind,
        resolution=edge.resolution,
        line=edge.line,
    )


def symbol_graph(ws: Workspace, symbol: str, relation: Relation = "definition") -> GraphResult:
    matches = find_symbols(ws, symbol)
    non_test = [s for s in matches if not s.is_test]
    chosen = matches[0] if len(matches) == 1 else non_test[0] if len(non_test) == 1 else None
    if chosen is None:
        return GraphResult(
            query=symbol,
            relation=relation,
            candidates=[SymbolInfo.of(s) for s in matches[:MAX_CANDIDATES]],
        )

    kinds: set[EdgeKind]
    if relation == "callers":
        edges, outgoing, kinds = ws.edges_to.get(chosen.id, []), False, {"calls", "decorated_by"}
    elif relation == "callees":
        edges, outgoing, kinds = ws.edges_from.get(chosen.id, []), True, {"calls", "decorated_by"}
    elif relation == "members":
        edges, outgoing, kinds = ws.edges_from.get(chosen.id, []), True, {"contains"}
    elif relation == "superclasses":
        edges, outgoing, kinds = ws.edges_from.get(chosen.id, []), True, {"inherits"}
    elif relation == "subclasses":
        edges, outgoing, kinds = ws.edges_to.get(chosen.id, []), False, {"inherits"}
    else:
        edges, outgoing, kinds = [], True, set()

    related = [_related(ws, e, outgoing) for e in edges if e.kind in kinds]
    related.sort(
        key=lambda r: (
            _CONFIDENCE[r.resolution],
            r.symbol.path if r.symbol else "~",
            r.symbol.start_line if r.symbol else 0,
            r.name,
        )
    )
    return GraphResult(
        query=symbol,
        relation=relation,
        symbol=SymbolInfo.of(chosen),
        related=related[:MAX_RELATED],
        total=len(related),
    )
