# 2026-10-03 — WebUI Editor Dock (design)

**Status:** proposta — attende review utente
**Ambito:** `sparkforge` WebUI (`webui/index.html` + `server.py`)
**Autore:** agente (da richiesta utente)

## 1. Problema

L'editor attuale è un `<textarea>` (`min-height: 280px`) dentro la rail sinistra,
tab **Files** ([webui/index.html](../../webui/index.html) L580-599). Nessun colore,
nessuna tab multi-file, nessuna vista markdown/immagini/diagrammi.
Non è adatto a "coding + view". Il backend esiste già
(`/api/fs/list|read|write`, `webui/index.html` L2216-2320).

## 2. Goal

Un **dock editor a destra**, apribile/chiudibile e **ridimensionabile**, con **una
tab per file**, editor vero (**CodeMirror 6**), colori per linguaggio, e **vista per
tipo** (codice / markdown render / immagini / HTML-dashboard). Tutto **offline**
(vendorizzato, niente CDN).

## 3. Non-goal

- Porting all'app Android (SparkPulse): resta separata.
- Editing collaborativo / multiutente.
- Terminale, git UI, LSP.
- Fase 2 (markdown/diagrammi) non è in Fase 1.

## 4. Decisioni approvate

| Tema | Scelta |
|---|---|
| Forma | **Dock a destra** (resize drag, persiste larghezza), overlay su mobile |
| Stack editor | **CodeMirror 6** vendorizzato |
| Consegna | **2 fasi** (Fase 1 sotto, Fase 2 sotto) |
| Rete | **Offline** — nessuna CDN |

## 5. Vincolo e deviazione dalla convenzione

Oggi il progetto è "**no build step, un solo `index.html`**" e `server.py` serve
solo `/` e `/index.html`. CM6 (ESM) richiede un bundle, quindi servono:

1. un **bundle vendorizzato** `webui/assets/vendor/codemirror.js` (build
   *una-tantum* con `esbuild`; procedure in `webui/assets/README.md`);
2. una **rotta statica read-only** `GET /assets/<path>` in `server.py`, ancorata a
   `webui/assets/`, con whitelist di estensioni e protezione anti path-traversal.

È una **deviazione consapevole** da "no build", giustificata da un editor reale.
*Alternativa scartata:* inline del bundle dentro `index.html` (file ~2 MB, illeggibile).

## 6. Architettura

- **Server:** nuova rotta `GET /assets/<path>` (sola lettura, sandbox). Nessun'altra
  modifica al server.
- **Client:** il codice dell'editor vive in `webui/editor.js` (ES module), servito
  dalla nuova rotta; `index.html` resta snello (aggiunge solo il dock + il loader).
- **Unità piccole e testabili:**
  - `Dock` — open/close, resize (drag), persistenza larghezza (`localStorage`), modal su mobile.
  - `Tabs` — file aperti, tab attiva, badge "modified", chiusura con conferma se dirty.
  - `EditorHost` — wrapper CM6: `create/setValue/getValue/setLanguage/destroy`, tema scuro.
  - `ViewerRegistry` — mappa `ext`/`mime` → viewer: `code` · `markdown` · `image` · `html-iframe` · `binary`.
  - `fsClient` — thin wrapper su `/api/fs/list|read|write` + riuso del journal diff/undo esistente.
  - `sanitize` — sanitizzazione markdown/HTML (DOMPurify vendorizzato o subset sicuro).
- **Data flow:** click su file → `fsClient.read` → `ViewerRegistry.pick` → render;
  edit → dirty per tab; **save** → `/api/fs/write`; i file toccati dai tool restano
  nel journal diff/undo già presente.

## 7. Fase 1 — scope implementativo immediato

Dock a destra + resize + persistenza + **tab per file** + **CM6** (numeri di riga,
indentazione, bracket-match, ricerca) + **immagini** + save/revert + badge dirty +
overlay mobile. Riusa `/api/fs/*`.

**Deliverable:** aprire più file in tab, editarli e salvarli, con colori — dentro la WebUI.

## 8. Fase 2 — dopo

Markdown render con toggle *code ↔ render*; anteprima **HTML/diagrammi in `<iframe sandbox>`**
(es. artefatti archify); JSON/YAML colorati; (eventuale) mermaid; CSV come tabella.

## 9. Sicurezza

- Ogni contenuto renderizzato passa da `sanitize` (niente `innerHTML` da sorgente non sanitizzata).
- `iframe` con `sandbox` **senza** `allow-same-origin`.
- Rotta `/assets` con whitelist estensioni + risoluzione del path ancorata alla root.
- *(Fuori scope editor, ma correlato)* l'input del **token** in Settings va mascherato
  (`type=password`) e non persistito in chiaro.

## 10. Verifica

- `tests/v150_webui_editor.py` — acceptance strutturale (convenzione repo: helper `check()`,
  report JSON, exit 0 = ok): esiste la rotta `/assets`, esiste `webui/editor.js`, marker
  `#editorDock` / tab / CM6, uso degli endpoint `/api/fs/*`.
- Manuale con chrome-devtools MCP: apri file, tab, save, markdown render, screenshot,
  containment (`scrollWidth <= innerWidth`).

## 11. Rischi

- **Peso bundle CM6** (mitigazione: 1 bundle, caricato lazy al primo open).
- **Nuovo build step** (documentato; non richiesto a runtime).
- **Sicurezza rotta statica** (whitelist + root fissa + anti-traversal).

## 12. Prossimi passi

1. **Review di questa spec** (utente).
2. Commit della spec.
3. `writing-plans` → piano di implementazione **Fase 1**.
