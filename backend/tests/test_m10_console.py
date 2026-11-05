"""M10: the Rich terminal views read the same answer and events as the API."""

from rich.console import Console

from agentic_rag import console as view
from agentic_rag.agent import events as ev
from agentic_rag.workspace import Workspace

from .test_agent_m3 import CALLERS, ScriptedLLM, _plan, _route, run, sufficiency
from .test_agent_m5 import NORMALIZE, ask, code, draft, search, verdicts


def _text(renderable: object) -> str:
    out = Console(record=True, width=120, color_system=None)
    out.print(renderable)
    return out.export_text()


def test_answer_view_marks_each_claim_and_lists_removed_ones(sample_ws: Workspace) -> None:
    llm = ScriptedLLM(
        _route("lookup"),
        draft((NORMALIZE, [code("src/shop/util.py", 5, 6)]), ("Found by search.", [search()])),
        verdicts((0, "supported"), (1, "partial")),
    )
    text = _text(view.answer_view(ask(sample_ws, llm)))
    assert "✓ `normalize` strips whitespace" in text or "✓ normalize" in text
    assert "src/shop/util.py:5-6" in text
    assert "~ Found by search." in text
    assert "1/2 claims verified" in text
    assert "route direct (lookup)" in text


def test_trace_view_shows_rounds_tools_and_the_check(sample_ws: Workspace) -> None:
    llm = ScriptedLLM(_route(), _plan([CALLERS]), sufficiency(True))
    text = _text(view.trace_view(run(sample_ws, llm, "who calls normalize?")))
    assert "Round 1" in text
    assert "symbol_graph · callers of normalize" in text
    assert "read_source · src/shop/util.py:1-2" in text  # a follow-up read
    assert "✓ enough evidence" in text


def test_live_status_follows_the_events() -> None:
    class FakeStatus:
        def __init__(self) -> None:
            self.lines: list[str] = []

        def update(self, text: str) -> None:
            self.lines.append(text)

    status = FakeStatus()
    sink = view.LiveStatus(status)  # type: ignore[arg-type]
    sink(ev.Routed(category="call_graph", route="agentic", reason="r", at=1.0, spent_usd=0.001))
    sink(ev.Synthesized(attempt=1, direct_answer="x", claims=3, at=9.0, spent_usd=0.008))
    assert "call_graph" in status.lines[0] and "planning" in status.lines[0]
    assert "Verifying 3 claim(s)" in status.lines[1] and "$0.0080" in status.lines[1]
