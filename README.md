# wall_ai

Design: [Understand component](docs/design/understand.md)

## Change log

| Date | PR ID | System Before | Task | System After | Status |
|---|---|---|---|---|---|
| 2026-10-22 | #1 | Empty repo with Apache-2.0 license | Add design for the Understand component | Design doc in `docs/design/understand.md` | Open |
| 2026-10-22 | #2 | Design doc only, no code | Scaffold the Python project with lint and test CI | uv project with ruff and pytest; CI runs both on every PR | Open |
| 2026-10-22 | #3 | Project scaffold with nothing to analyze | Add the shopfront sample target with ground truth | Two-service sample (FastAPI + Express) in `samples/shopfront` with `expected.json` | Open |
| 2026-10-22 | #4 | Sample target but no system model | Add the system model, unit tests first | `SystemModel` graph with evidence-tagged links; 8 unit tests | Open |
