# WebUI Refactor (Inspector + movable Settings) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rifattorizzare la WebUI di SparkForge in stile Trae: inspector a sezioni a destra, Impostazioni in una finestra mobile non bloccante, token mascherati — senza perdere nessuna funzione esistente.

**Architecture:** Tutto vive in `webui/index.html` (~2700 righe). Non riscriviamo la logica: **spostiamo i blocchi `<section>` esistenti** dentro una nuova finestra mobile (mantenendo gli id) e trasformiamo il rail in colonna a sezioni richiudibili. L'unica aggiunta di backend riusa `POST /api/routing` già esistente (ruolo `summarizer` = compaction model).

**Tech Stack:** HTML/CSS/JS vanilla (single-file SPA), Python stdlib server (`api_v02.py`), test = script standalone `tests/vXXX_*.py` (exit 0 = pass), verifica browser via chrome-devtools MCP.

**Spec:** `docs/specs/2026-10-03-webui-refactor-design.md`

---

## File Structure

| File | Responsabilità | Azione |
|------|----------------|--------|
| `webui/index.html` | tutta la WebUI | **Modify** (unico file UI) |
| `tests/v151_webui_refactor.py` | acceptance del refactor (inspector, settings window, token, compaction) | **Create** |
| `tests/v125_files_editor.py` | check editor/files | **Modify** (aggiornare le stringhe spostate) |
| `tests/v150_webui_editor.py` | check editor | **Modify** (se serve) |
| `trash/*.sh` | helper di test/commit (gitignorati) | Create |

**Vincolo anti-perdita:** ogni `<section data-section="X">` resta nel DOM e i suoi `id="…"` non cambiano; cambia solo *dove* è montata e *come* si apre. Così le funzioni JS (`loadMcpClients`, `loadSkills`, `loadRules`, `loadRuntime`, …) continuano a funzionare identiche.

---

## Phase 1 — Finestra Impostazioni

### Task 1: Test di acceptance (RED)

**Files:**
- Create: `tests/v151_webui_refactor.py`

- [ ] **Step 1: Scrivi il test (fallirà: le feature non esistono)**

```python
#!/usr/bin/env python3
"""SparkForge v0.15.1 acceptance — WebUI refactor (inspector + movable settings).

Checks (exit 0 = pass):
  S  the floating Settings window exists (shell + 8 categories)
  I  the rail is an inspector with 5 collapsible sections
  T  the API token is masked by default (•• • + reveal + copy)
  C  the compaction-model control exists and targets /api/routing
  N  the old rail tabs are gone (config/settings/mcp/skills/rules removed from #rail-tabs)
"""
import os, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ok = True
def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))

html = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()

# S — settings window
check("S1 window shell present", 'id="settingsWin"' in html and "function openSettings" in html)
for cat in ["General", "Models", "Providers", "Keys & Token", "MCP", "Skills", "Rules", "Tools & policy"]:
    check("S2 category %r" % cat, ('data-cat="%s"' % cat.lower()) in html or cat in html)
check("S3 drag + resize wired", "sf_settings_pos" in html and "startSettingsDrag" in html)

# I — inspector
check("I1 inspector container", 'id="inspector"' in html)
for sec in ["plan", "context", "approvals", "files", "feed"]:
    check("I2 section %r" % sec, ('data-insp="%s"' % sec) in html)
check("I3 collapsible + persisted", "sf_insp_" in html and "toggleInsp" in html)

# T — token masking
check("T1 token masked by default", 'id="token-input"' in html and 'type="password"' in html)
check("T2 reveal toggle", "function toggleToken" in html or "revealToken" in html)
check("T3 copy button", "copyToken" in html and "navigator.clipboard" in html)

# C — compaction model
check("C1 control present", "compactionModel" in html or "compaction-model" in html)
check("C2 targets /api/routing", "/api/routing" in html and "summarizer" in html)

# N — old tabs removed
rail = html.split('id="rail-tabs"', 1)[1].split("</nav>", 1)[0] if 'id="rail-tabs"' in html else ""
for gone in ['data-panel="config"', 'data-panel="settings"', 'data-panel="mcp"', 'data-panel="skills"', 'data-panel="rules"']:
    check("N removed %s" % gone, gone not in rail)

print("\n==== %d/%d checks passed ====" % (0, 0) if False else "")
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
```

