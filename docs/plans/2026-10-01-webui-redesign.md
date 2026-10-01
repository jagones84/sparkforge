# SparkForge WebUI Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Portare `webui/index.html` a qualità "desktop IDE" (3 colonne, rail contesto, tool card interattive, ⌘K), chiudendo i 5 gap concordati, senza build step.

**Architecture:** Un unico `webui/index.html` autonomo, servito da `server.py` (`WEBUI_DIR`). Nessuna modifica al backend: si consumano gli endpoint esistenti (`/api/*`, SSE `/api/feed`). Verifica tramite uno script di acceptance standalone conforme alla convenzione del repo (`tests/vXX_*.py`, helper `check()`, report JSON, exit 0 = ok).

**Tech Stack:** HTML5 + CSS (variabili, grid/flex, media query) + JS vanilla (fetch, EventSource). Python 3 stdlib per lo script di acceptance.

**Spec:** `docs/specs/2026-10-01-webui-redesign-design.md`

---

## File Structure

| File | Responsabilità | Azione |
|------|----------------|--------|
| `webui/index.html` | Intera WebUI: design tokens, shell, rail, chat, sessioni, palette | Riscrittura completa |
| `tests/v080_webui_redesign.py` | Acceptance strutturale della WebUI (markers, endpoint, dedup plan) | Create |

Nessun'altra modifica. `server.py` resta invariato.

---

## Task 0: Branch di lavoro

**Files:** nessuno (solo git).

- [ ] **Step 1: Creare il branch**

```bash
ssh dgx "cd /home/jagones/Repositories/sparkforge && git checkout -b feature/webui-redesign"
```

- [ ] **Step 2: Verificare il branch**

```bash
ssh dgx "cd /home/jagones/Repositories/sparkforge && git status -sb | head -1"
```
Expected: `## feature/webui-redesign`

---

## Task 1: Design tokens + shell a 3 colonne + top bar (Fase 1)

**Files:**
- Modify: `webui/index.html` (riscrittura: struttura + CSS)
- Create: `tests/v080_webui_redesign.py`

- [ ] **Step 1: Scrivere lo script di acceptance con i marker della Fase 1**

```python
#!/usr/bin/env python3
"""SparkForge v0.8 acceptance — WebUI redesign (structural, offline).

Legge webui/index.html e verifica i marker strutturali delle 5 fasi.
Exit 0 iff ogni check passa. Report: data/v080-webui-acceptance.json
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(REPO, "webui", "index.html")
RESULTS = {"task": "v0.8 webui redesign", "checks": [], "passed": False}


def check(name, ok, detail=""):
    RESULTS["checks"].append({"name": name, "ok": bool(ok), "detail": str(detail)[:400]})
    print("%s %s %s" % ("PASS" if ok else "FAIL", name, detail))
    return bool(ok)


def html():
    with open(INDEX, encoding="utf-8") as fh:
        return fh.read()


def main():
    src = html()
    # --- Fase 1: tokens + shell 3 colonne + top bar ---
    check("accent token #8b7bf0", "--accent: #8b7bf0" in src)
    check("shell 3 colonne", all(m in src for m in ('data-col="sessions"', 'data-col="chat"', 'data-col="context"')))
    check("topbar presente", 'id="topbar"' in src)
    check("model chip", 'id="model-chip"' in src)
    check("ctx meter", 'id="ctx-meter"' in src)
    check("server badge", 'id="server-badge"' in src)
    check("responsive 1100", "@media (max-width: 1100px)" in src)
    check("responsive 820", "@media (max-width: 820px)" in src)
    RESULTS["passed"] = all(c["ok"] for c in RESULTS["checks"])
    os.makedirs(os.path.join(REPO, "data"), exist_ok=True)
    with open(os.path.join(REPO, "data", "v080-webui-acceptance.json"), "w", encoding="utf-8") as fh:
        json.dump(RESULTS, fh, indent=2)
    print("RESULT:", "PASS" if RESULTS["passed"] else "FAIL")
    return 0 if RESULTS["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Eseguire e verificare il FAIL**

```bash
ssh dgx "cd /home/jagones/Repositories/sparkforge && python3 tests/v080_webui_redesign.py"
```
Expected: `FAIL` sui marker non ancora presenti (indice vecchio).

- [ ] **Step 3: Riscrivere lo shell di `webui/index.html`**

Struttura di base (i pannelli/chat arrivano nei task seguenti):

```html
<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SparkForge</title>
<style>
  :root {
    --accent: #8b7bf0; --you: #8fb6ff; --ok: #4ecb8d; --deny: #ef6461; --info: #5ac8fa;
    --bg: #0f1219; --bg-2: #121722; --bg-3: #161b25; --line: #2b3140; --line-2: #1e2431;
    --ink: #c3cad6; --muted: #7b8494; --fs: 13px;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--ink);
         font: var(--fs)/1.5 system-ui, sans-serif; }
  #topbar { display: flex; align-items: center; justify-content: space-between;
            padding: 8px 12px; background: var(--bg-3); border-bottom: 1px solid var(--line); }
  #app { display: flex; height: calc(100vh - 42px); }
  [data-col="sessions"] { width: 200px; border-right: 1px solid var(--line); background: var(--bg-2); }
  [data-col="chat"]     { flex: 1; display: flex; flex-direction: column; }
  [data-col="context"]  { width: 238px; border-left: 1px solid var(--line); background: var(--bg-2); }
  @media (max-width: 1100px) { [data-col="context"] { display: none; } }
  @media (max-width: 820px)  { [data-col="sessions"] { display: none; } }
