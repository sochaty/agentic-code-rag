"""Fetch the pinned corpora listed in corpora.toml.

Full history is cloned on purpose: the git_history tool answers "when and why did this change?".
"""

import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CorpusSpec:
    name: str
    url: str
    ref: str
    license: str
    languages: tuple[str, ...]


def load_specs(corpora_file: Path) -> dict[str, CorpusSpec]:
    raw = tomllib.loads(corpora_file.read_text(encoding="utf-8"))
    return {
        name: CorpusSpec(
            name=name,
            url=entry["url"],
            ref=entry["ref"],
            license=entry["license"],
            languages=tuple(entry.get("languages", [])),
        )
        for name, entry in raw.items()
    }


def _git(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def fetch(spec: CorpusSpec, corpora_dir: Path) -> Path:
    """Clone (or update) the corpus and check out its pinned ref. Idempotent."""
    target = corpora_dir / spec.name
    if not (target / ".git").exists():
        corpora_dir.mkdir(parents=True, exist_ok=True)
        _git("clone", "--quiet", spec.url, str(target))
    else:
        _git("fetch", "--quiet", "--tags", "origin", cwd=target)
    _git("-c", "advice.detachedHead=false", "checkout", "--quiet", spec.ref, cwd=target)
    return target


def current_ref(target: Path) -> str:
    return _git("describe", "--tags", "--always", cwd=target)
