# wall_ai

Design: [Understand component](docs/design/understand.md)

## Change log

| Date | PR ID | System Before | Task | System After | Status |
|---|---|---|---|---|---|
| 2026-10-22 | #1 | Empty repo with Apache-2.0 license | Add design for the Understand component | Design doc in `docs/design/understand.md` | Merged |
| 2026-10-22 | #2 | Design doc only, no code | Build a first version of the Understand component and check it against a sample | Python project with lint and test CI; `SystemModel` graph with evidence-tagged links; static pipeline (`wall-ai understand`) using cdxgen, tree-sitter and Semgrep; functional tests match the shopfront sample's ground truth | Open |
