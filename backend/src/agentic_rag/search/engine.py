"""Hybrid retrieval over chunks: dense vectors (Qdrant) + BM25, merged by reciprocal rank fusion."""

import json
import threading
from dataclasses import dataclass
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PointStruct,
    VectorParams,
)
from rank_bm25 import BM25Okapi

from agentic_rag.ingest.models import Chunk, ChunkKind
from agentic_rag.search.embed import Embedder, document_text
from agentic_rag.search.text import tokenize

COLLECTION = "chunks"
RRF_K = 60  # standard constant from the RRF paper; damps the influence of top ranks
CANDIDATES = 40  # per retriever, before fusion


@dataclass(frozen=True)
class Scored:
    chunk: Chunk
    score: float


def build_vectors(chunks: list[Chunk], embedder: Embedder, out_dir: Path) -> None:
    """Embed every chunk and persist a local Qdrant collection under `out_dir`."""
    client = QdrantClient(path=str(out_dir))
    try:
        if client.collection_exists(COLLECTION):
            client.delete_collection(COLLECTION)
        client.create_collection(
            COLLECTION, vectors_config=VectorParams(size=embedder.dim, distance=Distance.COSINE)
        )
        vectors = embedder.embed_documents([document_text(c) for c in chunks])
        client.upsert(
            COLLECTION,
            points=[
                PointStruct(
                    id=i,
                    vector=vector,
                    payload={"chunk_id": c.id, "kind": c.kind, "is_test": c.is_test},
                )
                for i, (c, vector) in enumerate(zip(chunks, vectors, strict=True))
            ],
        )
    finally:
        client.close()
    (out_dir / "embedding.json").write_text(
        json.dumps({"model": embedder.model_name, "dim": embedder.dim}), encoding="utf-8"
    )


class SearchEngine:
    def __init__(self, chunks: list[Chunk], vector_dir: Path, embedder: Embedder) -> None:
        self.chunks = chunks
        self.by_id = {c.id: c for c in chunks}
        self.embedder = embedder
        built = json.loads((vector_dir / "embedding.json").read_text(encoding="utf-8"))
        if built["model"] != embedder.model_name:
            raise ValueError(
                f"index embedded with {built['model']}, query embedder is {embedder.model_name}"
            )
        self._client = QdrantClient(path=str(vector_dir))
        # Local-mode Qdrant and the ONNX session aren't safe to share across threads, and the
        # agent runs tool calls in parallel; queries are fast, so a lock costs nothing.
        self._lock = threading.Lock()
        self._bm25 = BM25Okapi([tokenize(document_text(c)) for c in chunks])

    def close(self) -> None:
        self._client.close()

    def _allowed(self, chunk: Chunk, kinds: set[ChunkKind] | None, include_tests: bool) -> bool:
        return (kinds is None or chunk.kind in kinds) and (include_tests or not chunk.is_test)

    def dense(
        self, query: str, k: int, kinds: set[ChunkKind] | None = None, include_tests: bool = False
    ) -> list[Scored]:
        must = [FieldCondition(key="kind", match=MatchAny(any=sorted(kinds)))] if kinds else []
        must_not = (
            [] if include_tests else [FieldCondition(key="is_test", match=MatchValue(value=True))]
        )
        with self._lock:
            points = self._client.query_points(
                COLLECTION,
                query=self.embedder.embed_query(query),
                limit=k,
                query_filter=Filter(must=must, must_not=must_not),
            ).points
        # Skip ids that no longer exist (vectors left over from an older `--no-embed` re-index).
        return [
            Scored(self.by_id[str(p.payload["chunk_id"])], float(p.score))
            for p in points
            if p.payload is not None and str(p.payload["chunk_id"]) in self.by_id
        ]

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
