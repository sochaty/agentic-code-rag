"""Eval charts as standalone SVG, drawn from dashboard.json. No plotting library.

The README and the blog embed these files, so they're regenerated from the same numbers the
dashboard shows (`acr eval charts`) instead of being redrawn by hand when results change.
White background on purpose: the images must read the same in GitHub's light and dark themes,
on dev.to and on Medium.
"""

from html import escape

from agentic_rag.evaluation.dashboard import Dashboard, Interval

FONT = "font-family=\"system-ui, -apple-system, 'Segoe UI', sans-serif\""
INK = "#18181b"
MUTED = "#71717a"
GRID = "#e4e4e7"
NAIVE = "#a1a1aa"
AGENT = "#18181b"
OTHER = "#71717a"
CATEGORIES = ["lookup", "conceptual", "identifier", "call_graph", "history", "existence"]
LABELS = {
    "lookup": "Lookup",
    "conceptual": "Conceptual",
    "identifier": "Identifier",
    "call_graph": "Call graph",
    "history": "History",
    "existence": "Existence",
    "heldout": "held-out",
    "fresh": "fresh",
    "dev": "dev",
    "all": "all",
}


def _svg(width: int, height: int, body: list[str], title: str) -> str:
    return "\n".join(
        [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
            f'width="{width}" height="{height}" {FONT} role="img" aria-label="{escape(title)}">',
            f"<title>{escape(title)}</title>",
            f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
            *body,
            "</svg>",
        ]
    )


def _text(x: float, y: float, s: str, size: int = 13, fill: str = INK, **attrs: str) -> str:
    extra = " ".join(f'{k.replace("_", "-")}="{v}"' for k, v in attrs.items())
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" {extra}>{escape(s)}</text>'
    )


def _ticks(start: float) -> list[float]:
    """Round gridlines from `start` to 100%: every 10 points, or 20 when that's too many."""
    step = 0.1 if 1 - start <= 0.5 + 1e-9 else 0.2
    ticks, t = [], 1.0
    while t >= start - 1e-9:
        ticks.append(round(t, 2))
        t -= step
    return sorted(ticks)


def _pct(v: float) -> str:
    return f"{round(v * 100)}%"


def _tone(config: str) -> str:
    return NAIVE if config == "naive" else AGENT if config == "full" else OTHER


def _whisker(x0: float, x1: float, y: float, h: float = 10) -> list[str]:
    return [
        f'<line x1="{x0:.1f}" x2="{x1:.1f}" y1="{y:.1f}" y2="{y:.1f}" stroke="{INK}" stroke-width="1.5"/>',
        f'<line x1="{x0:.1f}" x2="{x0:.1f}" y1="{y - h / 2:.1f}" y2="{y + h / 2:.1f}" stroke="{INK}" stroke-width="1.5"/>',
        f'<line x1="{x1:.1f}" x2="{x1:.1f}" y1="{y - h / 2:.1f}" y2="{y + h / 2:.1f}" stroke="{INK}" stroke-width="1.5"/>',
    ]


def accuracy(board: Dashboard, split: str, title: str) -> str:
    """Horizontal bars per configuration; the whisker is the bootstrap 95% interval."""
    view = board.splits[split]
    configs = [c.name for c in board.configs if c.name in view.accuracy]
    row, top, left, right = 34, 70, 150, 70
    width = 720
    height = top + row * len(configs) + 50
    start = max(0.0, int(min(view.accuracy[c].low for c in configs) * 10) / 10 - 0.1)
    plot = width - left - right

    def x(v: float) -> float:
        return left + (v - start) / (1 - start) * plot

    body = [
        _text(20, 30, title, 17, weight="600"),
        _text(
            20,
            52,
            f"{view.questions} {LABELS.get(split, split)} questions · whisker = 95% interval (paired bootstrap)",
            12,
            MUTED,
        ),
    ]
    for tick in _ticks(start):
        body.append(
            f'<line x1="{x(tick):.1f}" x2="{x(tick):.1f}" y1="{top - 8}" y2="{height - 40}" stroke="{GRID}"/>'
        )
        body.append(_text(x(tick), height - 22, _pct(tick), 11, MUTED, text_anchor="middle"))
    for i, c in enumerate(configs):
        a: Interval = view.accuracy[c]
        y = top + i * row
        body.append(_text(left - 12, y + 15, c, 13, INK, text_anchor="end"))
        body.append(
            f'<rect x="{left}" y="{y + 3}" width="{x(a.value) - left:.1f}" height="18" rx="3" fill="{_tone(c)}"/>'
        )
        body += _whisker(x(a.low), x(a.high), y + 12)
        body.append(_text(width - right + 12, y + 16, _pct(a.value), 13, INK, weight="600"))
    return _svg(width, height, body, title)


