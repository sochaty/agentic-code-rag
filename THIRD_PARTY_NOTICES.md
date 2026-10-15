# Third-party notices

This repository's own code is MIT-licensed (see `LICENSE`).

Corpora are **not** vendored into this repository; they are cloned at a pinned tag by
`acr corpus fetch`. Artifacts derived from them — the prebuilt index published as a
GitHub release asset, and code excerpts quoted in `eval/questions.jsonl` — contain
portions of those projects and remain under their original licenses:

| Corpus | Upstream | License |
|---|---|---|
| Flask 3.1.3 | https://github.com/pallets/flask | BSD-3-Clause, Copyright 2010 Pallets |

The full upstream license text ships inside each prebuilt index archive.
