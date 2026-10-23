# wall_ai

Design: [Understand component](docs/design/understand.md)

## Install

Needs Python 3.11+, [uv](https://docs.astral.sh/uv/), Node.js, and these tools, which wall_ai runs as separate programs:

```bash
uv tool install semgrep
```

```bash
npm install --global @cyclonedx/cdxgen@12
```

To run targets (`--run`) on macOS, also install [Lima](https://lima-vm.io/). wall_ai creates its sandbox VM on first use.

```bash
brew install lima
```

## Use

```bash
uv run wall-ai understand samples/shopfront --run
```

Without `--run`, wall-ai only reads the code. With it, wall-ai also runs the target's Python components in the sandbox and compares what ran with what the code says. Raw run output is kept in `~/.wall_ai/runs/`.

## Change log

| Date | PR ID | System Before | Task | System After | Status |
|---|---|---|---|---|---|
| 2026-10-22 | #1 | Empty repo with Apache-2.0 license | Add design for the Understand component | Design doc in `docs/design/understand.md` | Merged |
| 2026-10-22 | #2 | Design doc only, no code | Build a first version of the Understand component and check it against a sample | Python project with lint and test CI; `SystemModel` graph with evidence-tagged links; static pipeline (`wall-ai understand`) using cdxgen, tree-sitter and Semgrep; functional tests match the shopfront sample's ground truth | Merged |
| 2026-10-23 | #6 | Static pipeline only | Add the runtime pipeline for Python | `wall-ai understand --run` runs the target in an isolated sandbox (Lima, or the CI runner), mocks outbound calls, records spans and call pairs, and compares observed with static links; functional test checks a real run of the shopfront sample | Merged |
| 2026-10-23 | #7 | Change log listed merged PR #6 as Open | Mark #6 as merged | Change log matches GitHub | Merged |
| 2026-10-23 | #8 | On a real codebase, wall_ai crashed, gave wrong route paths and the wrong app, flagged 214 of 289 functions as unused, and found no services | Fix static accuracy on real code | On the FastAPI full-stack template: 1 of 64 backend functions flagged unused (correct), full `/api/v1` paths, the right app, Postgres/SMTP/Sentry found, every frontend client method linked to its endpoint | Merged |
| 2026-10-23 | #9 | The tree-sitter pin gave no reason | Link the upstream issues behind the pin | `pyproject.toml` explains the 0.26.0 crash and when to lift the pin | Open |