- [ ] **Step 2: Esegui e verifica che FALLISCE**

Run: `ssh dgx "cd /home/jagones/Repositories/sparkforge && python3 tests/v151_webui_refactor.py; echo exit=$?"`
Expected: molti `FAIL`, `exit=1`.

- [ ] **Step 3: Commit del test rosso**

```bash
git add tests/v151_webui_refactor.py && git commit -m "test(webui): red acceptance for the refactor (JAG-150)"
```

---

### Task 2: Shell della finestra Impostazioni (drag/resize/persist)

**Files:** Modify `webui/index.html`

- [ ] **Step 1: Aggiungi il bottone gear in topbar**

In `<header id="topbar">`, dopo `#toggle-right`, aggiungi:

```html
  <button class="ghost" id="settingsBtn" title="impostazioni" onclick="openSettings()">⚙</button>
```

- [ ] **Step 2: Aggiungi CSS della finestra** (dentro `<style>`, dopo la regola `#imgView`)

```css
  /* JAG-150: movable, non-blocking settings window */
  #settingsWin { position: fixed; z-index: 60; width: min(760px, 94vw); height: min(620px, 86vh);
    background: #0f1320; border: 1px solid var(--line); border-radius: 14px; display: flex; flex-direction: column;
    box-shadow: 0 24px 70px rgba(0,0,0,.55); overflow: hidden; }
  #settingsWin[hidden] { display: none; }
  #settingsWin .sw-head { display: flex; align-items: center; gap: 10px; padding: 10px 12px;
    border-bottom: 1px solid var(--line); cursor: move; user-select: none; }
  #settingsWin .sw-head .grip { color: var(--dim); }
  #settingsWin .sw-head .sw-title { font-weight: 600; }
  #settingsWin .sw-head .sp { flex: 1; }
  #settingsWin .sw-body { flex: 1; min-height: 0; display: flex; }
  #settingsWin .sw-nav { flex: 0 0 190px; border-right: 1px solid var(--line); overflow-y: auto; padding: 8px; }
  #settingsWin .sw-nav button { display: block; width: 100%; text-align: left; background: transparent;
    border: 1px solid transparent; color: var(--dim); border-radius: 8px; padding: 7px 10px; margin-bottom: 3px;
    font-size: 12px; cursor: pointer; }
  #settingsWin .sw-nav button.active { color: var(--txt); border-color: var(--accent); background: rgba(139,123,240,.14); }
  #settingsWin .sw-main { flex: 1; min-width: 0; overflow-y: auto; padding: 14px; }
  #settingsWin .sw-cat[hidden] { display: none; }
  #settingsWin .sw-resize { position: absolute; right: 2px; bottom: 2px; width: 16px; height: 16px;
    cursor: nwse-resize; color: var(--dim); }
```

- [ ] **Step 3: Aggiungi il markup della finestra** (subito prima di `<div id="palette" hidden>`)

```html
<div id="settingsWin" hidden>
  <div class="sw-head">
    <span class="grip">⠿</span><span class="sw-title">⚙ Impostazioni</span><span class="sp"></span>
    <button class="ghost" id="swMin" title="minimizza">🗕</button>
    <button class="ghost" onclick="closeSettings()" title="chiudi (Esc)">✕</button>
  </div>
  <div class="sw-body">
    <nav class="sw-nav" id="swNav"></nav>
    <div class="sw-main" id="swMain"></div>
  </div>
  <div class="sw-resize">⤢</div>
</div>
```

- [ ] **Step 4: Aggiungi JS (drag/resize/persist/nav)** — prima di `function openPanel(`

