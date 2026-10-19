import json
from typing import Any

from agentic_rag.agent.answer import (
    CheckedClaim,
    Citation,
    answer_question,
    cited_text,
    repair_calls,
)
from agentic_rag.agent.budget import Budget
from agentic_rag.agent.calls import SemanticSearch, execute
from agentic_rag.workspace import Workspace

from .test_agent_m3 import BIG, ConstReranker, ScriptedLLM, _route


def code(path: str, start: int, end: int, observation: int = 1) -> dict[str, Any]:
    return {
        "kind": "code",
        "observation": observation,
        "path": path,
        "start_line": start,
        "end_line": end,
        "sha": None,
    }


def search(observation: int = 1) -> dict[str, Any]:
    return {
        "kind": "search",
        "observation": observation,
        "path": None,
        "start_line": None,
        "end_line": None,
        "sha": None,
    }


def draft(
    *claims: tuple[str, list[dict[str, Any]]], answer: str = "It upper-cases the SKU."
) -> str:
    return json.dumps(
        {
            "direct_answer": answer,
            "claims": [{"text": t, "citations": c} for t, c in claims],
            "caveats": [],
            "insufficient": False,
        }
    )


def verdicts(*items: tuple[int, str]) -> str:
    return json.dumps(
        {"items": [{"claim": i, "verdict": v, "reason": f"because {v}"} for i, v in items]}
    )


def ask(ws: Workspace, llm: ScriptedLLM, budget: Budget = BIG) -> Any:
    return answer_question(
        ws,
        llm,
        "What does normalize do?",
        cheap_model="c",
        heavy_model="h",
        budget=budget,
        reranker=ConstReranker(5.0),  # every hit clearly relevant: no grading calls
    )


NORMALIZE = "`normalize` strips whitespace and upper-cases the SKU."


def test_supported_claims_make_the_answer(sample_ws: Workspace) -> None:
    llm = ScriptedLLM(
        _route("lookup"),
        draft(
            (NORMALIZE, [code("src/shop/util.py", 5, 6)]), ("It is found by search.", [search()])
        ),
        verdicts((0, "supported"), (1, "partial")),
    )
    answer = ask(sample_ws, llm)

    assert [c.verdict for c in answer.claims] == ["supported", "partial"]
    assert answer.removed == [] and not answer.repaired
    assert [r["model"] for r in llm.requests] == ["c", "h", "c"]  # route, synthesize, verify
    verify_prompt = llm.requests[2]["messages"][0]["content"]
    assert "6 |     return sku.strip().upper()" in verify_prompt  # re-read from disk
    rendered = answer.render()
    assert "[src/shop/util.py:5-6]" in rendered and "(partly supported)" in rendered


def test_unresolvable_citation_triggers_one_repair(sample_ws: Workspace) -> None:
    llm = ScriptedLLM(
        _route("lookup"),
        draft((NORMALIZE, [code("missing.py", 1, 2)])),  # doesn't resolve: no LLM verdict needed
        draft((NORMALIZE, [code("src/shop/util.py", 5, 6)])),  # after repair
        verdicts((0, "supported")),
    )
    answer = ask(sample_ws, llm)

    assert answer.repaired
    assert [c.verdict for c in answer.claims] == ["supported"]
    # route, synth, synth, verify: the first verify had nothing left to ask the model
    assert [r["model"] for r in llm.requests] == ["c", "h", "h", "c"]
    second_synthesis = llm.requests[2]["messages"][0]["content"]
    assert "symbol_graph(symbol='normalize', relation='definition')" in second_synthesis


def test_claims_that_still_fail_are_removed_and_reported(sample_ws: Workspace) -> None:
    claim = ("`normalize` sends an email.", [code("src/shop/util.py", 5, 6)])
    llm = ScriptedLLM(
        _route("lookup"),
        draft(claim),
        verdicts((0, "unsupported")),
        draft(claim),
        verdicts((0, "unsupported")),
    )
    answer = ask(sample_ws, llm)

    assert answer.claims == []
    assert [c.text for c in answer.removed] == ["`normalize` sends an email."]
    assert "Removed (couldn't be verified" in answer.render()