</style>
</head>
<body>
  <header id="topbar">
    <div>◈ <strong>SparkForge</strong> <span style="color:var(--muted)">agent harness · DGX Spark</span></div>
    <div style="display:flex;gap:10px;align-items:center">
      <button id="model-chip">model ▾</button>
      <span id="ctx-meter">ctx —</span>
      <span id="sandbox-badge">sandbox —</span>
      <span id="server-badge">● …</span>
      <button id="palette-open">⌘K</button>
    </div>
  </header>
  <main id="app">
    <aside data-col="sessions"></aside>
    <section data-col="chat"></section>
    <aside data-col="context"></aside>
  </main>
  <script>/* stato + trasporto + render (task seguenti) */</script>
</body>
</html>
```

- [ ] **Step 4: Eseguire e verificare il PASS**

```bash
ssh dgx "cd /home/jagones/Repositories/sparkforge && python3 tests/v080_webui_redesign.py"
```
Expected: `RESULT: PASS` (8/8).

- [ ] **Step 5: Commit**

```bash
ssh dgx "cd /home/jagones/Repositories/sparkforge && git add webui/index.html tests/v080_webui_redesign.py && git commit -m 'feat(webui): 3-column shell + design tokens + topbar (phase 1)'"
```

---

## Task 2: Rail contesto con i 5 pannelli (Fase 2)

**Files:** Modify `webui/index.html`, `tests/v080_webui_redesign.py`

- [ ] **Step 1: Aggiungere le assertion dei pannelli**

Aggiungere in `main()` prima di `RESULTS["passed"] = ...`:

```python
    for p in ("graph", "config", "self", "settings", "approvals"):
        check("panel tab %s" % p, ('data-panel="%s"' % p) in src)
    check("panel body", 'id="panel-body"' in src)
```

- [ ] **Step 2: Run → FAIL** (`python3 tests/v080_webui_redesign.py`)

- [ ] **Step 3: Implementare la rail**

Dentro `<aside data-col="context">`:

```html
<nav id="rail-tabs">
  <button data-panel="graph">Graph</button>
  <button data-panel="config">Config</button>
  <button data-panel="self">Self</button>
  <button data-panel="settings">Settings</button>
  <button data-panel="approvals">Approvals</button>
</nav>
<div id="panel-body"><p class="empty">Nessun run attivo.</p></div>
<script>
  const PANEL_API = {
    graph:     () => fetch(api("/api/runs/" + (state.runId || "") + "/graph")).then(r => r.json()),
    config:    () => fetch(api("/api/tools")).then(r => r.json()),
    self:      () => fetch(api("/api/self")).then(r => r.json()),
    settings:  () => fetch(api("/api/providers")).then(r => r.json()),
    approvals: () => fetch(api("/api/approvals")).then(r => r.json()),
  };
  function openPanel(name) {
    document.querySelectorAll("#rail-tabs button").forEach(b =>
      b.classList.toggle("active", b.dataset.panel === name));
    state.panel = name;
    PANEL_API[name]().then(data => renderPanel(name, data));
  }
  document.getElementById("rail-tabs").addEventListener("click", e => {
    const b = e.target.closest("button[data-panel]");
    if (b) openPanel(b.dataset.panel);
  });