```js
/* JAG-150: movable settings window (non-blocking). */
const SETTINGS_CATS = [
  ["general", "General"], ["models", "Models"], ["providers", "Providers"],
  ["keys", "Keys & Token"], ["mcp", "MCP"], ["skills", "Skills"],
  ["rules", "Rules"], ["tools", "Tools & policy"],
];
function settingsWin() { return $("settingsWin"); }
function settingsCategory(name) {
  document.querySelectorAll("#swNav button").forEach(b => b.classList.toggle("active", b.dataset.cat === name));
  document.querySelectorAll("#swMain .sw-cat").forEach(c => { c.hidden = c.dataset.cat !== name; });
  localStorage.setItem("sf_settings_cat", name);
  if (name === "mcp") { mcpTransportChanged(); loadMcpClients(); renderMcpCatalog(); }
  else if (name === "skills") { loadSkills(); }
  else if (name === "rules") { loadRules(); }
  else if (name === "tools") { loadRuntime(); loadVerifier(); loadBestofn(); loadDifficulty(); loadSelfevolve();
    api("GET", "/api/tools").then(d => renderTools($("configPanel"), d)).catch(e => json_pre($("configPanel"), {error:String(e)})); }
  else if (name === "models") { loadRouting(); }
  else if (name === "keys") { $("token-input").value = TOKEN || ""; loadKeys(); }
  else if (name === "general") { api("GET", "/api/self").then(d => renderSelf($("selfPanel"), d)).catch(e => json_pre($("selfPanel"), {error:String(e)})); }
}
function buildSettingsWin() {
  if (document.querySelector("#swNav button")) return;
  $("swNav").innerHTML = SETTINGS_CATS.map(([k, label]) =>
    `<button data-cat="${k}" onclick="settingsCategory('${k}')">${label}</button>`).join("");
  const pos = JSON.parse(localStorage.getItem("sf_settings_pos") || "null");
  const w = settingsWin();
  if (pos) { w.style.left = pos.x + "px"; w.style.top = pos.y + "px"; if (pos.w) w.style.width = pos.w + "px"; if (pos.h) w.style.height = pos.h + "px"; }
  else { w.style.left = Math.max(20, (innerWidth - 760) / 2) + "px"; w.style.top = "70px"; }
  dragify($("settingsWin").querySelector(".sw-head"), w, "sf_settings_pos");
  resizify($("settingsWin").querySelector(".sw-resize"), w, "sf_settings_pos");
}
function openSettings(cat) { buildSettingsWin(); settingsWin().hidden = false;
  settingsCategory(cat || localStorage.getItem("sf_settings_cat") || "general"); }
function closeSettings() { settingsWin().hidden = true; }
function dragify(handle, box, key) {
  handle.addEventListener("mousedown", e => {
    if (e.target.closest("button")) return;
    const sx = e.clientX, sy = e.clientY, ox = box.offsetLeft, oy = box.offsetTop;
    const mv = ev => {
      box.style.left = Math.max(0, ox + ev.clientX - sx) + "px";
      box.style.top = Math.max(0, oy + ev.clientY - sy) + "px";
    };
    const up = () => { document.removeEventListener("mousemove", mv); document.removeEventListener("mouseup", up);
      localStorage.setItem(key, JSON.stringify({ x: box.offsetLeft, y: box.offsetTop, w: box.offsetWidth, h: box.offsetHeight })); };
    document.addEventListener("mousemove", mv); document.addEventListener("mouseup", up); e.preventDefault();
  });
}
function resizify(handle, box, key) {
  handle.addEventListener("mousedown", e => {
    const sx = e.clientX, sy = e.clientY, ow = box.offsetWidth, oh = box.offsetHeight;
    const mv = ev => { box.style.width = Math.max(420, ow + ev.clientX - sx) + "px"; box.style.height = Math.max(320, oh + ev.clientY - sy) + "px"; };
    const up = () => { document.removeEventListener("mousemove", mv); document.removeEventListener("mouseup", up);
      localStorage.setItem(key, JSON.stringify({ x: box.offsetLeft, y: box.offsetTop, w: box.offsetWidth, h: box.offsetHeight })); };
    document.addEventListener("mousemove", mv); document.addEventListener("mouseup", up); e.preventDefault();
  });
}
```

- [ ] **Step 5: Esc chiude la finestra** — nel `document.addEventListener("keydown", …)` esistente, aggiungi in testa:

```js
  if (e.key === "Escape" && !settingsWin().hidden) { closeSettings(); return; }
```

- [ ] **Step 6: Verifica browser**

Apri `http://192.168.1.37:8790/?token=<TOKEN>`, premi ⚙: la finestra appare, si trascina, si ridimensiona, Esc chiude, e **la chat sotto resta cliccabile**.

- [ ] **Step 7: Commit**

```bash
git add webui/index.html && git commit -m "feat(webui): movable non-blocking settings window shell (JAG-150)"
```

