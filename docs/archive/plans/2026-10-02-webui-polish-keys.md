# Piano — JAG-113 WebUI polish + keys (TDD)

Spec: `docs/specs/2026-10-02-webui-polish-keys-design.md`. Test: `tests/v113_webui_polish.py`.

## Task 1 — Spec + piano
- [x].

## Task 2 — Test TDD (rossi)
- [ ] `tests/v113_webui_polish.py`: R1, R2, T1, K1.

## Task 3 — Server: sessioni / tool event / keys
- [ ] `_rel_time`, `list_sessions` (updated+age+ordine), `_trunc`, `_tool_event`.
- [ ] I due `tool.result` passano args+output.
- [ ] `keys_status()` + `GET /api/keys`.
- Verifica: R1, R2, T1, K1 verdi.

## Task 4 — WebUI: sessioni, tool card, picker, tab Keys
- [ ] age nella riga sessione; toolCard(args); picker custom; tab Keys.
- Verifica: browser.

## Task 5 — Verifica e2e + HANDOFF
- [ ] v113 + regressione; live; HANDOFF.
