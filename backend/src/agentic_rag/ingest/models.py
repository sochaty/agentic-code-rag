"""Language-agnostic records produced by ingestion. Every language plugin emits these shapes."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

ChunkKind = Literal["code", "doc", "changelog"]
Granularity = Literal["function", "class_outline", "module_outline", "section"]
SymbolKind = Literal["module", "class", "function", "method", "variable"]
EdgeKind = Literal["contains", "calls", "inherits", "decorated_by", "imports"]
Resolution = Literal["exact", "receiver", "heuristic", "ambiguous", "external", "unresolved"]


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True)


class Chunk(_Record):
    """A retrievable unit of text with a precise location. Lines are 1-based and inclusive."""

    id: str
    kind: ChunkKind
    granularity: Granularity
    path: str
    start_line: int
    end_line: int
    title: str
    text: str
    language: str | None = None
    symbol_id: str | None = None
    part: int = 0
    # Repeated on continuation parts of long units, e.g. the function signature.
    context: str | None = None
    is_test: bool = False


class Symbol(_Record):
    id: str  # "<path>::<qualname>", unique even when two files define the same qualname
    qualname: str
    name: str
    kind: SymbolKind
    language: str
    path: str
    start_line: int
    end_line: int
    parent_id: str | None = None
    signature: str | None = None
    docstring: str | None = None
    decorators: tuple[str, ...] = ()
    is_test: bool = False


class RawRef(_Record):
    """An unresolved reference as written in source; plugins resolve these into edges."""

    src_id: str
    kind: EdgeKind
    raw: str
    line: int


class Edge(_Record):
    src: str
    dst: str  # a symbol id, or a dotted external name when resolution == "external"
    kind: EdgeKind
    resolution: Resolution
    line: int | None = None
    raw: str | None = None


class Commit(_Record):
    sha: str
    author: str
    date: str
    subject: str
    body: str
    files: tuple[str, ...]
