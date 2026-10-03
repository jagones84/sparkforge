# Plan — WebUI UX + PMCP opzionale + categoria Harness (2026-10-03)

Spec: `docs/specs/2026-10-03-webui-ux-topbar-editor-pmcp-harness-design.md`.

## T1 — Inspector & topbar
- `index.html`: spostare `<section data-insp="feed">` dopo `terminal`.
- CSS: `#settingsBtn { border-color: rgba(108,140,255,.55); color: var(--accent); }`.
- Verifica: browser (ordine sezioni, bordo blu).

## T2 — Palette senza skills
- `index.html loadPaletteDynamic`: rimuovere il blocco `/api/skills`.
- Verifica: ⌘K non mostra "skill ▸".

## T3 — Editor: context menu + drag&drop
- `editor.js`: menu contestuale sulle righe file (`copiare path`, `apri`, `download`); drop su `#editorDock`
  → `openTemp` / `openTempImage`; schede temporanee non persistite.
- Verifica: browser (click destro → copia path; drop di un file di testo).

## T4 — PMCP opzionale
- `config/mcp_clients.yaml`: solo `env_files` + esempi commentati (nessun client attivo).
- `config/mcp_clients.local.json`: pmcp + python_sandbox reali (gitignored).
- `server.py`: SYSTEM_PROMPT con blocco PMCP condizionale.
- `tests/v07_mcp_fsedit.py` (+ v071/v072 se applicabile): check pmcp → SKIP se assente.
- Verifica: `/api/mcp/clients` mostra ancora pmcp+python_sandbox (dal locale); un config vuoto non rompe.

## T5 — Settings: categoria Harness + restyle
- `SETTINGS_CATS` += `harness`; spostare le 5 card in `data-cat="harness"`; `tools` = policy (`#configPanel`).
- Restyle card con dot colorato + spacing (stile archify).
- Verifica: browser (2 categorie, aspetto).

## T6 — Test + chiusura
- `tests/v158_webui_ux_and_pmcp.py` (statici + live).
- Regressione: v07, v113, v129, v152, v156, v157.
- Commit + push; aggiornare `.agent/HANDOFF.md`.