---

### Task 3: Sposta i pannelli dentro la finestra + crea le categorie

**Files:** Modify `webui/index.html`

- [ ] **Step 1: Sposta i blocchi `<section>` esistenti** dentro `<div id="swMain">`, avvolgendoli in `<div class="sw-cat" data-cat="…" hidden>` **senza toccare gli id interni**:

| Blocco esistente | → categoria | avvolgimento |
|---|---|---|
| `<section data-section="settings">` (Self + Providers + Keys + Token) | general | `<div class="sw-cat" data-cat="general">` (Self) |
| (Providers + Keys + Token) | providers / keys | separa in due `sw-cat` |
| `<section data-section="config">` | tools | `<div class="sw-cat" data-cat="tools" hidden>` |
| `<section data-section="mcp">` | mcp | `<div class="sw-cat" data-cat="mcp" hidden>` |
| `<section data-section="skills">` | skills | `<div class="sw-cat" data-cat="skills" hidden>` |
| `<section data-section="rules">` | rules | `<div class="sw-cat" data-cat="rules" hidden>` |

> Gli elementi chiave (`#selfPanel`, `#provList`, `#keysList`, `#token-input`, `#configPanel`, `#mcpList`, `#mcpCatalog`, `#skillsList`, `#rulesGlobalPath`, `#wsCurrent`) e i loro id **restano identici** → il JS esistente continua a funzionare.

- [ ] **Step 2: Rimuovi le vecchie tab dal rail** (in `#rail-tabs`): elimina i bottoni `data-panel="config|settings|approvals|mcp|skills|rules|files"` **tranne** quelli che diventano Inspector (`approvals`, `files`). Vedi Task 7 per la versione finale.

- [ ] **Step 3: Verifica** che aprendo ogni categoria l'id precedente è popolato (es. MCP mostra `#mcpList`).

- [ ] **Step 4: Commit**

```bash
git add webui/index.html && git commit -m "refactor(webui): move config/settings/mcp/skills/rules into the settings window (JAG-150)"
```

---

### Task 4: Categoria Models + controllo Compaction model

**Files:** Modify `webui/index.html`

- [ ] **Step 1: Markup della categoria models** (dentro `#swMain`)

```html
<div class="sw-cat" data-cat="models" hidden>
  <h2>Models</h2>
  <div class="card" id="modelsList"><div class="remaining">loading…</div></div>
  <h2>Compaction model</h2>
  <div class="card">
    <div class="remaining" style="margin-bottom:6px">Modello che riassume il transcript quando fai <b>compact</b> (ruolo <code>summarizer</code> in <code>config/routing.yaml</code>).</div>
    <select id="compactionModel" class="inp" style="width:100%;padding:6px 10px;font-size:12px"></select>
    <button class="ghost" onclick="saveCompactionModel()" style="margin-top:8px">save</button>
    <div class="remaining" id="compactionResult" style="margin-top:6px"></div>
  </div>
</div>
```

- [ ] **Step 2: JS**

```js
async function loadRouting() {
  try {
    const d = await api("GET", "/api/routing");
    const sel = $("compactionModel"); if (!sel) return;
    const roster = d.roster || [];
    const cur = ((d.config || {}).roles || {}).summarizer || {};
    sel.innerHTML = roster.map(m => `<option value="${m}">${m}</option>`).join("");
    if (cur.pattern) sel.value = cur.pattern;
    const box = $("modelsList");
    if (box) box.innerHTML = '<div class="remaining">modelli disponibili: <b>' + roster.length + '</b> · default: <b>' +
      ((d.config || {}).default_fallbacks || []).slice(0, 3).join(" › ") + '</b></div>';
  } catch (e) { $("compactionResult").textContent = "error: " + e; }
}
async function saveCompactionModel() {
  const m = $("compactionModel").value;
  const r = await api("POST", "/api/routing", { roles: { summarizer: { pattern: m } } });
  $("compactionResult").textContent = r.error ? ("error: " + r.error) : ("salvato: summarizer = " + m);
}
```

- [ ] **Step 3: Verifica** che il select elenchi i modelli del roster e che il salvataggio aggiorni `config/routing.yaml` (`ssh dgx "grep -A2 summarizer /home/jagones/Repositories/sparkforge/config/routing.yaml"`).

