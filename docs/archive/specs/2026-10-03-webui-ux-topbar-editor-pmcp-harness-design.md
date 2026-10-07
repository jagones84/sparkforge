# WebUI UX (inspector/topbar/palette/editor) + PMCP opzionale + categoria Harness — design (2026-10-03)

## Motivation (5 richieste utente)
1. Feed in fondo all'inspector; topbar piu' ordinata; bordo blu sul bottone ⚙.
2. `compact` deve stare nel **Context** (gia' fatto: `index.html:500`; lo screenshot era cache → Ctrl+F5).
3. La palette ⌘K elenca 176 skill: **non ha senso** → toglierle.
4. Editor: **tasto-destro** sull'albero file per **copiare il path**; **drag&drop** di un file dall'OS.
5. PMCP non deve essere "ovvio"/obbligatorio: la repo deve funzionare senza.
6. Settings: separare **Tools & policy** (policy dei tool) dai **parametri harness** (Runtime/Verifier/Best-of-N/Difficulty/Self-evolving) in una **nuova categoria**, ridisegnata seguendo l'HTML archify.

## D1 — Inspector & topbar
- Sposto `<section data-insp="feed">` in fondo (dopo `terminal`).
- `#settingsBtn`: bordo **blu** (`border-color: rgba(108,140,255,.55); color: var(--accent)`); spaziatura topbar piu' uniforme.
- Nessuna modifica a `compact` (gia' nel Context).

## D2 — Command palette (⌘K)
- `loadPaletteDynamic()`: **rimosso** il blocco `skills`. Restano **sessioni** (switch) + **MCP** (vai alle impostazioni) + le voci statiche.

## D3 — Editor
- **Menu contestuale** su `.ed-trow` (righe file): "copia path" (clipboard + fallback), "apri", "download". Chiude su click/Esc.
- **Drag&drop** su `#editorDock` (`dragover` preventDefault + `drop`): il browser NON espone il path OS, quindi:
  - immagine → anteprima in scheda **temporanea** (object URL);
  - altro → `FileReader.readAsText` → scheda **temporanea** `untitled` (read-only, non scritta su disco), con badge "file trascinato".
- Editor API: `openTemp(name, text)` / `openTempImage(name, url)`; le tab temporanee hanno `path = "untitled://<name>"` e non vengono persistite.

## D4 — PMCP opzionale
- `config/mcp_clients.yaml` (**tracciato**): resta solo `env_files` + **esempi commentati**. Nessun client attivo ⇒ un clone fresco funziona.
- `config/mcp_clients.local.json` (**gitignored**): il wiring reale del maintainer (`pmcp` + `python_sandbox`) in formato `mcpServers`. L'espansione `${PMCP_AUTH_TOKEN}` continua a funzionare (`os.path.expandvars`, `mcp_client:201`).
- `server.py` `SYSTEM_PROMPT`: il blocco "## MCP gateway (PMCP)" diventa **condizionale** (incluso solo se un client `pmcp` è configurato).
- Test `v07/v071/v072`: i check pmcp **skippano** se `pmcp` non è configurato (nessun FAIL per chi non lo usa).

## D5 — Settings: categoria Harness + restyle
- `SETTINGS_CATS` += `["harness", "Harness"]`.
- Nuovo `<div class="sw-cat" data-cat="harness">` con le 5 card (Runtime/Verifier/Best-of-N/Difficulty/Self-evolving).
- `data-cat="tools"` resta con la **policy dei tool** (`#configPanel` ← `/api/tools`), titolo "Tool policy".
- Restyle ispirato a `docs/diagrams/sparkforge-architecture.html`: card `background:var(--panel)`, `border:1px solid`, `border-radius:.75rem`, header con **dot colorato** per gruppo, sottotitolo, griglia; palette slate/emerald/violet/amber/rose/orange.

## Error handling
- Drag&drop non testuale/binario non-immagine → scheda "binary, no preview".
- Copia path: fallback `document.execCommand("copy")` se la clipboard API è bloccata.
- PMCP assente: nessun errore (già garantito da `start_all` try/except); prompt senza il blocco PMCP.

## Testing
- `tests/v158_webui_ux_and_pmcp.py`: statici (Feed ultimo; `#settingsBtn` blu; palette senza `skills`; `openTemp`/contextmenu; `SETTINGS_CATS` con `harness`; config tracciato senza client attivi; prompt condizionale) + live (⌘K senza "skill ▸"; `/api/tools` ok).
- Regressione: v07, v113, v129, v152, v156, v157.
