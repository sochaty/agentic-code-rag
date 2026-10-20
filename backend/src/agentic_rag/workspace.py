"""A loaded index plus everything the tools need: the repo on disk, lookups, and search."""

from collections.abc import Callable
from functools import cached_property
from pathlib import Path, PurePosixPath

from agentic_rag.config import Settings, get_settings
from agentic_rag.ingest import pipeline, store
from agentic_rag.ingest.models import Edge, Symbol
from agentic_rag.ingest.store import Index
from agentic_rag.search.embed import Embedder, FastEmbedder
from agentic_rag.search.engine import SearchEngine
from agentic_rag.search.rerank import CrossEncoderReranker, Reranker

VECTOR_DIR = "vectors"


class Workspace:
    def __init__(
        self,
        index: Index,
        repo: Path,
        vector_dir: Path | None = None,
        embedder_factory: Callable[[], Embedder] | None = None,
        reranker_factory: Callable[[], Reranker] | None = None,
    ) -> None:
        self.index = index
        self.repo = repo
        self._vector_dir = vector_dir
        self._embedder_factory = embedder_factory  # model loads lazily, on the first search
        self._reranker_factory = reranker_factory
        self._lines: dict[str, list[str] | None] = {}
        self.symbols_by_id: dict[str, Symbol] = {s.id: s for s in index.symbols}
        self.edges_from: dict[str, list[Edge]] = {}
        self.edges_to: dict[str, list[Edge]] = {}
        for edge in index.edges:
            self.edges_from.setdefault(edge.src, []).append(edge)
            self.edges_to.setdefault(edge.dst, []).append(edge)

    @classmethod
    def open(cls, name: str, settings: Settings | None = None) -> "Workspace":
        settings = settings or get_settings()
        index_dir = settings.indexes_dir / name
        if not (index_dir / "manifest.json").exists():
            raise FileNotFoundError(f"no index at {index_dir}; run `acr ingest {name}` first")
        index = store.load(index_dir)
        repo = Path(index.manifest["repo"])
        if not repo.exists():  # index built on another machine; fall back to the corpora dir
            repo = settings.corpora_dir / name
        vector_dir = index_dir / VECTOR_DIR
        model, reranker, cache = (
            settings.embedding_model,
            settings.reranker_model,
            settings.models_dir,
        )
        return cls(
            index,
            repo,
            vector_dir if vector_dir.exists() else None,
            (lambda: FastEmbedder(model, cache)) if vector_dir.exists() else None,
            lambda: CrossEncoderReranker(reranker, cache),
        )

    @cached_property
    def search(self) -> SearchEngine:
        if self._vector_dir is None or self._embedder_factory is None:
            raise RuntimeError("this index has no vectors; re-run `acr ingest` without --no-embed")
        return SearchEngine(self.index.chunks, self._vector_dir, self._embedder_factory())

    @cached_property
    def reranker(self) -> Reranker:
        if self._reranker_factory is None:
            raise RuntimeError("no reranker configured for this workspace")
        return self._reranker_factory()

    @cached_property
    def _sections(self) -> dict[str, list[tuple[int, int, str]]]:
        by_path: dict[str, list[tuple[int, int, str]]] = {}
        for c in self.index.chunks:
            if c.kind in ("doc", "changelog"):
                by_path.setdefault(c.path, []).append((c.start_line, c.end_line, c.title))
        return by_path

    def section_at(self, path: PurePosixPath, line: int) -> str | None:
        """The doc/changelog heading (breadcrumb) a line falls under, if any."""
        spans = self._sections.get(path.as_posix(), [])
        hits = [title for start, end, title in spans if start <= line <= end]
        return hits[-1] if hits else None

    def section_span(self, path: str, line: int) -> tuple[int, int] | None:
        """The innermost doc/changelog section around a line, as (start, end)."""
        spans = [(s, e) for s, e, _ in self._sections.get(path, []) if s <= line <= e]
        return min(spans, key=lambda span: span[1] - span[0]) if spans else None

    @cached_property
    def _functions(self) -> dict[str, list[Symbol]]:
        by_path: dict[str, list[Symbol]] = {}
        for s in self.index.symbols:
            if s.kind in ("function", "method"):
                by_path.setdefault(s.path, []).append(s)
        return by_path

    def function_at(self, path: str, line: int) -> Symbol | None:
        """The innermost function or method containing a line, if any."""
        inside = [s for s in self._functions.get(path, []) if s.start_line <= line <= s.end_line]
        return min(inside, key=lambda s: s.end_line - s.start_line) if inside else None

    @cached_property
    def files(self) -> list[PurePosixPath]:
        return pipeline.discover(self.repo)

    def read_lines(self, path: PurePosixPath) -> list[str] | None:
        """File lines, cached (exact_search scans every file); None if missing or binary."""
        key = path.as_posix()
        if key not in self._lines:
            full = self.repo / path
            data = full.read_bytes() if full.is_file() else None
            text = data is not None and b"\0" not in data[:8000]
            self._lines[key] = (
                data.decode("utf-8", errors="replace").splitlines() if data and text else None
            )
        return self._lines[key]

    def warm_up(self) -> None:
        """Load models and file contents now, so the first parallel round doesn't stall.

        Without this, parallel exact_search calls each miss the cold file cache and read every
        file at once (measured ~0.5s each locally, 3s+ with antivirus scanning cold reads).
        """
        if self._vector_dir is not None:
            _ = self.search
        if self._reranker_factory is not None:
            _ = self.reranker
        for path in self.files:
            self.read_lines(path)

    def close(self) -> None:
        if "search" in self.__dict__:
            self.search.close()
