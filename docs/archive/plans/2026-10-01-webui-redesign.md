# SparkForge WebUI Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Portare `webui/index.html` a qualità "desktop IDE" (3 colonne, rail contesto, tool card interattive, ⌘K), chiudendo i 5 gap concordati, senza build step e **senza regressioni**.

**Architecture:** **Refactor incrementale** di un unico `webui/index.html` autonomo, servito da `server.py` (`WEBUI_DIR`). La logica JS esistente (token, SSE, tool card, graph, approvals, sessions, ctx, agent) **viene preservata**; cambiano CSS e struttura DOM, si aggiungono pannelli/palette in modo additivo. Verifica con script di acceptance standalone conforme alla convenzione del repo (`tests/vXX_*.py`, helper `check()`, report JSON, exit 0 = ok).

**Tech Stack:** HTML5 + CSS (variabili, grid/flex, media query) + JS vanilla (fetch, EventSource). Python 3 stdlib per l'acceptance.

**Spec:** `docs/specs/2026-10-01-webui-redesign-design.md`

---

## Critical Review (finding in fase di esecuzione)

Il file **non è vuoto**: 732 righe, con logica già funzionante. Una "riscrittura completa" romperebbe
feature in produzione. Vincoli obbligatori:

**Funzioni JS da PRESERVARE (non rinominare, non duplicare):**
`api(method, path, body)`, `authQS()`, `authHeaders()`, `ensureToken()`, `send()`, `runAgent()`,
`loadSessions()`, `newSession()`, `loadHistory()`, `loadPlan()`, `genPlan()`, `loadCtx()`,
`compactNow()`, `loadStatus()`, `loadApprovals()`, `decide()`, `loadGraph()`, `applyGraphEvent()`,
`renderGraph()`, `showNodeDetail()`, `graphNodeAction()`, `addTask()`, `replanGraph()`,
`connectFeed()`, `toolCard()`, `updateToolCard()`, `ensureThink()`, `ensureAnswer()`, `cotFeed()`,
`endStream()`, `openTab()`, `closeAside()`, `splitThinkTail()`.

**ID/elementi DOM da PRESERVARE:** `log`, `inp`, `agentBtn`, `sessions`, `sessInp`, `planGoal`,
`planSteps`, `planInp`, `tasks`, `taskInp`, `taskCount`, `graphHead`, `taskDetail`, `remaining`,
`ctxPill`, `ctxBar`, `ctxTok`, `ctxMsgs`, `ctxBudget`, `compactBtn`, `modelPill`, `sbxPill`,
`srvPill`, `feedDot`, `approvals`, `apprCount`, `feed`, `cotDrawer`, `aside`, `backdrop`.

**Token già gestito** (`localStorage["sf_token"]`, `ensureToken`, `authQS`): il task "token in UI"
diventa **migliorare** il prompt, non introdurre un nuovo sistema.

**Regola d'oro:** ogni task è **additivo o ristrutturante**; nessun task deve cancellare una funzione
o un ID non esplicitamente sostituito, e se lo sostituisce deve riskrivere il chiamante nello stesso commit.

---

## File Structure

| File | Responsabilità | Azione |
|------|----------------|--------|
| `webui/index.html` | WebUI completa: tokens, shell 3 colonne, rail pannelli, chat, sessioni, palette | Refactor incrementale (preserva JS/ID) |
| `tests/v080_webui_redesign.py` | Acceptance strutturale (markers, endpoint, dedup plan) | Create |

`server.py` resta invariato.

---

## Task 0: Branch di lavoro

- [ ] **Step 1: Creare il branch**

```bash
ssh dgx "cd /home/jagones/Repositories/sparkforge && git checkout -b feature/webui-redesign"
```

- [ ] **Step 2: Verificare**

```bash
ssh dgx "cd /home/jagones/Repositories/sparkforge && git status -sb | head -1"
```
Expected: `## feature/webui-redesign`

- [ ] **Step 3: Fotografare il baseline (per il confronto anti-regressione)**

```bash
ssh dgx "cd /home/jagones/Repositories/sparkforge && grep -cE 'function ' webui/index.html"
```
Expected: `~32` (annotare il numero; non deve scendere a fine lavoro).

---

## Task 1: Design tokens + shell a 3 colonne + top bar (Fase 1)

**Files:** Modify `webui/index.html`; Create `tests/v080_webui_redesign.py`

- [ ] **Step 1: Scrivere l'acceptance con i marker di Fase 1**

