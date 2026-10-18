"""Cross-encoder rerankers: score (query, passage) pairs jointly, far sharper than embeddings."""

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from agentic_rag.search.text import tokenize


class Reranker(Protocol):
    model_name: str

    def score(self, query: str, passages: Sequence[str]) -> list[float]: ...


class CrossEncoderReranker:
    """ms-marco MiniLM via FastEmbed (ONNX, CPU). Returns raw logits: >0 leans relevant.

    On Flask, clearly relevant passages score about +3 to +8 and clearly irrelevant ones
    below -4; the band in between is what the LLM grader looks at.
    """

    def __init__(self, model_name: str, cache_dir: Path) -> None:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        self.model_name = model_name
        self._model = TextCrossEncoder(model_name, cache_dir=str(cache_dir))

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        return [float(s) for s in self._model.rerank(query, list(passages))]


class OverlapReranker:
    """Deterministic stand-in for tests: query-token overlap mapped onto a logit-like scale."""

    model_name = "overlap"

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        wanted = set(tokenize(query))
        scores = []
        for passage in passages:
            got = set(tokenize(passage))
            share = len(wanted & got) / len(wanted) if wanted else 0.0
            scores.append(round(share * 16 - 8, 2))  # 0% -> -8, 100% -> +8
        return scores
