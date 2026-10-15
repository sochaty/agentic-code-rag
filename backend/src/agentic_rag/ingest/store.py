"""On-disk index: one JSONL file per record type plus a manifest. Plain files, easy to inspect."""

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from agentic_rag.ingest.models import Chunk, Commit, Edge, Symbol


@dataclass
class Index:
    chunks: list[Chunk] = field(default_factory=list)
    symbols: list[Symbol] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    commits: list[Commit] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)


def _write_jsonl(path: Path, records: Iterable[BaseModel]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for record in records:
            fh.write(record.model_dump_json(exclude_defaults=True))
            fh.write("\n")


def _read_jsonl[T: BaseModel](path: Path, model: type[T]) -> list[T]:
    with path.open(encoding="utf-8") as fh:
        return [model.model_validate_json(line) for line in fh if line.strip()]


def save(index: Index, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(out_dir / "chunks.jsonl", index.chunks)
    _write_jsonl(out_dir / "symbols.jsonl", index.symbols)
    _write_jsonl(out_dir / "edges.jsonl", index.edges)
    _write_jsonl(out_dir / "commits.jsonl", index.commits)
    (out_dir / "manifest.json").write_text(
        json.dumps(index.manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


def load(out_dir: Path) -> Index:
    return Index(
        chunks=_read_jsonl(out_dir / "chunks.jsonl", Chunk),
        symbols=_read_jsonl(out_dir / "symbols.jsonl", Symbol),
        edges=_read_jsonl(out_dir / "edges.jsonl", Edge),
        commits=_read_jsonl(out_dir / "commits.jsonl", Commit),
        manifest=json.loads((out_dir / "manifest.json").read_text(encoding="utf-8")),
    )
