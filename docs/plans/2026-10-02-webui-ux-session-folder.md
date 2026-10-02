# Piano — rifiniture UX WebUI + cartella di sessione (JAG-116/117)

Spec: `docs/specs/2026-10-02-webui-ux-session-folder-design.md`

- [x] #1 `.model-btn` leggibile (WebUI CSS).
- [x] #2 `_apply_chat_todos` / `_apply_chat_todo_updates`: args + output (server).
- [x] #4 `_stick` + `_nearBottom` + `#jumpBtn` (WebUI).
- [x] #5 `ensure_session_workspace`, `backfill_session_workspaces`, dialog nuova sessione;
      fix `rules.check_dir("")`.
- [x] Test `tests/v116_webui_fixes.py` (9/9), `tests/v117_session_folder.py` (8/8);
      v115 aggiornato; regressione v107→v117 verde.
- [x] Verifica live browser (modello leggibile, dialog, 10/10 sessioni con 📁).

## Deferred
- #3 coda/steer delle richieste → spec dedicata (JAG-119).
