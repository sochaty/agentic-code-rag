# agentic-code-rag

Ask questions about a Python codebase and get answers you can check. An agent decides how to search — by meaning, exact names, the call graph, or git history — throws out weak evidence, tries again when it misses, and cites `file:line` for every claim. And it stops when it hits the budget you set.

> **Status:** early development (M2 — tools + naive baseline). The agent loop isn't built yet; follow along or star the repo.

## Why

Single-pass RAG retrieves once and hopes. That works for "what does `X` do?" and falls apart on "who ends up calling `X` when a request fails, and why was that changed in 2.3?". This project puts an agent in the loop and **measures** what each piece of that loop actually buys — accuracy, cost and latency — against a plain RAG baseline.

## How it works

```
question → router ──simple──→ one-pass retrieve → answer
             └──complex──→ planner → tools (parallel) → rerank-grade
                  → [borderline only → LLM grade] → enough evidence?
                  → no: rewrite & retry (while budget remains)
                  → synthesize with file:line citations → verify each claim
                  → unsupported claim: re-retrieve (while budget remains)
                  → answer, or an honest "not enough evidence"
```

Five tools: semantic search, exact search, symbol/call graph, git history, and source reads. The same tools are exposed as an MCP server.

## Quick start (developers)

Requires [uv](https://docs.astral.sh/uv/) and git.

```bash
cd backend
uv sync                      # creates .venv and installs everything
uv run acr corpus fetch flask  # clones Flask 3.1.3 (the demo corpus) into data/corpora
uv run acr ingest flask      # chunks + symbol graph + history, then embeddings -> data/indexes/flask
uv run poe check             # lint, format check, type check, tests
```

`acr ingest` also takes a path to any local git repo: `uv run acr ingest D:\path\to\repo`.
Embedding runs locally on CPU (FastEmbed, `bge-small-en-v1.5`, ~67 MB download once). For Flask's
2,176 chunks that took 22 minutes on a laptop CPU (one-time per index); `--no-embed` skips it.

## The tools

Every tool works from the CLI today, and the agent will call the same functions:

```bash
uv run acr search flask "how are teardown functions run after a request"   # semantic_search (hybrid)
uv run acr grep   flask SESSION_COOKIE_SAMESITE                             # exact_search
uv run acr symbol flask full_dispatch_request --rel callees                 # symbol_graph
uv run acr history flask Flask.make_response                                # git_history (follows the lines)
uv run acr read   flask src/flask/app.py --start 900 --end 940              # read_source
uv run acr ask    flask "what does preprocess_request do?"                  # naive RAG baseline (calls the model)
uv run acr explore flask "who ends up calling handle_user_exception?"       # agent: route + plan + run tools
```

`acr explore` shows the agent's reasoning so far: the router's decision, each planning round's
sub-questions and tool calls, what every call returned, how semantic hits were graded, any
query rewrites, the sufficiency check, and why the loop stopped. Synthesizing an answer comes
in M5.

How the loop keeps cost down:

- **Grading:** a local cross-encoder (`ms-marco-MiniLM-L-6-v2`) scores every semantic hit.
  Scores ≥ 3 are kept and ≤ −4 dropped for free; only the band in between goes to the cheap
  model, in one batched call. Exact search, the call graph, history and source reads are
  precise, so they aren't graded.
- **Rewrite:** if every hit of a search is dropped, the cheap model rewrites the query once.
- **Sufficiency:** after each round the cheap model checks whether every sub-question is
  answered; if so the loop stops before paying for another planner call.
- **Budget:** per-question limits on tokens, seconds and dollars (`ACR_BUDGET_MAX_TOKENS`,
  `ACR_BUDGET_MAX_SECONDS`, `ACR_BUDGET_MAX_COST_USD`), checked before every model call.

## Model providers

Copy `.env.example` to `.env` (repo root). The default provider is **OpenAI** (`OPENAI_API_KEY`);
set `ACR_PROVIDER=anthropic` and `ANTHROPIC_API_KEY` to use Claude instead. Any Chat Completions
server also works through the OpenAI provider — for example a free local model with
[Ollama](https://ollama.com): `ACR_OPENAI_BASE_URL=http://localhost:11434/v1`.

| Provider | Cheap roles (router, grader, rewriter) | Heavy roles (planner, synthesizer, verifier) |
|---|---|---|
| OpenAI (default) | `gpt-6-luna` | `gpt-6.1-sol` |
| Anthropic | `claude-haiku-5-5` | `claude-sonnet-5-5` |

`acr ask` prints tokens and cost for every question — roughly $0.03–0.05 with the default heavy model.

## What ingestion produces

Plain JSONL files you can open and grep:

| File | Contents |
|---|---|
| `chunks.jsonl` | Functions/methods (long ones split with overlap), class and module outlines with bodies collapsed, doc sections with heading breadcrumbs, one changelog entry per version |
| `symbols.jsonl` | Modules, classes, functions, methods, module/class-level variables — with signature, first docstring paragraph, decorators and exact line spans |
| `edges.jsonl` | `contains`, `calls`, `inherits`, `decorated_by`, `imports` — each labelled with **how** it was resolved |
| `commits.jsonl` | Full history: subject, body, author, date and touched files |
| `manifest.json` | Counts, including the resolution breakdown below |

Static analysis of a dynamic language can't see everything, so every edge says how sure it is:

| Resolution | Meaning |
|---|---|
| `exact` | Followed imports, re-exports, enclosing scopes, or `self`/`super()` through the class hierarchy |
| `receiver` | The object is known (e.g. the `request_started` signal), the method called on it is not |
| `heuristic` | The only symbol in the repo with that name |
| `ambiguous` | A few same-named candidates — one edge each |
| `external` | Lives outside the repo (stdlib, Werkzeug, …) |
| `unresolved` | Nothing static analysis can see (attributes of local variables, dynamic dispatch) |

Language support is a plugin (`languages/base.py`); Python is the only one in v1.

## Roadmap

| Release | Scope |
|---|---|
| v1.0 | Python codebases · agent loop · MCP server · React trace UI · ablation eval · Docker Compose · public demo |
| v1.1 | Helm chart · AWS (ECS Fargate + Bedrock) |
| v2.0 | Go, C#, TypeScript, Angular |
| v2.1 | Terraform, Kubernetes, GitHub Actions, Bash — and the links between them |

## Prior work

The loop builds on ideas from [Self-RAG](https://arxiv.org/abs/2310.11511), [Corrective RAG](https://arxiv.org/abs/2401.15884) and [Adaptive-RAG](https://arxiv.org/abs/2403.14403).

## License

MIT — see [LICENSE](LICENSE). Corpus licenses: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