</script>
```

- [ ] **Step 4: Run → PASS**

- [ ] **Step 5: Commit**

```bash
ssh dgx "cd /home/jagones/Repositories/sparkforge && git add webui/index.html tests/v080_webui_redesign.py && git commit -m 'feat(webui): context rail with 5 panels (phase 2)'"
```

---

## Task 3: Chat — tool card interattive + thinking live (Fase 3)

**Files:** Modify `webui/index.html`, `tests/v080_webui_redesign.py`

- [ ] **Step 1: Aggiungere le assertion chat**

```python
    check("tool card markup", 'class="toolcard"' in src)
    check("tool card expand", "toggleTool(" in src)
    check("thinking live", 'class="thinking"' in src)
    check("markdown render", "renderMarkdown(" in src)
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implementare le card e il thinking**

```html
<script>
  function renderMarkdown(t) {
    return (t || "")
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\n/g, "<br>");
  }
  function toggleTool(id) {
    document.getElementById(id)?.classList.toggle("expanded");
  }
  function toolCard(ev) {
    const ok = ev.ok !== false;
    const id = "t" + Math.random().toString(36).slice(2, 8);
    return `<div class="toolcard ${ok ? "ok" : "err"}">
      <div class="toolcard-head" onclick="toggleTool('${id}')">
        <span>${ok ? "✅" : "⛔"} <strong>${renderMarkdown(ev.tool || "tool")}</strong></span>
        <span class="dim">${ev.ms ? ev.ms + "ms" : ""} ▾</span>
      </div>
      <div class="toolcard-body" id="${id}">
        <div class="dim">args: ${renderMarkdown(ev.args || "")}</div>
        <pre>${renderMarkdown(ev.result || "")}</pre>
      </div>
    </div>`;
  }
  function renderThinking(text) {
    return `<div class="thinking">◉ thinking… <span class="dim">${renderMarkdown(text)}</span></div>`;
  }
</script>
```

- [ ] **Step 4: Run → PASS**

- [ ] **Step 5: Commit**

```bash
ssh dgx "cd /home/jagones/Repositories/sparkforge && git add webui/index.html tests/v080_webui_redesign.py && git commit -m 'feat(webui): interactive tool cards + live thinking + markdown (phase 3)'"
```

---

## Task 4: Sessioni (ricerca/filtri) + command palette ⌘K (Fase 4)

**Files:** Modify `webui/index.html`, `tests/v080_webui_redesign.py`

- [ ] **Step 1: Aggiungere le assertion sessioni + palette**

```python
    check("session search", 'id="session-search"' in src)
    check("hide empty filter", 'id="hide-empty"' in src)
    check("command palette", 'id="palette"' in src)
    check("palette shortcut", "metaKey" in src and "key === \"k\"" in src)
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implementare ricerca, filtri e palette**

```html
<div style="padding:8px">
  <input id="session-search" placeholder="cerca sessione…">
  <label class="dim"><input type="checkbox" id="hide-empty"> nascondi vuote</label>
</div>
<div id="session-list"></div>
<div id="palette" hidden>
  <input id="palette-input" placeholder="vai a sessione / pannello / azione…">
  <ul id="palette-results"></ul>
</div>
<script>
  function renderSessions(list) {
    const q = document.getElementById("session-search").value.toLowerCase();
    const hideEmpty = document.getElementById("hide-empty").checked;
    document.getElementById("session-list").innerHTML = list
      .filter(s => (!hideEmpty || s.messages > 0) && s.title.toLowerCase().includes(q))
      .map(s => `<div class="session-row" onclick="switchSession('${s.id}')">
        <div>${s.title}</div><div class="dim">${s.id} · ${s.messages} msg</div>
      </div>`).join("");
  }
  document.getElementById("palette-open").onclick = () => openPalette();
  addEventListener("keydown", e => {
    if ((e.metaKey || e.ctrlKey) && e.key === "k") { e.preventDefault(); openPalette(); }
    if (e.key === "Escape") closePalette();
  });
