# Plan — Per-session state + command palette (2026-10-03)

Spec: `docs/specs/2026-10-03-per-session-state-and-palette-design.md`.

## Task 1 — Backend: modello per sessione
- `server.py:list_sessions()` → aggiungere `"model": s.get("model")`.
- `server.py` POST: nuova route `POST /api/sessions/<id>/model {model}` (dopo il body
  parse, accanto alle route `/api/sessions`). Valida `sid` (no `/`, no `..`), 404 se assente.
- `server.py` chat (`/api/chat` ~L3549, `/api/chat/stream` ~L3453): modello =
  `param or sess.get("model")`.
- Verifica: `python3 -m py_compile server.py`; test live POST + rilettura.

## Task 2 — Frontend: per-sessione (modello + plan)
- `_sessModel = {}` popolata in `loadSessions()` da `s.model`.
- `currentModel()` = `_sessModel[sessionId] || localStorage.sf_model || ""`.
- `loadModels()`: usa `currentModel()`; scrive `sf_model` solo se nessun modello di sessione.
- `chooseModel(ref)`: set `sf_model` + `_sessModel[sessionId]` + POST `/api/sessions/<id>/model`.
- Refactor: estrarre `selectSession(s)` dal click handler; usarla anche dalla palette.
- Allo switch (selectSession, createNewSession, delete): `modelLabel()`, `loadPlan()`.
- Verifica: browser — cambiare modello in una sessione, passare a un'altra e tornare.

## Task 3 — Editor: default aperto + tab per sessione
- `editor.js`: `LS_TABS` → `tabsKey()` = `sf_ed_tabs_<sid>` (fallback `sf_ed_tabs`).
- `ensureOpen()`, `onSessionChange()`; flag `sf_dock_open` in `close()`/`toggle()`.
- `window.SparkEditor.ensureOpen/onSessionChange`; chiamate da `index.html` all'init e allo switch.
- Verifica: browser — editor aperto al load sul workspace; switch sessione → albero/tab cambiano.

## Task 4 — Command palette
- CSS `#palette-results{max-height:56vh;overflow:auto}` + evidenziazione `.hl`.
- `renderPalette` con `_palAll`/`_palHi` + `paintPalHi()`; keydown su `#palette-input`
  (↑/↓/↵/esc).
- `openPalette()`: render statico subito, poi `loadPaletteDynamic()` (sessioni/skill/MCP).
- Item: `session:<id>`→selectSession, `skill:<name>`→openSettings("skills"),
  `mcp:<name>`→openSettings("mcp").
- Verifica: browser — ⌘K, scroll, frecce/Enter, presenza sessioni/skill/MCP.

## Task 5 — Test + chiusura
- `tests/v156_per_session_and_palette.py` (statici + live).
- Regressione WebUI: v080/v120/v125/v129/v150/v151.
- Commit + push; aggiornare `.agent/HANDOFF.md`.
