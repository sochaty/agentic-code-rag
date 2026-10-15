"""Python plugin: tree-sitter parsing, outline chunks, and import-aware reference resolution.

Static resolution in a dynamic language is best-effort. Every edge records *how* it was
resolved so tools (and readers) can tell a certain fact from a guess:

- exact      followed imports, re-exports, enclosing scopes, or `self`/`super()` through the MRO
- receiver   the object is known (e.g. the module-level `request_started`), the method is not
- heuristic  the only symbol in the repo with that name
- ambiguous  a handful of same-named candidates; one edge per candidate
- external   resolves to code outside the repo (stdlib, werkzeug, ...)
- unresolved nothing we can see statically (attributes of locals, dynamic dispatch)
"""

import builtins
import inspect
import re
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import PurePosixPath

import tree_sitter_python
from tree_sitter import Language, Node, Parser

from agentic_rag.ingest.models import (
    Chunk,
    Edge,
    EdgeKind,
    Granularity,
    RawRef,
    Resolution,
    Symbol,
    SymbolKind,
)
from agentic_rag.languages.base import ParsedFile, RepoContext

_LANGUAGE = Language(tree_sitter_python.language())
_BUILTINS = frozenset(dir(builtins))
_DEF_TYPES = frozenset({"function_definition", "class_definition", "decorated_definition"})
_CALLEE = re.compile(r"(super\(\)\.)?[A-Za-z_][\w.]*")
_OVERLOAD = frozenset({"overload", "t.overload", "typing.overload", "typing_extensions.overload"})

MAX_CHUNK_LINES = 120  # longer units are split into overlapping windows
WINDOW_LINES = 100
OVERLAP_LINES = 15
MAX_AMBIGUOUS = 5  # more same-named candidates than this is noise, not a lead

_TARGET_KINDS: dict[EdgeKind, frozenset[SymbolKind]] = {
    "calls": frozenset({"function", "method", "class"}),
    "inherits": frozenset({"class"}),
    "decorated_by": frozenset({"function", "method", "class"}),
    "imports": frozenset({"module", "class", "function", "method", "variable"}),
    "contains": frozenset(),
}
_VARIABLE: frozenset[SymbolKind] = frozenset({"variable"})


def is_test_path(path: PurePosixPath) -> bool:
    name = path.name
    return (
        bool({"tests", "test"} & set(path.parts[:-1]))
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name == "conftest.py"
    )


def module_name(path: PurePosixPath, files: frozenset[PurePosixPath]) -> str:
    """Dotted module name, found by climbing package directories.

    A directory counts as a package if it has an __init__.py, or if its parent does: that
    covers namespace subpackages such as `flask/sansio/`, which ships without one.
    """

    def has_init(directory: PurePosixPath) -> bool:
        return directory / "__init__.py" in files

    packages: list[str] = []
    directory = path.parent
    while directory != PurePosixPath(".") and (has_init(directory) or has_init(directory.parent)):
        packages.insert(0, directory.name)
        directory = directory.parent
    if path.stem == "__init__":
        return ".".join(packages) or path.parent.name or "__init__"
    return ".".join([*packages, path.stem])


def _text(node: Node | None) -> str:
    if node is None or node.text is None:
        return ""
    return node.text.decode("utf-8", errors="replace")


def _line(node: Node) -> int:
    return node.start_point.row + 1


@dataclass(frozen=True)
class _Scope:
    id: str
    qualname: str
    kind: SymbolKind
    class_id: str | None  # the class `self` refers to inside this scope