def _place(
    points: list[tuple[str, float, float]], right: float
) -> list[tuple[str, float, float, float, float]]:
    """Labels beside lone points; stacked in a column beside a cluster (as in the web UI)."""
    groups: list[list[tuple[str, float, float]]] = []
    for p in points:
        home = next(
            (g for g in groups if any(abs(q[1] - p[1]) + abs(q[2] - p[2]) < 45 for q in g)), None
        )
        if home is None:
            groups.append([p])
        else:
            home.append(p)
    placed = []
    for g in groups:
        g.sort(key=lambda p: p[2])
        column = max(p[1] for p in g) + (20 if len(g) > 1 else 10)
        middle = sum(p[2] for p in g) / len(g)
        for i, (name, px, py) in enumerate(g):
            ly = middle - (len(g) - 1) * 8 + i * 16 + 4 if len(g) > 1 else py + 4
            placed.append((name, px, py, min(column, right - len(name) * 7), ly))
    # Neighbouring groups can still collide: push overlapping labels down, top to bottom.
    placed.sort(key=lambda p: p[4])
    for i, (name, px, py, lx, ly) in enumerate(placed):
        for other in placed[:i]:
            if abs(other[3] - lx) < max(len(other[0]), len(name)) * 7 and ly - other[4] < 16:
                ly = other[4] + 16
        placed[i] = (name, px, py, lx, ly)
    return placed


def cost_accuracy(board: Dashboard, split: str, title: str) -> str:
    view = board.splits[split]
    width, height = 720, 420
    left, right, top, bottom = 70, 40, 70, 60
    costs = [s.cost_usd for s in view.summaries]
    accs = [s.accuracy for s in view.summaries]
    spread = (max(costs) - min(costs)) or max(costs)
    c0, c1 = max(0.0, min(costs) - spread * 0.15), max(costs) + spread * 0.45
    a0 = max(0.0, int((min(accs) - 0.05) * 10) / 10)

    def x(v: float) -> float:
        return left + (v - c0) / (c1 - c0) * (width - left - right)

    def y(v: float) -> float:
        return top + (1 - (v - a0) / (1 - a0)) * (height - top - bottom)

    body = [
        _text(20, 30, title, 17, weight="600"),
        _text(
            20,
            52,
            "Mean cost to answer one question (judge excluded). Up and to the left is better.",
            12,
            MUTED,
        ),
    ]
    for a in _ticks(a0):
        body.append(
            f'<line x1="{left}" x2="{width - right}" y1="{y(a):.1f}" y2="{y(a):.1f}" stroke="{GRID}"/>'
        )
        body.append(_text(left - 8, y(a) + 4, _pct(a), 11, MUTED, text_anchor="end"))
    for i in range(3):
        c = c0 + i * (c1 - c0) / 2
        anchor = "start" if i == 0 else "end" if i == 2 else "middle"
        body.append(_text(x(c), height - bottom + 20, f"${c:.4f}", 11, MUTED, text_anchor=anchor))
    points = [(s.config, x(s.cost_usd), y(s.accuracy)) for s in view.summaries]
    for name, px, py, lx, ly in _place(points, width - right):
        if abs(ly - 4 - py) > 3 or lx - px > 12:
            body.append(
                f'<line x1="{px:.1f}" y1="{py:.1f}" x2="{lx - 3:.1f}" y2="{ly - 4:.1f}" stroke="{GRID}" stroke-width="1.2"/>'
            )
        body.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="6" fill="{_tone(name)}"/>')
        body.append(_text(lx, ly, name, 12))
    return _svg(width, height, body, title)


