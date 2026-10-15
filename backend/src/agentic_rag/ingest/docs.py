"""Split reStructuredText and Markdown into heading-delimited sections.

Changelogs (CHANGES/CHANGELOG/HISTORY) use the same splitter; each version heading becomes
its own `changelog` chunk, which is what "when did X change?" questions need.
"""

import re
from pathlib import PurePosixPath

from agentic_rag.ingest.models import Chunk, ChunkKind

DOC_EXTENSIONS = (".rst", ".md")
MAX_SECTION_LINES = 80

_RST_ADORNMENT = re.compile(r"^([=\-~^\"'`*+#:.])\1{2,}\s*$")
_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_CHANGELOG = re.compile(r"^(changes|changelog|history|news)$", re.IGNORECASE)


def is_doc(path: PurePosixPath) -> bool:
    return path.suffix.lower() in DOC_EXTENSIONS


def doc_kind(path: PurePosixPath) -> ChunkKind:
    return "changelog" if _CHANGELOG.match(path.stem) else "doc"


def _rst_headings(lines: list[str]) -> list[tuple[int, int, str]]:
    """(line index, level, title). Levels follow the order adornment styles first appear."""
    styles: list[str] = []
    found: list[tuple[int, int, str]] = []
    i = 0
    while i < len(lines) - 1:
        title, under = lines[i], lines[i + 1]
        match = _RST_ADORNMENT.match(under)
        if (
            title.strip()
            and not _RST_ADORNMENT.match(title)
            and match
            and len(under.rstrip()) >= len(title.rstrip())
        ):
            overlined = i > 0 and lines[i - 1].rstrip() == under.rstrip()
            style = ("over" if overlined else "") + match.group(1)
            if style not in styles:
                styles.append(style)
            found.append((i - 1 if overlined else i, styles.index(style), title.strip()))
            i += 2
            continue
        i += 1
    return found


def _md_headings(lines: list[str]) -> list[tuple[int, int, str]]:
    found: list[tuple[int, int, str]] = []
    in_fence = False
    for i, line in enumerate(lines):
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
        elif not in_fence and (match := _MD_HEADING.match(line)):
            found.append((i, len(match.group(1)) - 1, match.group(2)))
    return found


def split(path: PurePosixPath, text: str) -> list[Chunk]:
    lines = text.splitlines()
    headings = _md_headings(lines) if path.suffix.lower() == ".md" else _rst_headings(lines)
    kind = doc_kind(path)
    posix = path.as_posix()

    # Each section runs from its heading to the next heading of any level.
    bounds = [(0, -1, path.stem)] if not headings or headings[0][0] > 0 else []
    bounds += headings
    chunks: list[Chunk] = []
    trail: list[str] = []
    for n, (start, level, title) in enumerate(bounds):
        end = bounds[n + 1][0] if n + 1 < len(bounds) else len(lines)
        if level >= 0:
            trail = [*trail[:level], title]
        breadcrumb = " > ".join(trail) if level >= 0 else title
        body = lines[start:end]
        if not any(line.strip() for line in body):
            continue
        for part, offset in enumerate(range(0, len(body), MAX_SECTION_LINES)):
            piece = body[offset : offset + MAX_SECTION_LINES]
            while piece and not piece[-1].strip():
                piece = piece[:-1]
            if not piece:
                continue
            first = start + offset + 1
            chunks.append(
                Chunk(
                    id=f"{posix}#L{first}",
                    kind=kind,
                    granularity="section",
                    path=posix,
                    start_line=first,
                    end_line=first + len(piece) - 1,
                    title=breadcrumb,
                    text="\n".join(piece),
                    part=part,
                    context=breadcrumb if part > 0 else None,
                )
            )
    return chunks