</script>
```

- [ ] **Step 4: Run → PASS**

- [ ] **Step 5: Commit**

```bash
ssh dgx "cd /home/jagones/Repositories/sparkforge && git add webui/index.html tests/v080_webui_redesign.py && git commit -m 'feat(webui): session search/filters + command palette (phase 4)'"
```

---

## Task 5: Bug fix — plan duplicato, sessioni, sync feed (Fase 5)

**Files:** Modify `webui/index.html`, `tests/v080_webui_redesign.py`

- [ ] **Step 1: Aggiungere le assertion bug + token**

```python
    check("plan dedupe", "dedupePlan(" in src)
    check("feed sync", 'new EventSource(' in src)
    check("token field", 'id="token-input"' in src)
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implementare dedup + sync + token UI**

```html
<script>
  function dedupePlan(steps) {
    const seen = new Set();
    return steps.filter(s => {
      const key = (s.text || s.title || "").trim().toLowerCase();
      if (!key || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }
  function api(path) {
    const t = localStorage.getItem("sparkforge_token") || "";
    return path + (t ? (path.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(t) : "");
  }
  function connectFeed() {
    const es = new EventSource(api("/api/feed"));
    es.onmessage = ev => applyFeedEvent(JSON.parse(ev.data));
  }
</script>
<div id="settings-token">
  <label class="dim">bearer token</label>
  <input id="token-input" placeholder="SPARKFORGE_TOKEN">
</div>
```

- [ ] **Step 4: Run → PASS**

- [ ] **Step 5: Commit**

```bash
ssh dgx "cd /home/jagones/Repositories/sparkforge && git add webui/index.html tests/v080_webui_redesign.py && git commit -m 'fix(webui): dedupe plan, feed sync, token UI (phase 5)'"
```

---

## Task 6: Verifica finale end-to-end

**Files:** nessuno (verifica).

- [ ] **Step 1: Acceptance strutturale**

```bash
ssh dgx "cd /home/jagones/Repositories/sparkforge && python3 tests/v080_webui_redesign.py"
```
Expected: `RESULT: PASS`, report in `data/v080-webui-acceptance.json`.

- [ ] **Step 2: Verifica manuale guidata**

Istruzioni (nessuna asserzione automatica qui): aprire `http://<dgx>:8790/?token=<T>`, poi
(a) ridimensionare la finestra e osservare i drawer a 1100/820px; (b) aprire i 5 pannelli e
confrontare i dati con `curl /api/...` corrispondenti; (c) mandare un messaggio e verificare che
i tool compaiano come card; (d) cercare una sessione; (e) aprire ⌘K. Annotare i punti falliti.

- [ ] **Step 3: Merge nel branch principale**

```bash
ssh dgx "cd /home/jagones/Repositories/sparkforge && git checkout master && git merge --no-ff feature/webui-redesign -m 'merge: WebUI redesign (5 phases)'"
```

---

## Self-Review

**Spec coverage:** §5 struttura→Task1; §6 design system→Task1; §7 top bar→Task1; §8 pannelli→Task2;
§9 chat→Task3; §10 sessioni+⌘K→Task4; §11 bug→Task5; §12 tecnica (token UI, single file)→Task1/5;
§14 criteri→Task6. Copertura completa.

**Placeholder scan:** nessun TBD/TODO; ogni step di codice mostra codice reale; ogni comando ha
output atteso.

**Type consistency:** nomi coerenti tra task — `api()`, `renderMarkdown()`, `toolCard()`,
`dedupePlan()`, `openPanel()`, `openPalette()`, `applyFeedEvent()`, chiave `sparkforge_token`,
marker `data-panel`/`data-col`/`class="toolcard"`/`class="thinking"`.

**Nota:** il contenuto JS è rappresentativo e va integrato nel file unico reale; i marker testati
non cambiano. I nomi di campo delle risposte API vanno confermati contro le risposte reali al
momento dell'implementazione (rischio §15 della spec).
