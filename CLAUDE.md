# agentic-code-rag — Claude Instructions

## Read Master Memory First

At session start, always read:
`C:\Users\user\.claude\projects\d--src-sochaty\memory\MEMORY.md`

Then load: `project_agentic_code_rag.md` (full plan + every decision so far), `project_session_orchestration.md`.

## Project Rules

- User commits and pushes manually — never run `git commit` / `git push`.
- Anything that spends Anthropic API credit (eval runs, live end-to-end tests) needs the user's OK and a cost estimate first. CI and unit tests use a mocked LLM.
- Python lives in `backend/` (uv project, Python 3.12). Run tasks with `uv run poe <task>` from `backend/` — no Makefile (Windows dev box has no `make`).
- Language support goes through the `LanguagePlugin` interface (M1). Never special-case a language inside tools or nodes.
- Every agent node emits typed events (`events.py`); CLI, UI, logs and eval all consume that one stream. The core must never import from the API or UI layers.
- Corpora are fetched into `data/corpora/` (gitignored) at the tag pinned in `corpora.toml` — never vendor third-party code into the repo.
- Blog posts for this project are written from the starter-kit session, not here.

## Milestones

M0 scaffold · M1 ingestion + language plugins · M2 tools + naive baseline · M3 router/planner · M4 grade/rewrite/budget · M5 synthesize/verify · M6 graph + events + demo mode · M7 MCP · M8 eval · M9a/b UI · M10 Compose + v1.0.0 · M11 Fly.io demo + blog integration · v1.1: M12 Helm, M13 AWS · v2.0 Go/C#/TS/Angular · v2.1 infra langs.
