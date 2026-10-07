# Piano — JAG-112 provider/LLM aggiungibili + form (TDD)

Spec: `docs/specs/2026-10-02-providers-crud-design.md`
Esecuzione inline, un commit per task. Test: `tests/v112_providers_crud.py`.

## Task 1 — Spec + piano
- [x] spec + piano.

## Task 2 — Test TDD (devono fallire)
- [ ] `tests/v112_providers_crud.py`: P1..P8.
- Verifica: falliscono (attributi/funzioni assenti).

## Task 3 — Engine: overlay + merge + CRUD + validazione
- [ ] `providers.LOCAL_CONFIG`, `_read_yaml`, `_merge`, `_write_local`, `_valid_*`.
- [ ] `load()` merge; `upsert_provider/remove_provider/add_model/remove_model/set_default/reload`.
- Verifica: P1..P7 verdi.

## Task 4 — API helper + route
- [ ] `api_v02.provider_*` + branch POST/DELETE `/api/providers*`.
- Verifica: P8 verde; `py_compile`.

## Task 5 — WebUI tab Providers
- [ ] lista + form + set default + delete (DOM API).
- Verifica: browser.

## Task 6 — Verifica e2e + HANDOFF
- [ ] v112 + regressione; live HTTP upsert/remove; HANDOFF.
