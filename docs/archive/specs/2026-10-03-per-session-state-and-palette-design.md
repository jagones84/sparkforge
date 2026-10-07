# Per-session state + command palette — design (2026-10-03)

## Motivation (richiesta utente)
1. La **command palette** (⌘K) deve essere scrollabile, navigabile da tastiera e
   **auto-aggiornata** con sessioni/skill/server MCP (non solo voci hardcoded).
2. L'**editor** deve essere **già aperto** nel workspace della sessione.
3. Tutto e' **per sessione**: workspace/editor, todo/plan e **modello LLM**;
   cambiando sessione la UI si adatta e ognuno ricorda il proprio stato.

## Stato attuale (verificato)
- Palette: item da `paletteItems()` (3 azioni + 8 `Settings` da `SETTINGS_CATS` + 7
  `Inspector`), lista **non scrollabile**, **nessuna** navigazione da tastiera, non
  include sessioni/skill/MCP.
- Workspace: **per sessione** (`sess["workspace"]`), ricaricato allo switch.
- Todo/plan: **per sessione** lato backend (`data/graphs/<id>.json`) ma la UI **non**
  ricarica il pannello Plan allo switch.
- Modello: **globale** (`localStorage sf_model` + `routing.yaml`). Nessun `sess["model"]`.
- Editor: dock `#editorDock` (editor.js) chiuso di default; albero radicato nel
  workspace della sessione via `/api/fs/list?session=`; i tab sono globali (`sf_ed_tabs`).

## D1 — Command palette (⌘K)
- CSS: `#palette-results { max-height:56vh; overflow:auto }`.
- Tastiera: ↑/↓ spostano l'evidenziazione, ↵ esegue (riuso del pattern `_modelHi`/`paintModelHi`
  di `modelMenu`), filtro substring invariato.
- Contenuto **auto-aggiornato ad ogni apertura**: voci attuali + dinamiche:
  - **sessioni** ← `GET /api/sessions` → `selectSession(id)`
  - **skill** ← `GET /api/skills` → `openSettings("skills")`
  - **MCP** ← `GET /api/mcp/clients` → `openSettings("mcp")`
  - Le fetch sono **best-effort** (try/catch, mai bloccanti): le voci statiche appaiono
    subito, le dinamiche si aggiungono quando arrivano.
- Non e' un riepilogo impostazioni: resta un launcher.

## D2 — Stato per sessione
### Modello (strada A: backend = fonte di verita')
- Campo `sess["model"]` persistito in `data/sessions/<id>.json`.
- `list_sessions()` espone `"model": s.get("model")`.
- Nuova route `POST /api/sessions/<id>/model {model}` → salva e risponde
  `{"ok":true,"session":id,"model":...}`.
- Backend: i chat handler risolvono il modello come `param_model or sess.get("model")`
  (una sessione senza modello esplicito usa il proprio modello; fallback al default).
- Frontend: cache `_sessModel` da `/api/sessions`; `currentModel()` =
  `_sessModel[sessionId] || localStorage.sf_model`; `chooseModel()` scrive **entrambi**
  (sessione + default globale) e fa `POST /api/sessions/<id>/model`; allo switch →
  `modelLabel()`.

### Todo/plan
- Allo switch (e dopo new/delete) chiamare `loadPlan()` → il pannello mostra subito i
  todo della sessione attiva.

### Editor
- Nuovo `SparkEditor.ensureOpen()`: apre il dock se non e' stato chiuso a mano.
- Flag `sf_dock_open` (default `true`): `close()`→`false`, `toggle()`→invertito.
- A load e ad ogni switch sessione → `ensureOpen()`.
- Tab **per sessione**: chiave `sf_ed_tabs_<sid>` (+ fallback legacy `sf_ed_tabs`);
  `SparkEditor.onSessionChange()` ricarica i tab della nuova sessione.

## Error handling
- Palette: fetch fallite → item dinamici assenti, nessun errore visibile.
- Modello: POST fallita → la scelta resta in cache locale (degrada, non rompe).
- Editor: `sf_session` assente → radice = default globale (comportamento attuale).

## Testing
- `tests/v156_per_session_and_palette.py`: check statici (CSS scroll, `_palHi`,
  `ensureOpen`, `_sessModel`, `sess["model"]` in list_sessions, route model) + live
  (`POST /api/sessions/<id>/model` round-trip) se il server e' raggiungibile.
- Regressione: v080/v120/v125/v129/v150/v151 (WebUI) invariate.