```python
#!/usr/bin/env python3
"""SparkForge v0.8 acceptance — WebUI redesign (structural, offline).

Legge webui/index.html e verifica marker strutturali + assenza di regressioni.
Exit 0 iff ogni check passa. Report: data/v080-webui-acceptance.json
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(REPO, "webui", "index.html")
RESULTS = {"task": "v0.8 webui redesign", "checks": [], "passed": False}

PRESERVED_FUNCS = [
    "api(", "authQS(", "ensureToken(", "send(", "runAgent(", "loadSessions(", "loadHistory(",
    "loadPlan(", "loadCtx(", "loadStatus(", "loadApprovals(", "loadGraph(", "connectFeed(",
    "toolCard(", "openTab(",
]
PRESERVED_IDS = [
    "log", "inp", "sessions", "planSteps", "tasks", "ctxBar", "approvals", "feed", "cotDrawer",
]


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
    # --- Anti-regressione: logica esistente preservata ---
    for fn in PRESERVED_FUNCS:
        check("kept func %s" % fn, fn in src)
    for eid in PRESERVED_IDS:
        check("kept id %s" % eid, ('id="%s"' % eid) in src)
    RESULTS["passed"] = all(c["ok"] for c in RESULTS["checks"])
    os.makedirs(os.path.join(REPO, "data"), exist_ok=True)
    with open(os.path.join(REPO, "data", "v080-webui-acceptance.json"), "w", encoding="utf-8") as fh:
        json.dump(RESULTS, fh, indent=2)
    print("RESULT:", "PASS" if RESULTS["passed"] else "FAIL")
    return 0 if RESULTS["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run → FAIL atteso solo sui marker di Fase 1** (i "kept *" devono già passare)

```bash
ssh dgx "cd /home/jagones/Repositories/sparkforge && python3 tests/v080_webui_redesign.py"
```
Expected: `FAIL` sui marker `--accent`, `data-col`, `topbar`, `model-chip`, `ctx-meter`, `server-badge`, `@media`; i check `kept *` già `PASS`.

- [ ] **Step 3: Applicare i design tokens in cima al `<style>` esistente**

Aggiungere dentro `:root` (o creare `:root` con queste variabili), **senza rimuovere** le regole esistenti:

```css
:root {
  --accent: #8b7bf0; --you: #8fb6ff; --ok: #4ecb8d; --deny: #ef6461; --info: #5ac8fa;
  --bg: #0f1219; --bg-2: #121722; --bg-3: #161b25; --line: #2b3140; --line-2: #1e2431;
  --ink: #c3cad6; --muted: #7b8494;
}
```

- [ ] **Step 4: Ristrutturare `<body>` in shell a 3 colonne riusando le sezioni esistenti**

Obiettivo: `header#topbar` con i pill esistenti (`ctxPill`→`ctx-meter`, `modelPill`→`model-chip`,
`srvPill`→`server-badge`, mantenendo gli ID originali come classi/alias) e `<main id="app">`
con `data-col="sessions" | "chat" | "context"`. Le sezioni `aside#aside` esistenti vanno
**spostate** dentro `data-col="context"` (non ricreate), il `#chat` esistente dentro `data-col="chat"`,
e l'elenco sessioni dentro `data-col="sessions"`.

```html
<header id="topbar">
  <span class="logo">⚡ SPARKFORGE</span>
  <span class="sub">agent harness · dgx spark · local router</span>
  <span style="flex:1"></span>
  <span class="pill" id="ctxPill">ctx: …</span>
  <button class="ghost" id="compactBtn">🗜 compact</button>
  <span class="pill" id="modelPill">model: …</span>
  <span class="pill" id="sbxPill">sandbox: …</span>
  <span class="pill" id="srvPill">server</span>
  <span class="feed-dot off" id="feedDot"></span>
  <button class="ghost" id="palette-open" title="command palette">⌘K</button>
</header>
<main id="app">
  <aside data-col="sessions"><!-- #sessions + #sessInp esistenti --></aside>
  <section data-col="chat"><!-- #chat esistente: #log, #cotDrawer, #composer, #tabbar --></section>
  <aside data-col="context"><!-- le <section> di #aside esistono qui, in rail a tab (Task 2) --></aside>
</main>
```

Marker richiesti dall'acceptance: aggiungere gli alias richiesti senza perdere gli ID originali:
`ctx-meter`, `model-chip`, `server-badge` (es. `id="ctxPill" data-alias="ctx-meter"` non basta:
l'acceptance cerca `id="ctx-meter"`; quindi **rinominare** l'id e aggiornare il JS che lo usa —
`loadCtx` etc. — nello stesso commit).

- [ ] **Step 5: CSS del layout 3 colonne + responsive**

```css
#app { display: flex; height: calc(100vh - 44px); }
[data-col="sessions"] { width: 200px; border-right: 1px solid var(--line); overflow-y: auto; }
[data-col="chat"]     { flex: 1; display: flex; flex-direction: column; min-width: 0; }
[data-col="context"]  { width: 238px; border-left: 1px solid var(--line); overflow-y: auto; }
@media (max-width: 1100px) { [data-col="context"] { display: none; } }
@media (max-width: 820px)  { [data-col="sessions"] { display: none; } }
```

