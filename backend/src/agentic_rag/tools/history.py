"""git_history: when and why a file, folder, or individual symbol changed."""

import subprocess
from collections.abc import Callable, Mapping

from pydantic import BaseModel

from agentic_rag.ingest.models import Symbol
from agentic_rag.tools.graph import find_symbols
from agentic_rag.workspace import Workspace

BODY_CHARS = 400
DIFF_LINES = 12  # changed lines shown per commit; the oldest commit can be the whole symbol
_MARK = "\x1e"  # record separator between commits in git output


class CommitInfo(BaseModel):
    sha: str
    date: str
    author: str
    subject: str
    body: str = ""
    # For symbol history: the lines this commit changed inside the symbol ("-old" / "+new").
    diff: list[str] = []
    more_changed: int = 0


class HistoryResult(BaseModel):
    target: str
    resolved: str | None
    commits: list[CommitInfo]
    note: str | None = None
    # When a bare name matches several symbols (flask.helpers.make_response and
    # Flask.make_response), the runner-up's history too, so "last changed" isn't half an answer.
    also: list["HistoryResult"] = []

    def render(self) -> str:
        if self.resolved is None:
            return self.note or f"Nothing named {self.target!r} in the repo."
        out = [f"History of {self.resolved} (newest first, {len(self.commits)} commits):"]
        for c in self.commits:
            out.append(f"  {c.sha[:10]}  {c.date[:10]}  {c.author}: {c.subject}")
            if c.body:
                out += [f"      {line}" for line in c.body.splitlines()[:6] if line.strip()]
            if c.diff:
                out.append("      changed in this symbol:")
                out += [f"        {line}" for line in c.diff]
                if c.more_changed:
                    out.append(f"        ... {c.more_changed} more changed lines")
        if self.note:
            out.append(self.note)
        for other in self.also:
            out += ["", "Also matches:", other.render()]
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
    candidates = [x for x in symbols if not x.is_test] or symbols
    exact = any(x.qualname == target.strip() for x in candidates)
    also = []
    if len(candidates) > 1 and not exact:
        runner_up = candidates[1]
        also.append(
            HistoryResult(
                target=target,
                resolved=_label(runner_up),
                commits=_symbol_commits(ws, runner_up, max(2, limit // 2), info, by_sha),
            )
        )
    s = candidates[0]
    note = None
    if len(candidates) > 2 and not exact:
        others = ", ".join(x.qualname for x in candidates[2:5])
        note = f"(Matched {len(candidates)} symbols; history shown for two. Others: {others})"
    return HistoryResult(
        target=target,
        resolved=_label(s),
        commits=_symbol_commits(ws, s, limit, info, by_sha),
        note=note,
        also=also,
    )


def _label(s: Symbol) -> str:
    return f"{s.qualname} ({s.path}:{s.start_line}-{s.end_line})"


def _symbol_commits(
    ws: Workspace,
    s: Symbol,
    limit: int,
    info: Callable[[str], CommitInfo],
    by_sha: Mapping[str, object],
) -> list[CommitInfo]:
    # `git log -L` follows the symbol's line range back through every commit that touched it,
    # and its patch shows exactly which of those lines each commit changed.
    out = subprocess.run(
        [
            "git",
            "log",
            f"-L{s.start_line},{s.end_line}:{s.path}",
            f"--format={_MARK}%H",
            f"-n{limit}",
        ],
        cwd=ws.repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).stdout
    commits = []
    for block in out.split(_MARK)[1:]:
        sha, _, patch = block.partition("\n")
        if sha.strip() not in by_sha:
            continue
        changed = [
            line
            for line in patch.splitlines()
            if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
        ]
        commit = info(sha.strip())
        commit.diff = [line[:160] for line in changed[:DIFF_LINES]]
        commit.more_changed = max(len(changed) - DIFF_LINES, 0)
        commits.append(commit)
    return commits
