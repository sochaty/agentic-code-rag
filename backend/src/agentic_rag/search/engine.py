"""Hybrid retrieval over chunks: dense vectors + BM25, merged by reciprocal rank fusion.

Vectors are a plain normalised float32 matrix on disk (`vectors.npy` + `ids.json`), searched
by brute-force cosine. At this scale (thousands of chunks) that is well under a millisecond,
and plain files can be read by any number of processes at once: the API server, the MCP
server and the CLI all open the same index. (Qdrant's local mode took an exclusive file
lock, so only one of them could run at a time.)
"""

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import numpy as np
from numpy.typing import NDArray
from rank_bm25 import BM25Okapi

from agentic_rag.ingest.models import Chunk, ChunkKind
from agentic_rag.search.embed import Embedder, document_text
from agentic_rag.search.text import tokenize

RRF_K = 60  # standard constant from the RRF paper; damps the influence of top ranks
CANDIDATES = 40  # per retriever, before fusion
MATRIX, IDS, META = "vectors.npy", "ids.json", "embedding.json"
_LEGACY_QDRANT = "collection"  # indexes built before the switch to plain files


@dataclass(frozen=True)
class Scored:
    chunk: Chunk
    score: float


def _normalise(matrix: NDArray[np.float32]) -> NDArray[np.float32]:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return (matrix / np.where(norms == 0, 1.0, norms)).astype(np.float32)


def save_vectors(out_dir: Path, ids: list[str], vectors: NDArray[np.float32], model: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    np.save(out_dir / MATRIX, _normalise(vectors))
    (out_dir / IDS).write_text(json.dumps(ids), encoding="utf-8")
    (out_dir / META).write_text(
        json.dumps({"model": model, "dim": int(vectors.shape[1])}), encoding="utf-8"
    )


def build_vectors(chunks: list[Chunk], embedder: Embedder, out_dir: Path) -> None:
    """Embed every chunk and save the matrix under `out_dir`."""
    vectors = np.asarray(
        embedder.embed_documents([document_text(c) for c in chunks]), dtype=np.float32
    )
    save_vectors(out_dir, [c.id for c in chunks], vectors, embedder.model_name)


def migrate_legacy_qdrant(vector_dir: Path) -> bool:
    """Copy vectors out of an old local-Qdrant index, once, so nothing needs re-embedding."""
    if (vector_dir / MATRIX).exists() or not (vector_dir / _LEGACY_QDRANT).exists():
        return False
    from qdrant_client import QdrantClient

    meta = json.loads((vector_dir / META).read_text(encoding="utf-8"))
    client = QdrantClient(path=str(vector_dir))
    try:
        ids: list[str] = []
        rows: list[list[float]] = []
        offset = None
        while True:
            points, offset = client.scroll(
                "chunks", limit=512, offset=offset, with_vectors=True, with_payload=True
            )
            for point in points:
                if point.payload and isinstance(point.vector, list):
                    ids.append(str(point.payload["chunk_id"]))
                    rows.append([float(x) for x in cast(list[float], point.vector)])
            if offset is None:
                break
    finally:
        client.close()
    save_vectors(vector_dir, ids, np.asarray(rows, dtype=np.float32), meta["model"])
    return True


class SearchEngine:
    def __init__(self, chunks: list[Chunk], vector_dir: Path, embedder: Embedder) -> None:
        self.chunks = chunks
        self.by_id = {c.id: c for c in chunks}
        self.embedder = embedder
        migrate_legacy_qdrant(vector_dir)
        built = json.loads((vector_dir / META).read_text(encoding="utf-8"))
        if built["model"] != embedder.model_name:
            raise ValueError(
                f"index embedded with {built['model']}, query embedder is {embedder.model_name}"
            )
        ids: list[str] = json.loads((vector_dir / IDS).read_text(encoding="utf-8"))
        matrix: NDArray[np.float32] = np.load(vector_dir / MATRIX)
        # Keep only rows whose chunk still exists (e.g. after a `--no-embed` re-index).
        keep = [i for i, chunk_id in enumerate(ids) if chunk_id in self.by_id]
        self._ids = [ids[i] for i in keep]
        self._matrix = matrix[keep]
        # The ONNX embedding session isn't safe to share across the agent's parallel tool
        # threads; embedding a query takes milliseconds, so a lock costs nothing.
        self._lock = threading.Lock()
        self._bm25 = BM25Okapi([tokenize(document_text(c)) for c in chunks])

    def close(self) -> None:
        """Nothing to release: the index is plain arrays. Kept for callers that close."""

    def _allowed(self, chunk: Chunk, kinds: set[ChunkKind] | None, include_tests: bool) -> bool:
        return (kinds is None or chunk.kind in kinds) and (include_tests or not chunk.is_test)

    def dense(
        self, query: str, k: int, kinds: set[ChunkKind] | None = None, include_tests: bool = False
    ) -> list[Scored]:
        with self._lock:
            q = np.asarray(self.embedder.embed_query(query), dtype=np.float32)
        q /= np.linalg.norm(q) or 1.0
        scores = self._matrix @ q
        hits: list[Scored] = []
        for row in np.argsort(-scores):
            chunk = self.by_id[self._ids[row]]
            if self._allowed(chunk, kinds, include_tests):
                hits.append(Scored(chunk, float(scores[row])))
                if len(hits) == k:
                    break
        return hits

    def sparse(
        self, query: str, k: int, kinds: set[ChunkKind] | None = None, include_tests: bool = False
    ) -> list[Scored]:
        scores = self._bm25.get_scores(tokenize(query))
        ranked = sorted(range(len(self.chunks)), key=lambda i: -scores[i])
        hits: list[Scored] = []
        for i in ranked:
            if scores[i] <= 0 or len(hits) == k:
                break
            if self._allowed(self.chunks[i], kinds, include_tests):
                hits.append(Scored(self.chunks[i], float(scores[i])))
        return hits

    def hybrid(
        self, query: str, k: int, kinds: set[ChunkKind] | None = None, include_tests: bool = False
    ) -> list[Scored]:
        fused: dict[str, float] = {}
        for ranking in (
            self.dense(query, CANDIDATES, kinds, include_tests),
            self.sparse(query, CANDIDATES, kinds, include_tests),
        ):
            for rank, hit in enumerate(ranking):
                fused[hit.chunk.id] = fused.get(hit.chunk.id, 0.0) + 1.0 / (RRF_K + rank + 1)
        best = sorted(fused.items(), key=lambda item: -item[1])[:k]
        return [Scored(self.by_id[chunk_id], score) for chunk_id, score in best]