class _FileParser:
    def __init__(self, path: PurePosixPath, source: bytes, ctx: RepoContext) -> None:
        self.path = path
        self.posix = path.as_posix()
        self.source = source
        self.lines = source.decode("utf-8", errors="replace").splitlines()
        self.is_test = is_test_path(path)
        module = module_name(path, ctx.files)
        self.package = module if path.stem == "__init__" else module.rpartition(".")[0]
        self.out = ParsedFile(path=path, module=module)
        self._ids: set[str] = set()

    def parse(self) -> ParsedFile:
        # Keep `tree` referenced for the whole walk: nodes don't own it, and if it is
        # garbage-collected mid-traversal every node becomes a dangling pointer (segfault).
        tree = Parser(_LANGUAGE).parse(self.source)
        root = tree.root_node
        module = self.out.module
        scope = _Scope(self._unique_id(module), module, "module", None)
        self.out.symbols.append(
            Symbol(
                id=scope.id,
                qualname=module,
                name=module.rpartition(".")[2],
                kind="module",
                language="python",
                path=self.posix,
                start_line=1,
                end_line=max(len(self.lines), 1),
                docstring=self._docstring(root),
                is_test=self.is_test,
            )
        )
        self._walk(root, scope)
        outline = self._outline(root)
        if sum(1 for _, text in outline if text.strip()) >= 3:
            self._emit(scope.id, module, "module_outline", outline, symbol_id=scope.id)
        return self.out

    # ---- traversal -------------------------------------------------------------------

    def _walk(self, node: Node, scope: _Scope) -> None:
        for child in node.named_children:
            if child.type == "decorated_definition":
                definition = child.child_by_field_name("definition")
                if definition is not None:
                    decorators = tuple(
                        _text(d).lstrip("@").strip()
                        for d in child.children
                        if d.type == "decorator"
                    )
                    self._definition(definition, child, decorators, scope)
            elif child.type in ("function_definition", "class_definition"):
                self._definition(child, child, (), scope)
            elif child.type in ("import_statement", "import_from_statement"):
                self._import(child, scope)
            else:
                if child.type == "call":
                    callee = self._callee(child.child_by_field_name("function"))
                    if callee:
                        self._ref(scope.id, "calls", callee, _line(child))
                elif child.type == "expression_statement" and scope.kind in ("module", "class"):
                    self._variable(child, scope)
                self._walk(child, scope)

    def _variable(self, statement: Node, scope: _Scope) -> None:
        """`name = ...` / `name: T = ...` at module or class level, e.g. `current_app = ...`."""
        assignment = next(iter(statement.named_children), None)
        if assignment is None or assignment.type != "assignment":
            return
        target = assignment.child_by_field_name("left")
        if target is None or target.type != "identifier":
            return
        name = _text(target)
        first_line = self.lines[statement.start_point.row].strip()
        self.out.symbols.append(
            Symbol(
                id=self._unique_id(f"{scope.qualname}.{name}", _line(statement)),
                qualname=f"{scope.qualname}.{name}",
                name=name,
                kind="variable",
                language="python",
                path=self.posix,
                start_line=_line(statement),
                end_line=statement.end_point.row + 1,
                parent_id=scope.id,
                signature=first_line[:160],
                is_test=self.is_test,
            )
        )

    def _definition(
        self, node: Node, outer: Node, decorators: tuple[str, ...], scope: _Scope
    ) -> None:
        name = _text(node.child_by_field_name("name"))
        body = node.child_by_field_name("body")
        if not name or body is None:
            return
        if _OVERLOAD & set(decorators):
            return  # typing stubs; the implementation that follows is the real symbol
        qualname = f"{scope.qualname}.{name}"
        kind: SymbolKind
        if node.type == "class_definition":
            kind = "class"
        else:
            kind = "method" if scope.kind == "class" else "function"
        symbol_id = self._unique_id(qualname, _line(outer))
        signature = " ".join(
            self.source[node.start_byte : body.start_byte].decode("utf-8", "replace").split()
        ).rstrip(":")
        self.out.symbols.append(
            Symbol(
                id=symbol_id,
                qualname=qualname,
                name=name,
                kind=kind,
                language="python",
                path=self.posix,
                start_line=_line(outer),
                end_line=node.end_point.row + 1,
                parent_id=scope.id,
                signature=signature,
                docstring=self._docstring(body),
                decorators=decorators,
                is_test=self.is_test,
            )
        )
        for decorator in decorators:
            self._ref(symbol_id, "decorated_by", decorator.partition("(")[0].strip(), _line(outer))

        if kind == "class":
            superclasses = node.child_by_field_name("superclasses")
            for base in superclasses.named_children if superclasses is not None else []:
                if base.type in ("identifier", "attribute"):  # skips metaclass=..., Generic[T]
                    self._ref(symbol_id, "inherits", _text(base), _line(base))
            inner = _Scope(symbol_id, qualname, kind, symbol_id)
            self._walk(body, inner)
            self._emit(
                symbol_id, qualname, "class_outline", self._outline(body, header=(outer, body))
            )
        else:
            inner = _Scope(symbol_id, qualname, kind, scope.class_id)
            self._walk(body, inner)
            start, end = outer.start_point.row, node.end_point.row
            numbered = [
                (row + 1, self.lines[row]) for row in range(start, min(end + 1, len(self.lines)))
            ]
            self._emit(symbol_id, qualname, "function", numbered, context=signature)

    def _import(self, node: Node, scope: _Scope) -> None:
        imports = self.out.imports
        if node.type == "import_statement":
            for name_node in node.children_by_field_name("name"):
                if name_node.type == "aliased_import":
                    target = _text(name_node.child_by_field_name("name"))
                    imports[_text(name_node.child_by_field_name("alias"))] = target
                else:
                    target = _text(name_node)
                    head = target.partition(".")[0]
                    imports.setdefault(head, head)
                self._ref(scope.id, "imports", target, _line(node))
            return

        base = self._from_module(node.child_by_field_name("module_name"))
        if any(child.type == "wildcard_import" for child in node.children):
            self.out.star_imports.append(base)
            self._ref(scope.id, "imports", base, _line(node))
        for name_node in node.children_by_field_name("name"):
            if name_node.type == "aliased_import":
                name = _text(name_node.child_by_field_name("name"))
                alias = _text(name_node.child_by_field_name("alias"))
            else:
                name = alias = _text(name_node)
            target = f"{base}.{name}" if base else name
            imports[alias] = target
            self._ref(scope.id, "imports", target, _line(node))

    def _from_module(self, node: Node | None) -> str:
        if node is None:
            return ""
        if node.type != "relative_import":
            return _text(node)
        dots = sum(
            _text(child).count(".") for child in node.children if child.type == "import_prefix"
        )
        parts = self.package.split(".") if self.package else []
        if dots > 1:
            parts = parts[: max(len(parts) - (dots - 1), 0)]
        dotted = next((c for c in node.children if c.type == "dotted_name"), None)
        if dotted is not None:
            parts += _text(dotted).split(".")
        return ".".join(parts)

    # ---- helpers ---------------------------------------------------------------------

    @staticmethod
    def _callee(node: Node | None) -> str | None:
        if node is None or node.type not in ("identifier", "attribute"):
            return None
        compact = "".join(_text(node).split())
        return compact if _CALLEE.fullmatch(compact) else None

    @staticmethod
    def _docstring(body: Node) -> str | None:
        first = next(iter(body.named_children), None)
        if first is None or first.type != "expression_statement":
            return None
        string = next(iter(first.named_children), None)
        if string is None or string.type != "string":
            return None
        content = "".join(_text(c) for c in string.named_children if c.type == "string_content")
        paragraph = inspect.cleandoc(content).split("\n\n")[0].strip()
        return paragraph[:400] or None

    def _outline(
        self, block: Node, header: tuple[Node, Node] | None = None
    ) -> list[tuple[int, str]]:
        """Source of a block with nested function/class bodies collapsed to `...`."""
        rows: list[int] = []
        if header is not None:
            outer, body = header
            rows += self._header_rows(outer, body)
        for child in block.named_children:
            if child.type in _DEF_TYPES:
                definition = (
                    child.child_by_field_name("definition")
                    if child.type == "decorated_definition"
                    else child
                )
                nested_body = (
                    definition.child_by_field_name("body") if definition is not None else None
                )
                if nested_body is None:
                    continue
                header_rows = self._header_rows(child, nested_body)
                rows += header_rows
                rows.append(-(header_rows[-1] + 1))  # sentinel: emit "..." after this row
            else:
                rows += range(child.start_point.row, child.end_point.row + 1)
        numbered: list[tuple[int, str]] = []
        seen: set[int] = set()
        for row in rows:
            if row < 0:
                last = -row - 1
                indent = re.match(r"\s*", self.lines[last])
                pad = indent.group(0) if indent else ""
                numbered.append((last + 1, f"{pad}    ..."))
            elif row not in seen and row < len(self.lines):
                seen.add(row)
                numbered.append((row + 1, self.lines[row]))
        return numbered

    @staticmethod
    def _header_rows(outer: Node, body: Node) -> list[int]:
        first = outer.start_point.row
        last = body.start_point.row - 1 if body.start_point.row > first else first
        return list(range(first, last + 1))

    def _emit(
        self,
        base_id: str,
        title: str,
        granularity: Granularity,
        numbered: list[tuple[int, str]],
        symbol_id: str | None = None,
        context: str | None = None,
    ) -> None:
        if not numbered:
            return
        suffix = "outline" if granularity != "function" else ""
        windows: list[list[tuple[int, str]]]
        if len(numbered) <= MAX_CHUNK_LINES:
            windows = [numbered]
        else:
            step = WINDOW_LINES - OVERLAP_LINES
            windows = []
            for start in range(0, len(numbered), step):
                windows.append(numbered[start : start + WINDOW_LINES])
                if start + WINDOW_LINES >= len(numbered):
                    break
        for part, window in enumerate(windows):
            self.out.chunks.append(
                Chunk(
                    id=f"{base_id}#{suffix}{part}",
                    kind="code",
                    granularity=granularity,
                    path=self.posix,
                    start_line=window[0][0],
                    end_line=window[-1][0],
                    title=title,
                    text="\n".join(text for _, text in window),
                    language="python",
                    symbol_id=symbol_id or base_id,
                    part=part,
                    context=context if part > 0 else None,
                    is_test=self.is_test,
                )
            )

    def _ref(self, src_id: str, kind: EdgeKind, raw: str, line: int) -> None:
        if raw:
            self.out.refs.append(RawRef(src_id=src_id, kind=kind, raw=raw, line=line))

    def _unique_id(self, qualname: str, line: int | None = None) -> str:
        candidate = f"{self.posix}::{qualname}"
        if candidate in self._ids:
            candidate = f"{candidate}@{line}"  # conditional redefinitions, e.g. in if/else
        self._ids.add(candidate)
        return candidate


