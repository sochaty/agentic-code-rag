"""Text embedders. FastEmbed runs ONNX models locally on CPU — no PyTorch, no API key."""

import hashlib
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from agentic_rag.ingest.models import Chunk
from agentic_rag.search.text import tokenize


class Embedder(Protocol):
    model_name: str
    dim: int

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


def document_text(chunk: Chunk) -> str:
    """What gets embedded: location and title first, so a bare code body still has context."""
    header = [chunk.title, chunk.path]
    if chunk.context:
        header.append(chunk.context)
    return "\n".join([*header, chunk.text])


class FastEmbedder:
    def __init__(self, model_name: str, cache_dir: Path) -> None:
        from fastembed import TextEmbedding  # heavy import; only when actually embedding

        self.model_name = model_name
        self._model = TextEmbedding(model_name=model_name, cache_dir=str(cache_dir))
        self.dim = len(self.embed_query("probe"))

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [
            [float(x) for x in vector] for vector in self._model.embed(list(texts), batch_size=32)
        ]

    def embed_query(self, text: str) -> list[float]:
        return [float(x) for x in next(iter(self._model.query_embed(text)))]


class HashEmbedder:
    """Deterministic bag-of-tokens embedder for tests: no model download, stable results."""

    model_name = "hash"

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for token in tokenize(text):
            bucket = int(hashlib.md5(token.encode()).hexdigest(), 16) % self.dim
            vector[bucket] += 1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)
