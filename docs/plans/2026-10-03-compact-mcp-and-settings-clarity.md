# Plan — compact nel Context · settings chiari · MCP stile Trae (2026-10-03)

Spec: `docs/specs/2026-10-03-compact-mcp-and-settings-clarity-design.md`.

## Task 1 — D1: compact nel Context
- `webui/index.html`: rimuovere `#compactBtn` dalla topbar (L406) e inserirlo nella sezione
  `data-insp="context"` (dopo il card, dentro `insp-body`). Id invariato.
- Verifica: `compactNow()`/`$("compactBtn").onclick` invariati; test v157 + browser.

## Task 2 — D2: settings Tools & policy chiari
- `webui/index.html`: per ognuna delle 5 card aggiungere una frase `.remaining` e `title` sugli input/label,
  con etichette in chiaro. Nessun id modificato.
- Verifica: v113 (settings) verde; browser (tooltip presenti).

## Task 3 — D3 backend: local mcp.json (mcpServers)
- `mcp_client.py`:
  - `_load_local_doc()` traduce `mcpServers`→`clients` (e legge il legacy `.local.yaml`);
  - `_save_local_doc(doc)` scrive `config/mcp_clients.local.json` in formato `mcpServers`;
  - `status()` espone `path` del file locale.
- Verifica: `python3 -m py_compile`; live: POST /api/mcp/clients → file con `mcpServers`.

## Task 4 — D3 UI: editor + snippet, via il form
- Rimuovere il card "Add manually" (form).
- Aggiungere "✎ Edit mcp.json" (apre il file nell'editor) accanto a "⧉ MCP JSON".
- Catalogo: `＋ add` installa; preset con token → apre il modale snippet precompilato.
- Lista: `✎` apre il file nell'editor; `🗑` rimuove.
- Verifica: browser (apertura file, snippet append), v108/v152 verdi.

## Task 5 — Test + chiusura
- `tests/v157_compact_mcp_clarity.py` (statici + live).
- Regressione: v108, v113, v129, v152.
- Commit + push; aggiornare `.agent/HANDOFF.md`.
