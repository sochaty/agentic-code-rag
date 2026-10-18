"""exact_search: literal matches across every tracked text file (code, docs, config, templates)."""

from pathlib import PurePosixPath

from pydantic import BaseModel

from agentic_rag.languages.python import is_test_path
from agentic_rag.workspace import Workspace

PER_FILE = 8


class GrepHit(BaseModel):
    path: str
    line: int
    text: str


class GrepResult(BaseModel):
    term: str
    case_sensitive: bool
    total_matches: int
    files_matched: int
    hits: list[GrepHit]

    def render(self) -> str:
        if not self.hits:
            return f"No literal matches for {self.term!r}."
        out = [
            f"{self.total_matches} matches in {self.files_matched} files for {self.term!r}"
            + (f" (showing {len(self.hits)})" if len(self.hits) < self.total_matches else "")
        ]
        current = ""
        for hit in self.hits:
            if hit.path != current:
                current = hit.path
                out.append(f"{hit.path}")
            out.append(f"  {hit.line:>5}: {hit.text.strip()[:200]}")
        return "\n".join(out)


def exact_search(
    ws: Workspace,
    term: str,
    k: int = 40,
    include_tests: bool = True,
    case_sensitive: bool | None = None,
    path_prefix: str | None = None,
) -> GrepResult:
    """Case-sensitive when the term has capitals (like ripgrep's smart case)."""
    if case_sensitive is None:
        case_sensitive = term != term.lower()
    needle = term if case_sensitive else term.lower()

    def sort_key(path: PurePosixPath) -> tuple[bool, str]:
        return is_test_path(path), path.as_posix()

    all_hits: list[GrepHit] = []
    total, files = 0, 0
    for path in sorted(ws.files, key=sort_key):
        if path_prefix and not path.as_posix().startswith(path_prefix):
            continue
        if not include_tests and is_test_path(path):
            continue
        lines = ws.read_lines(path)
        if lines is None:
            continue
        matched = [
            GrepHit(path=path.as_posix(), line=n, text=line)
            for n, line in enumerate(lines, 1)
            if needle in (line if case_sensitive else line.lower())
        ]
        if matched:
            files += 1
            total += len(matched)
            all_hits += matched[:PER_FILE]
    return GrepResult(
        term=term,
        case_sensitive=case_sensitive,
        total_matches=total,
        files_matched=files,
        hits=all_hits[:k],
    )
