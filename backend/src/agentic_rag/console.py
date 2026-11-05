"""Terminal output for `acr ask` and `acr explore`: a live status line while the agent works,
then the answer with each claim's verdict, and (with --trace) the investigation as a tree.

It reads the same typed events the API streams, so the CLI can never disagree with the UI
about what happened. `--plain` keeps the old text output for scripts and logs.
"""

from collections.abc import Callable

from rich.console import Console, Group, RenderableType
from rich.markdown import Markdown
from rich.panel import Panel
from rich.status import Status
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from agentic_rag.agent import events as ev
from agentic_rag.agent.answer import Answer, citation_labels
from agentic_rag.agent.calls import (
    ExactSearch,
    GitHistory,
    ReadSource,
    SemanticSearch,
    SymbolGraph,
    ToolCall,
)
from agentic_rag.agent.explore import Exploration

VERDICTS = {
    "supported": ("✓", "green"),
    "partial": ("~", "yellow"),
    "unverified": ("?", "dim"),
    "unsupported": ("✗", "red"),
}


def describe(call: ToolCall) -> str:
    """One line per tool call, e.g. `symbol_graph · callers of normalize`."""
    match call:
        case SemanticSearch():
            what = f'"{call.query}" in {call.scope}'
        case ExactSearch():
            what = f'"{call.term}"' + (" (whole word)" if call.whole_word else "")
            what += f" under {call.path_prefix}" if call.path_prefix else ""
        case SymbolGraph():
            what = f"{call.relation} of {call.symbol}"
        case GitHistory():
            what = call.target
        case ReadSource():
            what = f"{call.path}:{call.start_line}-{call.end_line}"
    return f"{call.tool} · {what}"


class LiveStatus:
    """An event sink that keeps one status line up to date while a question runs."""

    def __init__(self, status: Status) -> None:
        self.status = status
        self.running = 0

    def __call__(self, event: ev._Event) -> None:
        stage = self._stage(event)
        if stage:
            self.status.update(f"{stage}  [dim]${event.spent_usd:.4f} · {event.at:.0f}s[/]")

    def _stage(self, event: ev._Event) -> str | None:
        match event:
            case ev.RunStarted():
                return "Routing the question…"
            case ev.Routed(route="direct"):
                return f"[bold]{event.category}[/] → one search…"
            case ev.Routed():
                return f"[bold]{event.category}[/] → planning…"
            case ev.Planned():
                return f"Round {event.round}: planned {len(event.plan.steps)} tool call(s)…"
            case ev.ToolStarted():
                self.running += 1
                return f"Running {describe(event.call)}…"
            case ev.ToolFinished():
                self.running = max(0, self.running - 1)
                return f"Round {event.round}: {self.running} tool call(s) still running…"
            case ev.Checked(sufficiency=s) if s.sufficient:
                return "Enough evidence → writing the answer…"
            case ev.Checked():
                return "Evidence missing → planning another round…"
            case ev.ExplorationDone():
                return "Writing the answer…"
            case ev.Synthesized():
                return f"Verifying {event.claims} claim(s) against the cited source…"
            case ev.Repairing():
                return f"Repairing {len(event.claims)} unsupported claim(s)…"
        return None


def run_with_status(console: Console, work: Callable[[LiveStatus], Answer]) -> Answer:
    with console.status("Starting…", spinner="dots") as status:
        return work(LiveStatus(status))


def answer_view(answer: Answer) -> Group:
    claims = Table.grid(padding=(0, 1))
    claims.add_column(no_wrap=True)
    claims.add_column(ratio=1)
    for claim in answer.claims:
        mark, color = VERDICTS[claim.verdict]
        body = Text.from_markup(
            f"{_escape(claim.text)}\n[cyan]{citation_labels(claim.citations)}[/]"
        )
        claims.add_row(Text(mark, style=f"bold {color}"), body)
    parts: list[RenderableType] = [Markdown(answer.direct_answer), Text()]
    if answer.claims:
        parts.append(claims)
    if answer.caveats:
        parts += [
            Text("\nCaveats", style="bold"),
            *[Text(f"• {c}", style="dim") for c in answer.caveats],
        ]
    if answer.removed:
        parts.append(Text("\nRemoved (couldn't be verified against the cited source)", "bold red"))
        parts += [Text(f"✗ {c.text} — {c.reason}", style="red") for c in answer.removed]
    title = "Answer" + (" · insufficient evidence" if answer.insufficient else "")
    panel = Panel(Group(*parts), title=title, title_align="left", border_style="blue")
    return Group(panel, _footer(answer))


def _footer(answer: Answer) -> Table:
    e, u = answer.exploration, answer.usage
    table = Table.grid(padding=(0, 2))
    for _ in range(5):
        table.add_column(style="dim")
    verified = sum(c.verdict == "supported" for c in answer.claims)
    table.add_row(
        f"route {e.route.route} ({e.route.category})",
        f"{len(e.rounds)} round(s) · stopped: {e.stop_reason}"
        + (" · repaired once" if answer.repaired else ""),
        f"{verified}/{len(answer.claims) + len(answer.removed)} claims verified",
        f"{u.calls} model calls · {u.input_tokens + u.cache_read_tokens:,} in"
        f" / {u.output_tokens:,} out",
        f"${u.cost_usd:.4f} · {answer.latency_s:.1f}s",
    )
    return table


def trace_view(exploration: Exploration) -> Tree:
    route = exploration.route
    routed = f"routed {route.category} → {route.route}: {_escape(route.reason)}"
    tree = Tree(f"[bold]{_escape(exploration.question)}[/]\n[dim]{routed}[/]")
    for r in exploration.rounds:
        node = tree.add(f"[bold]Round {r.number}[/]" + (" (direct)" if r.plan is None else ""))
        if r.plan is not None:
            for q in r.plan.sub_questions:
                node.add(f"[magenta]?[/] {_escape(q)}")
        for obs in r.observations:
            style = "red" if obs.error else "cyan"
            first = (obs.error or obs.text).splitlines()[0] if (obs.error or obs.text) else ""
            detail = f"{obs.elapsed_ms} ms · {_escape(first[:90])}"
            node.add(f"[{style}]{_escape(describe(obs.call))}[/] [dim]{detail}[/]")
        if r.grades:
            kept = sum(g.verdict != "irrelevant" for g in r.grades)
            node.add(f"[dim]graded {len(r.grades)} hit(s): kept {kept}[/]")
        for rw in r.rewrites:
            node.add(f"[yellow]rewrite[/] {_escape(rw.original)} → {_escape(rw.rewritten)}")
        if r.sufficiency is not None:
            ok = r.sufficiency.sufficient
            node.add("[green]✓ enough evidence[/]" if ok else "[yellow]… evidence missing[/]")
    tree.add(f"[dim]stopped: {exploration.stop_reason} · {exploration.budget}[/]")
    return tree


def _escape(text: str) -> str:
    return text.replace("[", r"\[")