- [ ] **Step 6: Aggiornare il JS che referenzia gli id rinominati** (`ctxPill`→`ctx-meter`,
  `modelPill`→`model-chip`, `srvPill`→`server-badge`) nelle funzioni `loadCtx`, `loadStatus`,
  `ensureToken`. Verificare con grep che non restino riferimenti orfani:

```bash
ssh dgx "cd /home/jagones/Repositories/sparkforge && grep -nE 'ctxPill|modelPill|srvPill' webui/index.html"
```
Expected: nessun output (veto: vuoto).

- [ ] **Step 7: Run → PASS (tutti i check, incluse anti-regressione)**

```bash
ssh dgx "cd /home/jagones/Repositories/sparkforge && python3 tests/v080_webui_redesign.py"
```
Expected: `RESULT: PASS`.

- [ ] **Step 8: Commit**

```bash
ssh dgx "cd /home/jagones/Repositories/sparkforge && git add webui/index.html tests/v080_webui_redesign.py && git commit -m 'feat(webui): 3-column shell + design tokens + topbar (phase 1)'"
```

---

## Task 2: Rail contesto con i 5 pannelli (Fase 2)

**Files:** Modify `webui/index.html`, `tests/v080_webui_redesign.py`

- [ ] **Step 1: Aggiungere assertion pannelli**

```python
    for p in ("graph", "config", "self", "settings", "approvals"):
        check("panel tab %s" % p, ('data-panel="%s"' % p) in src)
    check("panel body", 'id="panel-body"' in src)
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Trasformare le `<section>` esistenti di `data-col="context"` in tab**

Le 5 tab mappano sui pannelli ESISTENTI (nessun nuovo fetch se già presente):
`graph`→`#tasks`+`loadGraph`, `config`→`/api/tools` (nuovo, banale), `self`→`/api/self` (nuovo),
`settings`→`/api/providers`+`/api/models` (nuovo), `approvals`→`#approvals`+`loadApprovals`.
Le tab nuove (`config`, `self`, `settings`) riusano `api(method, path, body)` esistente.

```html
<nav id="rail-tabs">
  <button data-panel="graph" class="active" onclick="openPanel('graph')">Graph</button>
  <button data-panel="config" onclick="openPanel('config')">Config</button>
  <button data-panel="self" onclick="openPanel('self')">Self</button>
  <button data-panel="settings" onclick="openPanel('settings')">Settings</button>
  <button data-panel="approvals" onclick="openPanel('approvals')">Approvals</button>
</nav>
<div id="panel-body"><!-- sezione attiva mostrata --></div>
```

```js
function openPanel(name) {
  document.querySelectorAll('[data-panel]').forEach(b => b.classList.toggle('active', b.dataset.panel === name));
  document.querySelectorAll('#panel-body > section').forEach(s => s.hidden = (s.dataset.section !== name));
  if (name === 'graph') loadGraph();
  if (name === 'approvals') loadApprovals();
  if (name === 'self') api('GET', '/api/self').then(renderSelfPanel);
  if (name === 'config') api('GET', '/api/tools').then(renderConfigPanel);
  if (name === 'settings') api('GET', '/api/providers').then(renderSettingsPanel);
}
```

- [ ] **Step 4: Run → PASS**

- [ ] **Step 5: Commit**

```bash
ssh dgx "cd /home/jagones/Repositories/sparkforge && git add webui/index.html tests/v080_webui_redesign.py && git commit -m 'feat(webui): context rail with 5 panels (phase 2)'"
```

---

## Task 3: Chat — tool card interattive + thinking live (Fase 3)

**Files:** Modify `webui/index.html`, `tests/v080_webui_redesign.py`

- [ ] **Step 1: Aggiungere assertion chat**

```python
    check("tool card markup", 'class="toolcard"' in src)
    check("tool card expand", "toggleTool(" in src)
    check("thinking live", 'class="thinking"' in src)
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Estendere `toolCard()`/`updateToolCard()` esistenti, non riscriverli**

`toolCard()` esiste già (riga ~289). Va **arricchito**: aggiungere `class="toolcard"`, l'header
cliccabile con `toggleTool(id)`, corpo espandibile con `args` + `<pre>` risultato, e stato
`ok`/`err` derivato da `data.ok`. Il thinking esistente (`cotFeed`, `#cotDrawer`) va marcato
`class="thinking"` sul contenitore `.t`, senza cambiarne la logica.

```js
function toggleTool(id) { document.getElementById(id)?.classList.toggle('expanded'); }
```

- [ ] **Step 4: Run → PASS**

- [ ] **Step 5: Commit**

```bash
ssh dgx "cd /home/jagones/Repositories/sparkforge && git add webui/index.html tests/v080_webui_redesign.py && git commit -m 'feat(webui): interactive tool cards + thinking styling (phase 3)'"
```