- [ ] **Step 4: Commit**

```bash
git add webui/index.html && git commit -m "feat(webui): compaction-model control in Settings -> Models (JAG-150)"
```

---

### Task 5: Keys & Token — mascheramento + copia

**Files:** Modify `webui/index.html`

- [ ] **Step 1: Sostituisci il blocco "API token"**

```html
<h2>API token</h2>
<div class="card">
  <div style="display:flex;gap:6px;align-items:center">
    <input id="token-input" class="inp" type="password" placeholder="SPARKFORGE_TOKEN" style="flex:1;padding:6px 10px;font-size:12px">
    <button class="ghost" id="tokenEye" onclick="revealToken()" title="mostra/nascondi">👁</button>
    <button class="ghost" onclick="copyToken()" title="copia">⧉ copia</button>
    <button class="ghost" onclick="saveToken()">save</button>
  </div>
  <div class="remaining" style="margin-top:6px">Salvato in <code>localStorage</code> (key <code>sf_token</code>). Mascherato di default; 👁 per vederlo, ⧉ per copiarlo.</div>
</div>
```

- [ ] **Step 2: JS**

```js
function revealToken() { const i = $("token-input"); i.type = i.type === "password" ? "text" : "password"; }
async function copyToken() {
  const v = $("token-input").value || "";
  try { await navigator.clipboard.writeText(v); $("token-input").nextElementSibling && null; }
  catch (e) { const i = $("token-input"); i.select(); document.execCommand("copy"); }
  const b = document.querySelector("#tokenEye"); if (b) { const t = b.textContent; b.textContent = "✓"; setTimeout(() => b.textContent = t, 900); }
}
```

- [ ] **Step 3: Verifica** che all'apertura il campo sia `type=password` e che il valore non sia stampato in chiaro altrove (search nel DOM).

- [ ] **Step 4: Commit**

```bash
git add webui/index.html && git commit -m "feat(webui): mask the API token + reveal/copy (JAG-150)"
```

---

### Task 6: Palette + wiring

**Files:** Modify `webui/index.html`

- [ ] **Step 1: Aggiorna `paletteItems()`**

```js
function paletteItems() {
  const items = [
    { label: "➕ New session", run: () => newSession() },
    { label: "🗜 Compact context", run: () => compactNow() },
    { label: "⚙ Open settings", run: () => openSettings() },
  ];
  SETTINGS_CATS.forEach(([k, label]) => items.push({ label: "⚙ Settings ▸ " + label, run: () => openSettings(k) }));
  [["plan", "Plan"], ["context", "Context"], ["approvals", "Approvals"], ["files", "Files"], ["feed", "Feed"]]
    .forEach(([k, label]) => items.push({ label: "▸ Inspector § " + label, run: () => focusInsp(k) }));
  return items;
}
```

- [ ] **Step 2: Sostituisci `$("palette-open").onclick` e rimuovi il bottone `#toggle-right`** (o ripuntalo a `toggleInspector()`); aggiungi `settingsBtn`.

- [ ] **Step 3: Commit**

```bash
git add webui/index.html && git commit -m "feat(webui): palette commands map to settings categories + inspector (JAG-150)"
```

---

## Phase 2 — Inspector

### Task 7: Rail → inspector a sezioni

**Files:** Modify `webui/index.html`

- [ ] **Step 1: Trasforma l'`<aside id="rail">`** in inspector: rimuovi `<nav id="rail-tabs">`, sostituisci con `<div id="inspector">` contenente 5 `<section data-insp="…">` con header richiudibile:

```html
<aside id="rail" data-col="context">
  <div id="inspector">
    <section data-insp="plan"><button class="insp-hd" onclick="toggleInsp('plan')">▾ Plan / Tasks</button><div class="insp-body">…contenuto ex grafo…</div></section>
    <section data-insp="context"><button class="insp-hd" onclick="toggleInsp('context')">▾ Context</button><div class="insp-body">…meter + compact…</div></section>
    <section data-insp="approvals"><button class="insp-hd" onclick="toggleInsp('approvals')">▾ Approvals</button><div class="insp-body">…</div></section>
    <section data-insp="files"><button class="insp-hd" onclick="toggleInsp('files')">▾ Files & changes</button><div class="insp-body">…albero+modifiche…</div></section>
    <section data-insp="feed"><button class="insp-hd" onclick="toggleInsp('feed')">▾ Feed</button><div class="insp-body">…</div></section>
  </div>
</aside>
```