def categories(board: Dashboard, split: str, title: str) -> str:
    view = board.splits[split]
    cats = [c for c in CATEGORIES if any(c in s.by_category for s in view.summaries)]
    left, top, cell_w, cell_h = 140, 80, 92, 30
    width = left + cell_w * len(cats) + 20
    height = top + cell_h * len(view.summaries) + 20
    body = [
        _text(20, 30, title, 17, weight="600"),
        _text(
            20,
            52,
            f"Accuracy by question category · {view.questions} {LABELS.get(split, split)} questions",
            12,
            MUTED,
        ),
    ]
    for j, c in enumerate(cats):
        body.append(
            _text(
                left + j * cell_w + cell_w / 2, top - 10, LABELS[c], 12, MUTED, text_anchor="middle"
            )
        )
    for i, s in enumerate(view.summaries):
        y = top + i * cell_h
        body.append(_text(left - 12, y + 20, s.config, 13, INK, text_anchor="end"))
        for j, c in enumerate(cats):
            v = s.by_category.get(c)
            x = left + j * cell_w
            # red (0%) through amber to green (100%), as in the web UI
            fill = f"hsl({round((v or 0) * 120)}, 70%, 78%)" if v is not None else "#f4f4f5"
            body.append(
                f'<rect x="{x + 2}" y="{y + 2}" width="{cell_w - 4}" height="{cell_h - 4}" rx="4" fill="{fill}"/>'
            )
            body.append(
                _text(
                    x + cell_w / 2,
                    y + 20,
                    "–" if v is None else _pct(v),
                    12,
                    INK,
                    text_anchor="middle",
                )
            )
    return _svg(width, height, body, title)


def versions(rows: list[tuple[str, Dashboard, str]], title: str) -> str:
    """Naive vs the full agent, one group per (label, run, split): the release-over-release view."""
    width = 720
    left, top, group_h = 230, 76, 82
    height = top + group_h * len(rows) + 40
    plot = width - left - 80

    def x(v: float) -> float:
        return left + v * plot

    body = [
        _text(20, 30, title, 17, weight="600"),
        _text(
            20,
            52,
            "Accuracy with 95% interval · each version measured on questions it was never tuned on",
            12,
            MUTED,
        ),
    ]
    for t in [0, 0.25, 0.5, 0.75, 1]:
        body.append(
            f'<line x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{top - 8}" y2="{height - 34}" stroke="{GRID}"/>'
        )
        body.append(_text(x(t), height - 16, _pct(t), 11, MUTED, text_anchor="middle"))
    for i, (label, board, split) in enumerate(rows):
        view = board.splits[split]
        y = top + i * group_h
        body.append(_text(left - 14, y + 26, label, 14, INK, text_anchor="end", weight="600"))
        body.append(
            _text(
                left - 14,
                y + 44,
                f"{view.questions} {LABELS.get(split, split)} questions",
                11,
                MUTED,
                text_anchor="end",
            )
        )
        for k, config in enumerate(["naive", "full"]):
            a = view.accuracy[config]
            by = y + k * 30
            body.append(
                f'<rect x="{left}" y="{by + 4}" width="{x(a.value) - left:.1f}" height="20" rx="3" fill="{_tone(config)}"/>'
            )
            body += _whisker(x(a.low), x(a.high), by + 14)
            name = "single-pass RAG" if config == "naive" else "agent"
            body.append(_text(x(a.high) + 8, by + 18, f"{_pct(a.value)} {name}", 12))
        diff = next(
            (c for c in view.comparisons if c.config == "full" and c.baseline == "naive"), None
        )
        if diff:
            verdict = "significant" if diff.significant else "within noise"
            body.append(
                _text(
                    left,
                    y + 70,
                    f"agent − naive: {diff.diff.value * 100:+.1f} pts [{diff.diff.low * 100:+.1f}, {diff.diff.high * 100:+.1f}] · {verdict}",
                    11,
                    MUTED,
                )
            )
    return _svg(width, height, body, title)