def test_out_of_budget_answers_but_skips_repair(sample_ws: Workspace) -> None:
    llm = ScriptedLLM(
        _route("lookup"),
        draft((NORMALIZE, [code("missing.py", 1, 2)])),
    )
    tiny = Budget(max_tokens=50, max_seconds=3600, max_cost_usd=1.0)  # the router alone exceeds it
    answer = ask(sample_ws, llm, tiny)

    assert not answer.repaired
    assert answer.direct_answer == "It upper-cases the SKU."  # an answer is always written
    assert len(answer.removed) == 1


def test_cited_text_resolves_each_kind_and_rejects_bad_ranges(sample_ws: Workspace) -> None:
    obs = [
        execute(
            sample_ws,
            SemanticSearch(tool="semantic_search", query="x", scope="all", include_tests=False),
        )
    ]
    ok = Citation.model_validate(code("src/shop/util.py", 5, 6))
    assert "def normalize(sku):" in (cited_text(sample_ws, obs, ok) or "")
    too_long = Citation.model_validate(code("src/shop/cart.py", 1, 200))
    assert cited_text(sample_ws, obs, too_long) is None
    backwards = Citation.model_validate(code("src/shop/util.py", 6, 5))
    assert cited_text(sample_ws, obs, backwards) is None

    sha = sample_ws.index.commits[0].sha
    commit = Citation(
        kind="commit", observation=1, path=None, start_line=None, end_line=None, sha=sha[:8]
    )
    assert "Add VERSION" in (cited_text(sample_ws, obs, commit) or "")
    assert cited_text(sample_ws, obs, Citation.model_validate(search(1))) is not None
    assert cited_text(sample_ws, obs, Citation.model_validate(search(9))) is None


def test_repair_searches_the_claim_and_looks_up_its_identifiers() -> None:
    claim = CheckedClaim(
        text="`Cart.add` calls `helper` and `normalize` and `extra`",
        citations=[],
        verdict="unsupported",
        reason="r",
    )
    calls = repair_calls([claim])
    assert calls[0].tool == "semantic_search"
    assert [getattr(c, "symbol", None) for c in calls[1:]] == ["Cart.add", "helper"]  # capped at 2


def test_symbol_history_shows_what_each_commit_changed(sample_ws: Workspace) -> None:
    from agentic_rag import tools

    module = tools.git_history(sample_ws, "shop.util")
    newest = module.commits[0]
    assert newest.subject == "Add VERSION"
    assert "+VERSION = '1.1'" in newest.diff
    assert "changed in this symbol:" in module.render()
    assert all(line.startswith(("+", "-")) for c in module.commits for line in c.diff)


def test_commit_citation_with_a_path_is_checked_against_its_diff(sample_ws: Workspace) -> None:
    sha = sample_ws.index.commits[0].sha  # "Add VERSION": touched only src/shop/util.py

    def cite(path: str | None) -> str | None:
        c = Citation(
            kind="commit", observation=1, path=path, start_line=None, end_line=None, sha=sha
        )
        return cited_text(sample_ws, [], c)

    assert "+VERSION = '1.1'" in (cite("src/shop/util.py") or "")
    assert cite("src/shop/cart.py") is None  # that commit didn't touch cart.py
    assert "Add VERSION" in (cite(None) or "")


def test_absence_searches_report_their_scope(sample_ws: Workspace) -> None:
    from agentic_rag import tools

    rendered = tools.exact_search(sample_ws, "zzz_absent").render()
    assert "in 9 files searched" in rendered  # every tracked text file was checked


def test_ambiguous_history_covers_the_runner_up(sample_ws: Workspace) -> None:
    from agentic_rag import tools

    result = tools.git_history(sample_ws, "__init__")  # Cart.__init__ and Money.__init__
    assert result.resolved is not None and len(result.also) == 1
    assert "Also matches:" in result.render()


def test_commit_citation_without_path_borrows_its_history_observation(
    sample_ws: Workspace,
) -> None:
    from agentic_rag.agent.calls import GitHistory

    history = execute(sample_ws, GitHistory(tool="git_history", target="shop.util", limit=5))
    sha = sample_ws.index.commits[0].sha
    c = Citation(kind="commit", observation=1, path=None, start_line=None, end_line=None, sha=sha)
    text = cited_text(sample_ws, [history], c) or ""
    assert "From the history observation:" in text and "+VERSION = '1.1'" in text


def test_rendered_citations_are_deduplicated() -> None:
    from agentic_rag.agent.answer import citation_labels

    a = Citation.model_validate(code("a.py", 1, 2))
    b = Citation.model_validate(search(3))
    assert citation_labels([a, b, a]) == "a.py:1-2, search [3]"