---

## Task 4: Sessioni (ricerca/filtri) + command palette ⌘K (Fase 4)

**Files:** Modify `webui/index.html`, `tests/v080_webui_redesign.py`

- [ ] **Step 1: Aggiungere assertion**

```python
    check("session search", 'id="session-search"' in src)
    check("hide empty filter", 'id="hide-empty"' in src)
    check("command palette", 'id="palette"' in src)
    check("palette shortcut", "metaKey" in src and '"k"' in src)
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Aggiungere ricerca/filtri a `loadSessions()` esistente + palette**

`loadSessions()` esiste (riga ~367): aggiungere i filtri nel render. Nuova `openPalette()`.

```html
<input id="session-search" placeholder="cerca sessione…">
<label><input type="checkbox" id="hide-empty"> nascondi vuote</label>
<div id="palette" hidden><input id="palette-input"><ul id="palette-results"></ul></div>
```

```js
function openPalette() { $('palette').hidden = false; $('palette-input').focus(); }
addEventListener('keydown', e => { if ((e.metaKey || e.ctrlKey) && e.key === 'k') { e.preventDefault(); openPalette(); } });
```

- [ ] **Step 4: Run → PASS**

- [ ] **Step 5: Commit**

```bash
ssh dgx "cd /home/jagones/Repositories/sparkforge && git add webui/index.html tests/v080_webui_redesign.py && git commit -m 'feat(webui): session search/filters + command palette (phase 4)'"
```

---

## Task 5: Bug fix — plan duplicato, sessioni, token UI (Fase 5)

**Files:** Modify `webui/index.html`, `tests/v080_webui_redesign.py`

- [ ] **Step 1: Aggiungere assertion**

```python
    check("plan dedupe", "dedupePlan(" in src)
    check("token field", 'id="token-input"' in src)
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Dedup nel render di `loadPlan()` + campo token**

`loadPlan()` (riga ~473) renderizza `#planSteps`: applicare `dedupePlan(steps)` prima del render
per eliminare gli step identici ("say hello" ×9). Aggiungere in topbar/settings un
`#token-input` che scrive su `localStorage["sf_token"]` (chiave già esistente) e richiama
`ensureToken`/reload.

```js
function dedupePlan(steps) {
  const seen = new Set();
  return (steps || []).filter(s => { const k = (s.text || s.title || '').trim().toLowerCase();
    if (!k || seen.has(k)) return false; seen.add(k); return true; });
}
```

- [ ] **Step 4: Run → PASS**

- [ ] **Step 5: Commit**

```bash
ssh dgx "cd /home/jagones/Repositories/sparkforge && git add webui/index.html tests/v080_webui_redesign.py && git commit -m 'fix(webui): dedupe plan steps + token field (phase 5)'"
```

---

## Task 6: Verifica finale end-to-end

- [ ] **Step 1: Acceptance strutturale**

```bash
ssh dgx "cd /home/jagones/Repositories/sparkforge && python3 tests/v080_webui_redesign.py"
```
Expected: `RESULT: PASS`; report in `data/v080-webui-acceptance.json`.

- [ ] **Step 2: Anti-regressione (conteggio funzioni)**

```bash
ssh dgx "cd /home/jagones/Repositories/sparkforge && grep -cE 'function ' webui/index.html"
```
Expected: ≥ valore del baseline (Task 0 Step 3).

- [ ] **Step 3: Verifica manuale guidata**

Aprire `http://<dgx-tailscale-ip>:8790/?token=<T>` e provare: (a) resize → drawer a 1100/820px;
(b) aprire i 5 pannelli e confrontare con `curl /api/...`; (c) mandare un messaggio → tool card;
(d) cercare una sessione; (e) aprire ⌘K. Annotare i fallimenti.

- [ ] **Step 4: Merge**

```bash
ssh dgx "cd /home/jagones/Repositories/sparkforge && git checkout master && git merge --no-ff feature/webui-redesign -m 'merge: WebUI redesign (5 phases)'"
```

---

## Self-Review

**Spec coverage:** §5→T1, §6→T1, §7→T1, §8→T2, §9→T3, §10→T4, §11→T5, §12→T1/T5, §14→T6.

**Placeholder scan:** nessun TBD; ogni step di codice mostra codice reale; ogni comando ha output atteso.

**Type consistency:** `openPanel()`, `toggleTool()`, `openPalette()`, `dedupePlan()` nuovi e coerenti;
riuso esplicito di `api()`, `loadGraph()`, `loadApprovals()`, `loadSessions()`, `loadPlan()`, `toolCard()`.

**Rischio principale (spec §15):** la rinomina degli id pill (`ctxPill`→`ctx-meter`, ecc.) tocca JS
esistente — mitigato dal controllo grep "nessun orfano" in Task 1 Step 6.
