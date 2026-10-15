"""Commit history with the files each commit touched."""

import subprocess
from pathlib import Path

from agentic_rag.ingest.models import Commit

_RECORD, _FIELD = "\x1e", "\x1f"
_FORMAT = _FIELD.join(["%H", "%an", "%aI", "%s", "%b"]) + _FIELD


def read_commits(repo: Path, ref: str = "HEAD") -> list[Commit]:
    """Every commit reachable from `ref`, newest first."""
    out = subprocess.run(
        ["git", "log", ref, f"--format={_RECORD}{_FORMAT}", "--name-only", "--no-renames"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).stdout
    commits: list[Commit] = []
    for record in out.split(_RECORD):
        if not record.strip():
            continue
        sha, author, date, subject, body, names = record.split(_FIELD, 5)
        commits.append(
            Commit(
                sha=sha,
                author=author,
                date=date,
                subject=subject,
                body=body.strip(),
                files=tuple(line for line in names.splitlines() if line.strip()),
            )
        )
    return commits
