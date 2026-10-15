"""The contract every language plugin implements.

Adding a language means writing one class that satisfies `LanguagePlugin` and registering it.
Tools, graph storage and the agent never branch on language.
"""

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Protocol

from agentic_rag.ingest.models import Chunk, Edge, RawRef, Symbol


@dataclass(frozen=True)
class RepoContext:
    """Repository-wide facts a plugin may need while parsing one file."""

    files: frozenset[PurePosixPath]


@dataclass
class ParsedFile:
    path: PurePosixPath
    module: str
    symbols: list[Symbol] = field(default_factory=list)
    chunks: list[Chunk] = field(default_factory=list)
    refs: list[RawRef] = field(default_factory=list)
    imports: dict[str, str] = field(default_factory=dict)  # local name -> fully qualified target
    star_imports: list[str] = field(default_factory=list)


class LanguagePlugin(Protocol):
    name: str
    extensions: tuple[str, ...]

    def parse(self, path: PurePosixPath, source: bytes, ctx: RepoContext) -> ParsedFile:
        """Extract symbols, chunks and raw references from one file."""
        ...

    def resolve(self, files: list[ParsedFile]) -> list[Edge]:
        """Resolve every raw reference across all parsed files of this language into edges."""
        ...
