# Piano — sessione legata a una cartella (JAG-115)

Riferimento: `docs/specs/2026-10-02-session-workspace-design.md`

- [ ] T1. Spec + piano + test `tests/v115_session_workspace.py` (TDD, prima rosso).
- [ ] T2. `rules.py`: `resolve_workspace`, `check_dir`; `ws=` su `collect/rules_block/status/save`.
- [ ] T3. `server.py`: `rules_context(sess/ws)`, `_system_prompt(sess)`, `agent_run/agent_stream_gen(workspace=)`,
        endpoint `/api/agent/run` legge `?session=`, `list_sessions` espone `workspace`.
- [ ] T4. `api_v02.py`: `rules_status/rules_save/workspace_get/workspace_set` con `session`.
- [ ] T5. WebUI tab Rules: workspace di sessione + "default per nuove sessioni" + 📁 in lista sessioni.
- [ ] T6. Verifica: `tests/v115` + regressioni; live API (8791) + browser; commit; HANDOFF.

## Verifica
- `python3 tests/v115_session_workspace.py` → tutti PASS.
- Regressione: v114, v113, v112, v111, v110, v107.
- LIVE: `POST /api/workspace {session,path}` → sessione linkata; `GET /api/rules?session=` → regole giuste.
