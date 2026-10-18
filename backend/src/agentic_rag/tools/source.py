"""read_source: an exact line range, numbered, so answers can cite file:line."""

from pathlib import PurePosixPath

from pydantic import BaseModel

from agentic_rag.workspace import Workspace

MAX_LINES = 200


class SourceRange(BaseModel):
    path: str
    start_line: int
    end_line: int
    total_lines: int
    text: str
    error: str | None = None

    def render(self) -> str:
        if self.error:
            return self.error
        header = f"{self.path}:{self.start_line}-{self.end_line} (of {self.total_lines} lines)"
        return f"{header}\n{self.text}"


def read_source(
    ws: Workspace, path: str, start_line: int = 1, end_line: int | None = None
) -> SourceRange:
    rel = PurePosixPath(path.replace("\\", "/").lstrip("/"))

    def fail(message: str) -> SourceRange:
        return SourceRange(
            path=path, start_line=0, end_line=0, total_lines=0, text="", error=message
        )

    # Paths come from a model: refuse anything that escapes the repo or reaches into .git.
    full = (ws.repo / rel).resolve()
    if not full.is_relative_to(ws.repo.resolve()) or ".git" in rel.parts:
        return fail(f"{path} is outside the repository.")
    lines = ws.read_lines(rel)
    if lines is None:
        return fail(f"{path} does not exist or is not a text file.")
    start = max(start_line, 1)
    end = min(end_line or start + MAX_LINES - 1, len(lines), start + MAX_LINES - 1)
    if start > len(lines):
        return fail(f"{path} has only {len(lines)} lines.")
    width = len(str(end))
    text = "\n".join(f"{n:>{width}} | {lines[n - 1]}" for n in range(start, end + 1))
    return SourceRange(
        path=rel.as_posix(), start_line=start, end_line=end, total_lines=len(lines), text=text
    )
