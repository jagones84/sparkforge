# WebUI Editor Dock — Implementation Plan (Fase 1)

**Goal:** sostituire il `<textarea>` della tab *Files* con un **dock editor a destra** (tab per file, CodeMirror 6, immagini, markdown render) dentro la WebUI di sparkforge.

**Architecture:** la logica editor vive in `webui/editor.js` (ES module) servito da una nuova rotta statica `GET /assets/<path>` di `server.py`. Il bundle CodeMirror 6 è vendorizzato (build una-tantum con esbuild). `index.html` aggiunge solo il markup del dock + il loader. Endpoint dati: riuso di `/api/fs/list|read|write`.

**Tech:** Python stdlib (server), JS ESM (client), CodeMirror 6 (vendored), `marked` + `DOMPurify` (vendored) per il render markdown/HTML.

**Spec:** `docs/specs/2026-10-03-webui-editor-design.md`

---

## File structure

| File | Responsabilità |
|---|---|
| `server.py` | + rotta `GET /assets/<path>` (read-only, whitelist, anti-traversal) |
| `webui/assets/vendor/codemirror.js` | bundle CM6 (generato, committato) |
| `webui/assets/vendor/marked.min.js` | render markdown (vendorizzato) |
| `webui/assets/vendor/purify.min.js` | sanitizzazione HTML (vendorizzato) |
| `webui/assets/vendor/codemirror.css` | stile base CM + tema (o tema via theme-one-dark) |
| `webui/editor.js` | Dock, Tabs, EditorHost(CM6), ViewerRegistry, fsClient, sanitize |
| `webui/index.html` | markup `#editorDock` + loader + wiring (Files tab, Rules) |
| `tests/v150_webui_editor.py` | acceptance strutturale |

## Task

### Task 1 — Rotta statica `/assets`
- Modify `server.py` (in `do_GET`, prima del fallback `/`): serve file sotto `WEBUI_DIR/assets/` con whitelist estensioni (`.js .css .map .json .svg .png .jpg .jpeg .webp .woff2`) e path risolto dentro la root (rifiuta `..`).
- Expected: `curl -s localhost:8790/assets/vendor/…` → 200; `curl .../assets/../../etc/passwd` → 404.

### Task 2 — Build bundle vendor
- Script `webui/assets/build-vendor.sh` (o `scripts/`): `npm i` CM6 + marked + dompurify + esbuild in `/tmp`, bundle → `webui/assets/vendor/codemirror.js`, download `marked.min.js`/`purify.min.js`.
- Commit degli artefatti.

### Task 3 — `webui/editor.js`
- `fsClient`: `read(path)`, `write(path,text)`, `list(path)`.
- `ViewerRegistry`: `pick(path)` → `code|markdown|image|html-iframe|binary`; estensioni mappa.
- `EditorHost`: wrapper CM6 (`create(parent,{doc,lang})`, `setValue`, `getValue`, `setLanguage`, `destroy`), tema `oneDark`.
- `Tabs`: lista `[{path, lang, viewer, dirty, doc}]`, `open(path)`, `activate(i)`, `close(i,{force})`.
- `Dock`: `open(path?)`, `close()`, `toggle()`, width drag (persist `sf_ed_w`), overlay <1024px.
- `renderMarkdown(text)` = `DOMPurify.sanitize(marked.parse(text))`.

### Task 4 — `index.html` wiring
- Markup `#editorDock` (`hidden`) con: header (titolo, ✕), tab-strip, body (viewer host).
- Loader `<script type="module" src="/assets/editor.js">` con `window.SparkEditor` API.
- Tab *Files*: click su file → `SparkEditor.open(path)` (invece del textarea). Mantieni il journal Changes/diff.
- **Item 4:** spostare send/steer/agent/stop **sopra** la textarea della chat.

### Task 5 — Item 1: Rules → editor
- Nel pannello Rules, ogni regola ha un bottone "apri nell'editor" → `SparkEditor.open(path)` (render markdown con headings).

### Task 6 — Test
- `tests/v150_webui_editor.py`: check rotta `/assets`, esistenza `webui/editor.js` + `vendor/codemirror.js`, marker `#editorDock`, assenza del vecchio `#fileText` (o sua deprecazione). Report JSON, exit 0.
- Manuale: chrome-devtools MCP (apri file, tab, save, markdown, screenshot).

## Verifica finale
- `python3 tests/v150_webui_editor.py` → exit 0.
- Suite esistente sparkforge invariata.
- Screenshot browser: dock con tab, markdown renderizzato, immagini.
