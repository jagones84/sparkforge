# Piano — JAG-114 rules globali/progetto + workspace (TDD)

Spec: `docs/specs/2026-10-02-rules-workspace-design.md`. Test: `tests/v114_rules_workspace.py`.

## Task 1 — Spec + piano
- [x].

## Task 2 — Test TDD (rossi)
- [ ] `tests/v114_rules_workspace.py`: R1..R7, A1.

## Task 3 — `rules.py` (motore)
- [ ] path globali/progetto, `get/set_workspace`, `collect`, `rules_block`, `save`, `status`.
- Verifica: R1..R7 verdi.

## Task 4 — Server + API
- [ ] `RULES_POLICY` + blocco in `_system_prompt` e `agent_run`.
- [ ] `/api/rules`, `/api/workspace` (+ helper api_v02).
- Verifica: A1 + py_compile.

## Task 5 — WebUI tab Rules
- [ ] workspace + editor globali/progetto + lista file.
- Verifica: browser.

## Task 6 — Verifica e2e + HANDOFF
- [ ] v114 + regressione; live; HANDOFF.
