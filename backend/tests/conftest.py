import shutil
import subprocess
from pathlib import Path

import pytest

from agentic_rag.ingest import pipeline
from agentic_rag.ingest.models import Edge
from agentic_rag.ingest.store import Index

FIXTURE = Path(__file__).parent / "fixtures" / "sample_repo"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


@pytest.fixture(scope="session")
def sample_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The fixture tree as a real git repo: two commits, plus one untracked file."""
    repo = tmp_path_factory.mktemp("sample") / "repo"
    shutil.copytree(FIXTURE, repo)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "Initial shop")
    util = repo / "src" / "shop" / "util.py"
    util.write_text(util.read_text() + "\n\nVERSION = '1.1'\n")
    _git(repo, "commit", "-q", "-am", "Add VERSION", "-m", "Body line.")
    (repo / "scratch.py").write_text("def untracked():\n    pass\n")
    return repo


@pytest.fixture(scope="session")
def sample_index(sample_repo: Path) -> Index:
    return pipeline.build(sample_repo, "sample")


def edges_from(index: Index, src_qualname: str, kind: str) -> dict[str, Edge]:
    """Edges leaving the symbol with this qualname, keyed by the raw reference text."""
    src_ids = {s.id for s in index.symbols if s.qualname == src_qualname}
    assert src_ids, f"no symbol {src_qualname}"
    return {e.raw or e.dst: e for e in index.edges if e.src in src_ids and e.kind == kind}


def qualname_of(index: Index, symbol_id: str) -> str:
    return next(s.qualname for s in index.symbols if s.id == symbol_id)
