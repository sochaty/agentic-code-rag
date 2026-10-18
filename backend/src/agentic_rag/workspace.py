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

VECTOR_DIR = "vectors"


class Workspace:
    def __init__(
        self,
        index: Index,
        repo: Path,
        vector_dir: Path | None = None,
        embedder_factory: Callable[[], Embedder] | None = None,
    ) -> None:
        self.index = index
        self.repo = repo
        self._vector_dir = vector_dir
        self._embedder_factory = embedder_factory  # model loads lazily, on the first search
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
        if not vector_dir.exists():
            return cls(index, repo)
        model, cache = settings.embedding_model, settings.models_dir
        return cls(index, repo, vector_dir, lambda: FastEmbedder(model, cache))

    @cached_property
    def search(self) -> SearchEngine:
        if self._vector_dir is None or self._embedder_factory is None:
            raise RuntimeError("this index has no vectors; re-run `acr ingest` without --no-embed")
        return SearchEngine(self.index.chunks, self._vector_dir, self._embedder_factory())

    @cached_property
    def files(self) -> list[PurePosixPath]:
        return pipeline.discover(self.repo)

    def read_lines(self, path: PurePosixPath) -> list[str] | None:
        full = self.repo / path
        if not full.is_file():
            return None
        data = full.read_bytes()
        if b"\0" in data[:8000]:
            return None  # binary
        return data.decode("utf-8", errors="replace").splitlines()

    def close(self) -> None:
        if "search" in self.__dict__:
            self.search.close()
