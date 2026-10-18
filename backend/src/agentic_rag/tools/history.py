"""git_history: when and why a file, folder, or individual symbol changed."""

import subprocess

from pydantic import BaseModel

from agentic_rag.tools.graph import find_symbols
from agentic_rag.workspace import Workspace

BODY_CHARS = 400


class CommitInfo(BaseModel):
    sha: str
    date: str
    author: str
    subject: str
    body: str = ""


class HistoryResult(BaseModel):
    target: str
    resolved: str | None
    commits: list[CommitInfo]
    note: str | None = None

    def render(self) -> str:
        if self.resolved is None:
            return self.note or f"Nothing named {self.target!r} in the repo."
        out = [f"History of {self.resolved} (newest first, {len(self.commits)} commits):"]
        for c in self.commits:
            out.append(f"  {c.sha[:10]}  {c.date[:10]}  {c.author}: {c.subject}")
            if c.body:
                out += [f"      {line}" for line in c.body.splitlines()[:6] if line.strip()]
        if self.note:
            out.append(self.note)
        return "\n".join(out)


def git_history(ws: Workspace, target: str, limit: int = 10) -> HistoryResult:
    by_sha = {c.sha: c for c in ws.index.commits}

    def info(sha: str) -> CommitInfo:
        c = by_sha[sha]
        return CommitInfo(
            sha=c.sha, date=c.date, author=c.author, subject=c.subject, body=c.body[:BODY_CHARS]
        )

    prefix = target.strip().strip("/").replace("\\", "/")
    tracked = {p.as_posix() for p in ws.files}
    if prefix in tracked or any(p.startswith(prefix + "/") for p in tracked):
        commits = [
            info(c.sha)
            for c in ws.index.commits
            if any(f == prefix or f.startswith(prefix + "/") for f in c.files)
        ]
        return HistoryResult(target=target, resolved=prefix, commits=commits[:limit])

    symbols = find_symbols(ws, target)
    if not symbols:
        return HistoryResult(target=target, resolved=None, commits=[])
    s = symbols[0]
    # `git log -L` follows that line range back through every commit that touched it.
    out = subprocess.run(
        [
            "git",
            "log",
            f"-L{s.start_line},{s.end_line}:{s.path}",
            "-s",
            "--format=%H",
            f"-n{limit}",
        ],
        cwd=ws.repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    commits = [info(sha) for sha in out.split() if sha in by_sha]
    note = None
    if len(symbols) > 1:
        others = ", ".join(x.qualname for x in symbols[1:4])
        note = f"(Matched {len(symbols)} symbols; showing the first. Others: {others})"
    return HistoryResult(
        target=target,
        resolved=f"{s.qualname} ({s.path}:{s.start_line}-{s.end_line})",
        commits=commits,
        note=note,
    )