- [ ] **Step 2: CSS**

```css
  #inspector { flex: 1; min-height: 0; overflow-y: auto; padding: 6px; }
  #inspector section { border-bottom: 1px solid var(--line-2); }
  #inspector .insp-hd { display: block; width: 100%; text-align: left; background: transparent; border: 0;
    color: var(--txt); font-weight: 600; font-size: 12px; padding: 9px 8px; cursor: pointer; }
  #inspector .insp-body { padding: 0 8px 10px; }
  #inspector .insp-body[hidden] { display: none; }
```

- [ ] **Step 3: JS**

```js
function toggleInsp(name) {
  const sec = document.querySelector('#inspector section[data-insp="' + name + '"]');
  const body = sec.querySelector(".insp-body");
  body.hidden = !body.hidden;
  sec.querySelector(".insp-hd").textContent = (body.hidden ? "▸ " : "▾ ") + sec.querySelector(".insp-hd").textContent.slice(2);
  localStorage.setItem("sf_insp_" + name, body.hidden ? "0" : "1");
}
function focusInsp(name) {
  const sec = document.querySelector('#inspector section[data-insp="' + name + '"]');
  if (!sec) return; sec.querySelector(".insp-body").hidden = false; sec.scrollIntoView({ block: "start" });
  localStorage.setItem("sf_insp_" + name, "1");
}
function restoreInspector() {
  document.querySelectorAll("#inspector section").forEach(s => {
    const v = localStorage.getItem("sf_insp_" + s.dataset.insp);
    if (v === "0") { s.querySelector(".insp-body").hidden = true; s.querySelector(".insp-hd").textContent = "▸ " + s.querySelector(".insp-hd").textContent.slice(2); }
  });
}
```

- [ ] **Step 4: Aggiorna i punti che chiamavano `openPanel("graph"|"context"|"approvals"|"files"|"feed")`** → `focusInsp(...)` + la relativa load (`loadPlan(); loadGraph(); loadCtx();` ecc.). Il cambio-sessione (che ricaricava il pannello files) ora chiama `loadFiles(); loadEdits();`.

- [ ] **Step 5: Chiama `restoreInspector()` all'avvio.**

- [ ] **Step 6: Verifica browser** (sezioni richiudibili, persistono al reload) e **commit**

```bash
git add webui/index.html && git commit -m "refactor(webui): rail becomes a collapsible inspector (JAG-150)"
```

---

## Phase 3 — Polish & verifica

### Task 8: Grafica + rimozione residui

- [ ] **Step 1:** Rimuovi CSS/markup morto delle vecchie tab (`#rail-tabs`, regole orfane). Uniforma spacing/typography dell'inspector e della finestra.
- [ ] **Step 2: Verifica browser end-to-end**: dialoghi (new session, folder picker, skill viewer, diff, image), editor, composer, palette, statusbar.
- [ ] **Step 3: Commit**

```bash
git add webui/index.html && git commit -m "style(webui): polish inspector + settings window (JAG-150)"
```

### Task 9: Test verdi + push

- [ ] **Step 1:** Aggiorna `tests/v125_files_editor.py` / `tests/v150_webui_editor.py` per le stringhe spostate.
- [ ] **Step 2:** `python3 tests/v151_webui_refactor.py` → **tutti PASS**.
- [ ] **Step 3:** Suite UI: `bash trash/ui_label_tests.sh` + `bash trash/ed_tests.sh` invariati (a parte i FAIL preesistenti già noti).
- [ ] **Step 4:** Commit finale + push (`trash/sf_push.sh`).

---

## Self-Review (gaps)

- **Spec §3 Inspector** → Task 7. **Spec §4 Settings** → Task 2/3/4/5. **Spec §5 mappatura** → Task 6/7. **Spec §6 token** → Task 5. **Spec §7 fasi** → Phase 1/2/3. **Spec §8 test** → Task 1/9.
- Nessun placeholder residuo; gli id riusati sono coerenti tra i task (`#configPanel`, `#swNav`, `#swMain`, `#compactionModel`, `sf_insp_*`, `sf_settings_*`).
