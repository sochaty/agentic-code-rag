"""Repository -> Index. Language-agnostic: code goes through whichever plugin claims the file."""

import subprocess
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from agentic_rag import __version__
from agentic_rag.ingest import docs, gitlog
from agentic_rag.ingest.models import Edge
from agentic_rag.ingest.store import Index
from agentic_rag.languages.base import LanguagePlugin, ParsedFile, RepoContext
from agentic_rag.languages.registry import Registry, default_plugins

MAX_FILE_BYTES = 1_000_000
SKIP_DIRS = frozenset({"_static", "node_modules", ".venv", "venv", "build", "dist"})


def discover(repo: Path) -> list[PurePosixPath]:
    """Tracked files only, so .gitignore is honoured and build output never sneaks in."""
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=repo, check=True, capture_output=True
    ).stdout.decode("utf-8")
    paths = [PurePosixPath(p) for p in out.split("\0") if p]
    return sorted(p for p in paths if not SKIP_DIRS & set(p.parts[:-1]))


def _git_head(repo: Path) -> str:
    return subprocess.run(
        ["git", "describe", "--tags", "--always"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def build(repo: Path, name: str, registry: Registry | None = None) -> Index:
    registry = registry or Registry(default_plugins())
    files = discover(repo)
    ctx = RepoContext(files=frozenset(files))
    index = Index()
    parsed_by_plugin: dict[str, list[ParsedFile]] = defaultdict(list)
    plugins: dict[str, LanguagePlugin] = {}
    skipped: Counter[str] = Counter()

    for path in files:
        full = repo / path
        if full.stat().st_size > MAX_FILE_BYTES:
            skipped["too_large"] += 1
            continue
        plugin = registry.for_path(path)
        if plugin is not None:
            parsed = plugin.parse(path, full.read_bytes(), ctx)
            parsed_by_plugin[plugin.name].append(parsed)
            plugins[plugin.name] = plugin
            index.symbols += parsed.symbols
            index.chunks += parsed.chunks
        elif docs.is_doc(path):
            index.chunks += docs.split(path, full.read_text(encoding="utf-8", errors="replace"))
        else:
            skipped["unsupported"] += 1

    for symbol in index.symbols:
        if symbol.parent_id:
            index.edges.append(
                Edge(src=symbol.parent_id, dst=symbol.id, kind="contains", resolution="exact")
            )
    for plugin_name, parsed_files in parsed_by_plugin.items():
        index.edges += plugins[plugin_name].resolve(parsed_files)

    index.commits = gitlog.read_commits(repo)
    index.manifest = _manifest(index, name, repo, files, skipped, sorted(plugins))
    return index


def _manifest(
    index: Index,
    name: str,
    repo: Path,
    files: list[PurePosixPath],
    skipped: Counter[str],
    languages: list[str],
) -> dict[str, object]:
    resolution: dict[str, Counter[str]] = defaultdict(Counter)
    for edge in index.edges:
        resolution[edge.kind][edge.resolution] += 1
    return {
        "name": name,
        "repo": str(repo.resolve()),
        "ref": _git_head(repo),
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "tool_version": __version__,
        "languages": languages,
        "files": {"tracked": len(files), **dict(skipped)},
        "chunks": dict(Counter(f"{c.kind}:{c.granularity}" for c in index.chunks)),
        "symbols": dict(Counter(s.kind for s in index.symbols)),
        "edges": {kind: dict(counts) for kind, counts in sorted(resolution.items())},
        "commits": len(index.commits),
    }