class _Resolver:
    def __init__(self, files: list[ParsedFile]) -> None:
        self.by_id: dict[str, Symbol] = {}
        self.by_qual: dict[str, list[Symbol]] = defaultdict(list)
        self.by_name: dict[str, list[Symbol]] = defaultdict(list)
        self.members: dict[str, dict[str, str]] = defaultdict(dict)
        self.file_of: dict[str, ParsedFile] = {}
        self.modules: dict[str, list[ParsedFile]] = defaultdict(list)
        self.bases: dict[str, list[str]] = defaultdict(list)
        self.external_bases: dict[str, list[str]] = defaultdict(list)
        for parsed in files:
            self.modules[parsed.module].append(parsed)
            for symbol in parsed.symbols:
                self.by_id[symbol.id] = symbol
                self.by_qual[symbol.qualname].append(symbol)
                if symbol.kind != "module":
                    self.by_name[symbol.name].append(symbol)
                self.file_of[symbol.id] = parsed
                if symbol.parent_id:
                    self.members[symbol.parent_id].setdefault(symbol.name, symbol.id)
        self.top_packages = {module.partition(".")[0] for module in self.modules}

    def run(self, files: list[ParsedFile]) -> list[Edge]:
        refs = [ref for parsed in files for ref in parsed.refs]
        edges: list[Edge] = []
        # Inheritance first: `self.x` lookups walk the MRO built from these edges.
        for ref in refs:
            if ref.kind == "inherits":
                found = self._resolve(ref)
                edges += found
                for edge in found:
                    if edge.resolution in ("exact", "heuristic"):
                        self.bases[edge.src].append(edge.dst)
                    elif edge.resolution == "external":
                        self.external_bases[edge.src].append(edge.dst)
        for ref in refs:
            if ref.kind != "inherits":
                edges += self._resolve(ref)
        unique: dict[tuple[str, str, str], Edge] = {}
        for edge in edges:
            unique.setdefault((edge.src, edge.dst, edge.kind), edge)
        return list(unique.values())

    def _resolve(self, ref: RawRef) -> list[Edge]:
        raw, kinds = ref.raw, _TARGET_KINDS[ref.kind]
        src = self.by_id[ref.src_id]
        parsed = self.file_of[src.id]

        def edges(symbols: list[Symbol], resolution: Resolution) -> list[Edge]:
            if len(symbols) > 1 and resolution == "exact":
                resolution = "ambiguous"
            return [
                Edge(
                    src=src.id,
                    dst=s.id,
                    kind=ref.kind,
                    resolution=resolution,
                    line=ref.line,
                    raw=raw,
                )
                for s in symbols
            ]

        def leftover(dst: str, resolution: Resolution) -> list[Edge]:
            return [
                Edge(
                    src=src.id,
                    dst=dst,
                    kind=ref.kind,
                    resolution=resolution,
                    line=ref.line,
                    raw=raw,
                )
            ]

        if ref.kind == "imports":
            if found := self._qualified(raw, kinds):
                return edges(found, "exact")
            local = raw.partition(".")[0] in self.top_packages
            return leftover(raw, "unresolved" if local else "external")

        head, _, rest = raw.partition(".")
        cls = self._enclosing_class(src)
        if raw.startswith("super()."):
            member = raw.removeprefix("super().")
            if cls and "." not in member:
                for ancestor in self._mro(cls)[1:]:
                    if member_id := self.members[ancestor].get(member):
                        return edges([self.by_id[member_id]], "exact")
                if external := self._external_base(cls):
                    return leftover(f"{external}.{member}", "external")
            return leftover(raw, "unresolved")
        if head in ("self", "cls") and rest and cls:
            member, _, tail = rest.partition(".")
            for ancestor in self._mro(cls):
                if member_id := self.members[ancestor].get(member):
                    found_member = self.by_id[member_id]
                    if not tail:
                        return edges([found_member], "exact")
                    if found_member.kind == "variable":  # self.session_interface.open_session()
                        return edges([found_member], "receiver")
                    break
            else:
                if not tail and (external := self._external_base(cls)):
                    return leftover(f"{external}.{member}", "external")

        for scope_qualname in self._lexical_scopes(src):
            if found := self._qualified(f"{scope_qualname}.{raw}", kinds):
                return edges(found, "exact")
        target = (
            parsed.imports[head] + (f".{rest}" if rest else "") if head in parsed.imports else None
        )
        if target and (found := self._qualified(target, kinds)):
            return edges(found, "exact")
        for star in parsed.star_imports:
            if found := self._qualified(f"{star}.{raw}", kinds):
                return edges(found, "exact")
        if receiver := self._receiver(raw, src, parsed):
            return edges(receiver, "receiver")
        if target and target.partition(".")[0] not in self.top_packages:
            return leftover(target, "external")
        if head in _BUILTINS and head not in parsed.imports:
            return []

        name = raw.rpartition(".")[2]
        candidates = [s for s in self.by_name.get(name, []) if s.kind in kinds]
        if len(candidates) == 1:
            return edges(candidates, "heuristic")
        if 1 < len(candidates) <= MAX_AMBIGUOUS:
            return edges(candidates, "ambiguous")
        return leftover(raw, "unresolved")

    def _qualified(self, target: str, kinds: frozenset[SymbolKind], depth: int = 0) -> list[Symbol]:
        """Look a dotted name up, following re-exports and class members through the MRO."""
        found = [s for s in self.by_qual.get(target, []) if s.kind in kinds]
        if found or depth > 5:
            return found
        parts = target.split(".")
        for i in range(len(parts) - 1, 0, -1):
            prefix, name = ".".join(parts[:i]), parts[i]
            for parsed in self.modules.get(prefix, []):
                if name in parsed.imports and parsed.imports[name] != target:
                    rerouted = ".".join([parsed.imports[name], *parts[i + 1 :]])
                    if found := self._qualified(rerouted, kinds, depth + 1):
                        return found
            if i == len(parts) - 1:
                for owner in self.by_qual.get(prefix, []):
                    if owner.kind == "class":
                        for ancestor in self._mro(owner.id):
                            if member_id := self.members[ancestor].get(name):
                                return [self.by_id[member_id]]
        return []

    def _receiver(self, raw: str, src: Symbol, parsed: ParsedFile) -> list[Symbol]:
        """For `a.b.method`, find the longest prefix that names a known variable."""
        parts = raw.split(".")
        for i in range(len(parts) - 1, 0, -1):
            prefix = ".".join(parts[:i])
            candidates = [f"{scope}.{prefix}" for scope in self._lexical_scopes(src)]
            if parts[0] in parsed.imports:
                candidates.append(".".join([parsed.imports[parts[0]], *parts[1:i]]))
            for candidate in candidates:
                if found := self._qualified(candidate, _VARIABLE):
                    return found
        return []

    def _external_base(self, class_id: str) -> str | None:
        for ancestor in self._mro(class_id):
            if self.external_bases.get(ancestor):
                return self.external_bases[ancestor][0]
        return None

    def _enclosing_class(self, symbol: Symbol) -> str | None:
        current: Symbol | None = symbol
        while current is not None:
            if current.kind == "class":
                return current.id
            current = self.by_id.get(current.parent_id) if current.parent_id else None
        return None

    def _lexical_scopes(self, symbol: Symbol) -> Iterator[str]:
        """Enclosing function and module scopes, innermost first (class bodies are not scopes)."""
        current: Symbol | None = symbol
        while current is not None:
            if current.kind != "class":
                yield current.qualname
            current = self.by_id.get(current.parent_id) if current.parent_id else None

    def _mro(self, class_id: str) -> list[str]:
        order: list[str] = []
        queue = [class_id]
        while queue:
            current = queue.pop(0)
            if current not in order:
                order.append(current)
                queue += self.bases.get(current, [])
        return order


class PythonPlugin:
    name: str = "python"
    extensions: tuple[str, ...] = (".py", ".pyi")

    def parse(self, path: PurePosixPath, source: bytes, ctx: RepoContext) -> ParsedFile:
        return _FileParser(path, source, ctx).parse()

    def resolve(self, files: list[ParsedFile]) -> list[Edge]:
        return _Resolver(files).run(files)
