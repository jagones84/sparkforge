# Long-Horizon Task Tracking (JAG-129) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** L'harness diventa la "segretaria" dei todo: non lascia chiudere il turno finché la TASK LIST ha passi aperti, con stop conditions tipizzate e cap configurabile (anche da WebUI); una sola lista; subagent con todo propri (matrioska); steer che preempt-a; metriche per run.

**Architecture:** La logica di decisione vive in un modulo puro `keepgoing.py` (testabile senza server). Il loop chat (`server.chat_stream_gen`) la usa per decidere se continuare o fermarsi e re-inietta `taskgraph.render_todos`. Config in un blocco `runtime` (come `approvals`) esposto da `/api/tools` e dalla Config WebUI. Subagent: grafo per `run_id` + legame padre↔figlio. Metriche in `runmetrics.py` (`data/runs/<key>.json`).

**Tech Stack:** Python 3 stdlib (nessuna dipendenza nuova). Test = script standalone `tests/vNNN_*.py` con `check(name, ok, detail)` e `sys.exit(0/1)`. Repo su DGX (`z:\Repositories\sparkforge`); comandi via `ssh dgx "bash <script>.sh"` (cwd locale `C:\Users\giova`).

**Contratto ambiente (per ogni task):** letture native su `z:`; scritture/edits/comandi lato Linux via script `.sh`; interprete `python3` (non `python`); niente quote inline nei comandi ssh.

---

## File Structure

- **Create** `keepgoing.py` — decisione pura (defaults, config, hash, `decide`).
- **Create** `runmetrics.py` — metriche per run (`start`/`finish`/`get`, persist `data/runs/`).
- **Modify** `server.py` — loop chat (Parte A), abort+steer (Parte D), metriche (Parte E), route `/api/chat/abort`.
- **Modify** `api_v02.py` — `RunState` metriche; `/api/tools` GET/POST `runtime`.
- **Modify** `taskgraph.py` — legame padre↔figlio `child_run_id` (Parte C).
- **Modify** `subagent.py` — grafo proprio per run + profondità (Parte C).
- **Modify** `webui/index.html` — config runtime, checklist annidata, footer run, steer/abort.
- **Tests** `tests/v138_*.py` (A), `tests/v139_*.py` (B), `tests/v140_*.py` (C), `tests/v141_*.py` (D), `tests/v142_*.py` (E).

---

## FASE A — Loop di completamento

### Task A1: `keepgoing.py` — decisione pura

**Files:**
- Create: `keepgoing.py`
- Test: `tests/v138_keepgoing_loop.py`

- [ ] **Step 1: Write the failing test**

Create `tests/v138_keepgoing_loop.py`:

```python
#!/usr/bin/env python3
"""v0.9.38 acceptance — loop di completamento (JAG-129A)."""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


import keepgoing  # noqa: E402

check("K1 defaults present",
      all(k in keepgoing.DEFAULTS for k in
          ("keepgoing_max", "no_progress_rounds", "max_wall_secs", "subagent_max_depth")),
      str(sorted(keepgoing.DEFAULTS)))
check("K2 default keepgoing_max is 8", keepgoing.DEFAULTS["keepgoing_max"] == 8, "")

d = keepgoing.decide(open_nodes=3, rounds=0, stale=0, started=1000.0, now=1001.0)
check("K3 continues with open nodes", d["continue"] is True and d["reason"] is None, str(d))

check("K4 goal_reached when no open",
      keepgoing.decide(open_nodes=0, rounds=0, stale=0, started=1000.0, now=1001.0)["reason"]
      == "goal_reached", "")
check("K5 budget at cap",
      keepgoing.decide(open_nodes=3, rounds=8, stale=0, started=1000.0, now=1001.0)["reason"]
      == "budget", "")
check("K6 no_progress",
      keepgoing.decide(open_nodes=3, rounds=1, stale=2, started=1000.0, now=1001.0)["reason"]
      == "no_progress", "")
check("K7 blocked",
      keepgoing.decide(open_nodes=3, rounds=0, stale=0, started=1000.0, now=1001.0,
                       blocked=True)["reason"] == "blocked", "")
check("K8 user_stop",
      keepgoing.decide(open_nodes=3, rounds=0, stale=0, started=1000.0, now=1001.0,
                       aborted=True)["reason"] == "user_stop", "")
check("K9 budget on wall-clock",
      keepgoing.decide(open_nodes=3, rounds=0, stale=0, started=1000.0, now=99999.0)["reason"]
      == "budget", "")
check("K10 steer forces continue",
      keepgoing.decide(open_nodes=0, rounds=0, stale=0, started=1000.0, now=1001.0,
                       steer=True)["continue"] is True, "")

h1 = keepgoing.state_hash([{"id": "n1", "status": "todo"}, {"id": "n2", "status": "done"}])
h2 = keepgoing.state_hash([{"id": "n1", "status": "todo"}, {"id": "n2", "status": "done"}])
h3 = keepgoing.state_hash([{"id": "n1", "status": "doing"}, {"id": "n2", "status": "done"}])
check("K11 state_hash stable", h1 == h2 and h1 != h3, "%s %s" % (h1[:8], h3[:8]))
check("K12 tool_hash deterministic",
      keepgoing.tool_hash("shell", {"cmd": "ls"}) == keepgoing.tool_hash("shell", {"cmd": "ls"}),
      "")
check("K13 cfg() exposes overrides",
      keepgoing.cfg({"keepgoing_max": 20})["keepgoing_max"] == 20, "")

total = len(results)
print("\n==== %d/%d checks passed ====" % (sum(results), total))
sys.exit(0 if all(results) else 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/v138_keepgoing_loop.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'keepgoing'` (exit 1).

- [ ] **Step 3: Write minimal implementation**

Create `keepgoing.py`:

```python
#!/usr/bin/env python3
"""Loop di completamento (JAG-129A): la logica che decide se l'harness deve
CONTINUARE a lavorare su una TASK LIST con passi aperti o fermarsi.

Pattern: Ralph/Stop-hook + Claude `/goal`. L'agente non decide quando fermarsi:
lo decide la lista, con stop conditions tipizzate
(goal_reached | no_progress | budget | blocked | user_stop).

Modulo PURO: nessuna dipendenza da server/taskgraph -> testabile in isolamento.
"""
import hashlib
import json
import time

DEFAULTS = {
    "keepgoing_max": 8,       # giri di continuazione prima dello stop 'budget'
    "no_progress_rounds": 2,  # giri senza progresso prima dello stop 'no_progress'
    "max_wall_secs": 3600,    # tetto di tempo per run
    "subagent_max_depth": 2,  # profondita' massima della matrioska
}


def cfg(override=None):
    """Runtime config: DEFAULTS <- config/tools.yaml -> override esplicito."""
    out = dict(DEFAULTS)
    try:
        import registry
        got = (registry.load_config().get("runtime") or {})
        if isinstance(got, dict):
            out.update({k: v for k, v in got.items() if v is not None})
    except Exception:  # noqa: BLE001
        pass
    if isinstance(override, dict):
        out.update(override)
    return out


def state_hash(nodes):
    """Hash stabile dello stato (id,status) dei nodi: rileva il 'no progress'."""
    items = sorted("%s:%s" % (n.get("id"), n.get("status")) for n in (nodes or []))
    return hashlib.sha1(("|".join(items)).encode("utf-8")).hexdigest()


def tool_hash(tool, args):
    """Hash di una chiamata tool+args: rileva la ripetizione identica."""
    try:
        blob = json.dumps({"t": tool, "a": args}, sort_keys=True, default=str)
    except Exception:  # noqa: BLE001
        blob = "%s:%s" % (tool, args)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def decide(open_nodes, rounds, stale, started, now=None, aborted=False, blocked=False,
           steer=False, override=None):
    """Decide se continuare. Ritorna {"continue": bool, "reason": str|None}.

    Ordine di priorita' (la prima che scatta vince): user_stop, goal_reached,
    blocked, budget (tempo), budget (giri), no_progress. `steer` forza la
    continuazione (reindirizzamento utente) anche con la lista vuota.
    """
    c = cfg(override)
    now = time.time() if now is None else float(now)
    if aborted:
        return {"continue": False, "reason": "user_stop"}
    if open_nodes <= 0:
        if steer:
            return {"continue": True, "reason": None}
        return {"continue": False, "reason": "goal_reached"}
    if blocked:
        return {"continue": False, "reason": "blocked"}
    if now - float(started) >= float(c["max_wall_secs"]):
        return {"continue": False, "reason": "budget"}
    if int(rounds) >= int(c["keepgoing_max"]):
        return {"continue": False, "reason": "budget"}
    if int(stale) >= int(c["no_progress_rounds"]):
        return {"continue": False, "reason": "no_progress"}
    return {"continue": True, "reason": None}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/v138_keepgoing_loop.py`
Expected: `==== 13/13 checks passed ====` (exit 0).

- [ ] **Step 5: Commit**

```bash
git add keepgoing.py tests/v138_keepgoing_loop.py
git commit -m "feat(keepgoing): decisione pura del loop di completamento (JAG-129A)"
```

---

### Task A2: integrazione nel loop chat (Parte A)

**Files:**
- Modify: `server.py` — `chat_stream_gen`: sostituire il gate una-tantum ([server.py:2023-2041](file:///z:/Repositories/sparkforge/server.py#L2023-L2041)) con la decisione `keepgoing`.
- Test: `tests/v138_keepgoing_loop.py`

- [ ] **Step 1: Write the failing test (append prima di `total = len(results)`)**

```python
srv = open(os.path.join(REPO, "server.py"), encoding="utf-8", errors="replace").read()
check("S1 chat loop imports keepgoing", "import keepgoing" in srv, "")
check("S2 emits plan.continuing", "plan.continuing" in srv, "")
check("S3 emits plan.stopped with reason", "plan.stopped" in srv and '"reason"' in srv, "")
check("S4 no one-shot verify gate left", "verify_nudged" not in srv, "")
check("S5 re-injects the todo list", "render_todos" in srv and "CONTINUA" in srv, "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/v138_keepgoing_loop.py`
Expected: FAIL su S1-S5 (il gate una-tantum `verify_nudged` è ancora presente).

- [ ] **Step 3: Write minimal implementation**

3a. In `server.py`, prima del `while` del loop chat ([server.py:1877](file:///z:/Repositories/sparkforge/server.py#L1877) circa, accanto a `work_steps = 0`), aggiungi lo stato del loop:

```python
    work_steps = 0
    iters = 0
    used_tools = []
    # JAG-129A: stato del loop di completamento (vedi keepgoing.decide).
    import keepgoing as _kg
    _kg_rounds = 0
    _kg_prev = None
    _kg_stale = 0
    _kg_started = time.time()
    _kg_last_tool = None
```

3b. Sostituisci **integralmente** il blocco del gate una-tantum ([server.py:2023-2041](file:///z:/Repositories/sparkforge/server.py#L2023-L2041)):

```python
        if not verify_nudged and tool_ctx:
            _open_n = _open_plan_steps(sess)
            if _open_n:
                verify_nudged = True
                msgs.append({"role": "assistant", "content": answer})
                msgs.append({"role": "user", "content": (
                    "VERIFICATION GATE: your task list still has %d open step(s). Do "
                    ...
                    "open item is done or irrelevant." % _open_n)})
                continue
```

con:

```python
        if tool_ctx:
            # JAG-129A: l'harness (la "segretaria") decide se l'agente puo' davvero
            # chiudere. Con passi aperti re-inietta la lista e CONTINUA.
            _g = taskgraph.load(sess["id"]) or {}
            _nodes = _g.get("nodes", [])
            _open = [n for n in _nodes if n.get("status") in taskgraph.OPEN_STATUSES]
            _cur = _kg.state_hash(_nodes)
            _kg_stale = (_kg_stale + 1) if (_kg_prev is not None and _cur == _kg_prev) else 0
            _dec = _kg.decide(open_nodes=len(_open), rounds=_kg_rounds, stale=_kg_stale,
                              started=_kg_started, aborted=_is_aborted(sess["id"]),
                              blocked=any(n.get("status") == "blocked" for n in _nodes),
                              steer=has_steer(sess["id"]))
            if _dec["continue"]:
                _kg_rounds += 1
                _kg_prev = _cur
                on_event("plan.continuing", session=sess["id"], round=_kg_rounds,
                         open=len(_open), total=len(_nodes))
                msgs.append({"role": "assistant", "content": answer})
                msgs.append({"role": "user", "content": (
                    "CONTINUA: la tua TASK LIST ha ancora %d passo/i aperto/i. NON "
                    "fermarti e non chiedere il permesso. Per OGNI passo aperto: "
                    "esegui l'azione con una tool call, poi marcalo 'done' con "
                    "update_todos e l'evidenza concreta; se non serve piu', "
                    "ripianifica. Lista attuale:\n%s"
                    % (len(_open), taskgraph.render_todos(taskgraph.load(sess["id"]))))})
                continue
            on_event("plan.stopped", session=sess["id"], reason=_dec["reason"],
                     open=len(_open), total=len(_nodes), rounds=_kg_rounds,
                     duration_s=round(time.time() - _kg_started, 1))
        for ch, t in collected:
            on_delta(ch, t)
        final_answer, think = answer, think
        break
```

3c. Rimuovi la riga `verify_nudged = False  # JAG-87...` ([server.py:1840](file:///z:/Repositories/sparkforge/server.py#L1840)) e la costante locale `verify_nudged` (non più usata; il gate è ora illimitato entro il cap).

3d. Rimpiazza il blocco `plan.incomplete` ([server.py:2118-2131](file:///z:/Repositories/sparkforge/server.py#L2118-L2131)) con il solo calcolo delle metriche di fine turno (il warning non serve più: ora la lista viene chiusa o il loop emette `plan.stopped`):

```python
    try:
        _g = taskgraph.load(sess["id"])
        _nodes = (_g or {}).get("nodes", [])
        _open = [n for n in _nodes if n.get("status") not in ("done", "cancelled")]
        if _open:
            publish("plan.incomplete", session=sess["id"], open=len(_open),
                    total=len(_nodes),
                    items=[str(n.get("label", "")) for n in _open][:12])
    except Exception:  # noqa: BLE001
        pass
```

(NOTA: resta come rete di sicurezza se il loop è stato interrotto da abort; `plan.incomplete` convive con `plan.stopped`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/v138_keepgoing_loop.py`
Expected: tutti PASS (13/13 + S1-S5 = 18/18).

- [ ] **Step 5: Verifica di non-regressione**

Run: `python3 tests/v134_plan_incomplete.py` → atteso `8/8` (il banner resta).
Run: `python3 tests/v136_prompt_sections.py` → atteso `19/19`.

- [ ] **Step 6: Commit**

```bash
git add server.py tests/v138_keepgoing_loop.py
git commit -m "feat(chat): loop di completamento al posto del gate una-tantum (JAG-129A)"
```

---

### Task A3: abort utente nel chat (`user_stop`)

**Files:**
- Modify: `server.py` — accanto a `STEER_INBOX`/`push_steer`/`drain_steer` ([server.py:1148-1168](file:///z:/Repositories/sparkforge/server.py#L1148-L1168)); route `/api/chat/abort` (accanto a `/api/chat/steer`, [server.py:3351](file:///z:/Repositories/sparkforge/server.py#L3351)).
- Test: `tests/v138_keepgoing_loop.py`

- [ ] **Step 1: Write the failing test (append)**

```python
check("S6 has abort helpers", "def push_abort" in srv and "def _is_aborted" in srv, "")
check("S7 has /api/chat/abort route", '"/api/chat/abort"' in srv, "")
check("S8 abort flag cleared at turn start", "clear_abort" in srv, "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/v138_keepgoing_loop.py`
Expected: FAIL su S6-S8.

- [ ] **Step 3: Write minimal implementation**

3a. In `server.py`, dopo `drain_steer` ([server.py:1168](file:///z:/Repositories/sparkforge/server.py#L1168)):

```python
# JAG-129A: abort di un turno di chat in corso (distinto dallo steer: steer
# reindirizza, abort ferma). Il loop controlla il flag ad ogni giro.
ABORT_INBOX = set()
_abort_lock = threading.Lock()


def push_abort(sess_id):
    if not sess_id:
        return False
    with _abort_lock:
        ABORT_INBOX.add(sess_id)
    return True


def _is_aborted(sess_id):
    with _abort_lock:
        return sess_id in ABORT_INBOX


def clear_abort(sess_id):
    with _abort_lock:
        ABORT_INBOX.discard(sess_id)
```

3b. In `chat_stream_gen`, all'inizio del turno (dopo `import keepgoing as _kg` del Task A2):

```python
    clear_abort(sess["id"])
```

3c. Route, accanto a `/api/chat/steer` ([server.py:3351](file:///z:/Repositories/sparkforge/server.py#L3351)):

```python
        if path == "/api/chat/abort":
            # JAG-129A: ferma il turno in corso (l'agente non deve continuare).
            sid = body.get("session") or qs.get("session")
            if not sid:
                return self._send(400, {"error": "session required"})
            push_abort(sid)
            publish("chat.abort", session=sid)
            return self._send(200, {"ok": True, "aborted": sid})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/v138_keepgoing_loop.py`
Expected: tutti PASS (21/21).

- [ ] **Step 5: Commit**

```bash
git add server.py tests/v138_keepgoing_loop.py
git commit -m "feat(chat): abort del turno + user_stop nel loop (JAG-129A)"
```

---

### Task A4: config `runtime` (GET/POST + WebUI)

**Files:**
- Modify: `api_v02.py` — `/api/tools` GET include `runtime`; POST aggiorna `runtime` (stesso pattern di `approvals`, [api_v02.py:283-303](file:///z:/Repositories/sparkforge/api_v02.py#L283-L303)).
- Modify: `config/tools.yaml` — blocco `runtime:` di default.
- Modify: `webui/index.html` — card "Runtime / long-horizon".
- Test: `tests/v138_keepgoing_loop.py`

- [ ] **Step 1: Write the failing test (append)**

```python
import registry  # noqa: E402
check("R1 config/tools.yaml has runtime block",
      "runtime:" in open(os.path.join(REPO, "config", "tools.yaml"),
                         encoding="utf-8").read(), "")
api = open(os.path.join(REPO, "api_v02.py"), encoding="utf-8", errors="replace").read()
check("R2 /api/tools returns runtime", '"runtime"' in api, "")
check("R3 POST accepts runtime", "runtime" in api and "def update_policy" in api, "")
web = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8", errors="replace").read()
check("R4 WebUI has runtime fields",
      "keepgoing_max" in web and "no_progress_rounds" in web, "")
check("R5 keepgoing reads the runtime config", "load_config().get(\"runtime\")" in
      open(os.path.join(REPO, "keepgoing.py"), encoding="utf-8").read(), "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/v138_keepgoing_loop.py`
Expected: FAIL su R1-R4.

- [ ] **Step 3: Write minimal implementation**

3a. In `config/tools.yaml`, dopo il blocco `approvals:` ([config/tools.yaml:26-28](file:///z:/Repositories/sparkforge/config/tools.yaml#L26-L28)):

```yaml
# ---- runtime / long-horizon (JAG-129) ---------------------------------------
# Controlla il loop di completamento: l'harness non lascia chiudere il turno
# finche' la TASK LIST ha passi aperti. Editabile anche dalla WebUI (Config).
runtime:
  keepgoing_max: 8          # giri di continuazione prima dello stop 'budget'
  no_progress_rounds: 2     # giri senza progresso prima dello stop 'no_progress'
  max_wall_secs: 3600       # tetto di tempo per run
  subagent_max_depth: 2     # profondita' massima della matrioska
```

3b. In `api_v02.py`, nella GET `/api/tools` (accanto a `"policy": registry.load_config().get("approvals")`):

```python
        "runtime": registry.load_config().get("runtime") or {},
```

3c. In `api_v02.py`, nella `update_policy` della POST `/api/tools` (dove fa il merge di `approvals`):

```python
        if isinstance(body.get("runtime"), dict):
            cfg.setdefault("runtime", {})
            for k in ("keepgoing_max", "no_progress_rounds", "max_wall_secs",
                      "subagent_max_depth"):
                if k in body["runtime"] and body["runtime"][k] is not None:
                    cfg["runtime"][k] = int(body["runtime"][k])
```

3d. In `webui/index.html`, nel pannello Config (accanto alla card policy di approvazione), aggiungi la funzione e il markup:

```javascript
async function loadRuntime() {
  const d = await api("GET", "/api/tools");
  const r = (d && d.runtime) || {};
  if ($("rtKgMax")) $("rtKgMax").value = r.keepgoing_max ?? 8;
  if ($("rtNoProg")) $("rtNoProg").value = r.no_progress_rounds ?? 2;
  if ($("rtWall")) $("rtWall").value = r.max_wall_secs ?? 3600;
  if ($("rtDepth")) $("rtDepth").value = r.subagent_max_depth ?? 2;
}
async function saveRuntime() {
  await api("POST", "/api/tools", { runtime: {
    keepgoing_max: +$("rtKgMax").value,
    no_progress_rounds: +$("rtNoProg").value,
    max_wall_secs: +$("rtWall").value,
    subagent_max_depth: +$("rtDepth").value,
  }});
  who("ai", "✅ runtime aggiornato");
}
```

e nel markup del pannello Config:

```html
<div class="card"><b>Runtime / long-horizon</b>
  <label>giri di continuazione <input id="rtKgMax" type="number" min="0" value="8"></label>
  <label>no-progress rounds <input id="rtNoProg" type="number" min="0" value="2"></label>
  <label>tetto tempo (s) <input id="rtWall" type="number" min="0" value="3600"></label>
  <label>profondità subagent <input id="rtDepth" type="number" min="0" value="2"></label>
  <button class="ghost" onclick="saveRuntime()">salva runtime</button>
</div>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/v138_keepgoing_loop.py`
Expected: tutti PASS (26/26).

- [ ] **Step 5: Commit**

```bash
git add api_v02.py config/tools.yaml webui/index.html tests/v138_keepgoing_loop.py
git commit -m "feat(config): runtime long-horizon editabile (api + webui) (JAG-129A)"
```

---

## FASE B — Una sola lista

### Task B1: `/api/plan` alias della TASK LIST

**Files:**
- Modify: `server.py` — route `/api/plan` ([server.py:3381-3385](file:///z:/Repositories/sparkforge/server.py#L3381-L3385)).
- Test: `tests/v139_unified_tasklist.py`

- [ ] **Step 1: Write the failing test**

Create `tests/v139_unified_tasklist.py`:

```python
#!/usr/bin/env python3
"""v0.9.38 acceptance — una sola TASK LIST (JAG-129B)."""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


srv = open(os.path.join(REPO, "server.py"), encoding="utf-8", errors="replace").read()
check("B1 /api/plan is an alias of the task list",
      "/api/plan" in srv and "taskgraph.public" in srv, "")
check("B2 no second source of truth for /api/plan",
      "return self._send(200, plan)" not in srv, "")

web = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8", errors="replace").read()
check("B3 WebUI has ONE task-list section",
      web.count("TASK LIST") >= 1 and "RUN GRAPH" not in web, "")

total = len(results)
print("\n==== %d/%d checks passed ====" % (sum(results), total))
sys.exit(0 if all(results) else 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/v139_unified_tasklist.py`
Expected: FAIL su B1-B3.

- [ ] **Step 3: Write minimal implementation**

3a. In `server.py`, sostituisci il blocco `/api/plan` ([server.py:3381-3385](file:///z:/Repositories/sparkforge/server.py#L3381-L3385)) con un alias di lettura della task list:

```python
        if path == "/api/plan":
            # JAG-129B: il "plan" legacy E' la task list persistente (una sola
            # fonte di verita': il taskgraph della sessione).
            sid = body.get("session") or qs.get("session") or ""
            _g = taskgraph.load(sid) if sid else None
            return self._send(200, taskgraph.public(_g) or {"nodes": [], "counts": {}})
```

3b. In `webui/index.html`, sostituisci l'intestazione del pannello "RUN GRAPH" con "TASK LIST (persistente)" (una sola sezione); il grafo corrente è la stessa lista.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/v139_unified_tasklist.py`
Expected: `3/3`.

- [ ] **Step 5: Verifica di non-regressione**

Run: `python3 tests/v136_prompt_sections.py` → `19/19`.

- [ ] **Step 6: Commit**

```bash
git add server.py webui/index.html tests/v139_unified_tasklist.py
git commit -m "refactor(plan): /api/plan alias della TASK LIST, una sola sezione (JAG-129B)"
```

---

### Task B2: checklist annidata stile TRAE in chat

**Files:**
- Modify: `webui/index.html` — listener `plan.continuing`/`plan.stopped`; render annidato dei nodi.
- Test: `tests/v139_unified_tasklist.py`

- [ ] **Step 1: Write the failing test (append)**

```python
check("B4 chat shows plan.continuing", "plan.continuing" in web, "")
check("B5 chat shows plan.stopped", "plan.stopped" in web, "")
check("B6 nested checklist renderer", "function taskTree" in web or "parent" in web, "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/v139_unified_tasklist.py`
Expected: FAIL su B4-B6.

- [ ] **Step 3: Write minimal implementation**

3a. In `webui/index.html`, nel blocco SSE della chat (accanto a `plan.incomplete`):

```javascript
  es.addEventListener("plan.continuing", e => { planContinuing(JSON.parse(e.data)); });
  es.addEventListener("plan.stopped", e => planStopped(JSON.parse(e.data)));
```

3b. Funzioni (accanto a `planIncomplete`):

```javascript
function planContinuing(d) {
  who("ai", `🔁 continuo da solo — ${d.open}/${d.total} passi aperti (giro ${d.round})`);
}
function planStopped(d) {
  const map = { goal_reached: "✅ goal raggiunto", no_progress: "⚠ nessun progresso",
                budget: "⏱ budget esaurito", blocked: "⛔ bloccato",
                user_stop: "⏹ fermato da te" };
  who("ai", `${map[d.reason] || d.reason} — ${d.open} aperti / ${d.total} · ${d.rounds} giri · ${d.duration_s}s`);
}
function taskTree(nodes) {
  // checklist annidata: i figli (parent) sono indentati sotto il padre (stile TRAE).
  const byParent = {};
  nodes.forEach(n => { const p = n.parent || "_root"; (byParent[p] ||= []).push(n); });
  const mark = { todo: "☐", doing: "◐", done: "☑", blocked: "⛔", cancelled: "⊘" };
  const walk = (p, depth) => (byParent[p] || []).map(n =>
    `<div style="margin-left:${depth * 14}px">${mark[n.status] || "☐"} ${esc(n.label)}</div>`
    + walk(n.id, depth + 1)).join("");
  return walk("_root", 0);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/v139_unified_tasklist.py`
Expected: `6/6`.

- [ ] **Step 5: Commit**

```bash
git add webui/index.html tests/v139_unified_tasklist.py
git commit -m "feat(webui): checklist annidata + eventi continuazione (JAG-129B)"
```

---

## FASE C — Todo annidati per subagent

### Task C1: grafo proprio per subagent + legame padre↔figlio

**Files:**
- Modify: `subagent.py` — [`spawn`](file:///z:/Repositories/sparkforge/subagent.py#L36) passa `session_id=run_id` e applica `subagent_max_depth`.
- Modify: `taskgraph.py` — [`add_node`](file:///z:/Repositories/sparkforge/taskgraph.py#L231) accetta `child_run_id`.
- Modify: `server.py` — `_apply_chat_todos`/azione `subagent` collega il nodo al figlio.
- Test: `tests/v140_subagent_todos.py`

- [ ] **Step 1: Write the failing test**

Create `tests/v140_subagent_todos.py`:

```python
#!/usr/bin/env python3
"""v0.9.38 acceptance — todo annidati per subagent (JAG-129C)."""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ["SPARKFORGE_GRAPH_DIR"] = tempfile.mkdtemp()
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


import taskgraph  # noqa: E402

g = taskgraph.ensure("run_child1", session_id="run_child1", goal="child")
n = taskgraph.add_node(g, "subtask A", child_run_id="sub_123")
check("C1 node carries child_run_id", n.get("child_run_id") == "sub_123", str(n.get("child_run_id")))

child = taskgraph.ensure("sub_123", session_id="sub_123", goal="child goal")
taskgraph.apply_write_todos(child, [{"label": "passo figlio 1"}, {"label": "passo figlio 2"}])
check("C2 child has its own list", len(taskgraph.load("sub_123")["nodes"]) == 2, "")
check("C3 parent list is separate", len(taskgraph.load("run_child1")["nodes"]) == 1, "")

import keepgoing  # noqa: E402
import subagent  # noqa: E402
check("C4 depth limit enforced", subagent.depth_allowed(2, 2) is False, "")
check("C5 depth allowed below cap", subagent.depth_allowed(1, 2) is True, "")

total = len(results)
print("\n==== %d/%d checks passed ====" % (sum(results), total))
sys.exit(0 if all(results) else 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/v140_subagent_todos.py`
Expected: FAIL — `add_node` rifiuta `child_run_id` / `subagent.depth_allowed` mancante.

- [ ] **Step 3: Write minimal implementation**

3a. In `taskgraph.py`, firma e nodo di `add_node` ([taskgraph.py:231-252](file:///z:/Repositories/sparkforge/taskgraph.py#L231-L252)):

```python
def add_node(graph, label, deps=None, status="todo", evidence=None, node_id=None,
             source="model", parent=None, child_run_id=None):
    ...
    node = {"id": node_id or _next_id(graph), "label": label, "status": status,
            "deps": deps, "parent": str(parent) if parent else None, "evidence": ev,
            "source": source, "child_run_id": child_run_id,
            "created": round(time.time(), 3), "updated": round(time.time(), 3)}
```

3b. In `subagent.py`, aggiungi l'helper e usalo in `spawn`:

```python
def depth_allowed(depth, max_depth=None):
    """True se si puo' ancora annidare (matrioska) sotto `depth` livelli."""
    import keepgoing
    md = int(keepgoing.cfg()["subagent_max_depth"])
    if max_depth is not None:
        md = int(max_depth)
    return int(depth) < md


def spawn(goal, parent_run_id=None, max_steps=4, model=None, on_event=None, depth=0):
    ...
    st = api_v02.new_run("%s (subagent %s)" % (goal[:80], sid), model, max_steps)
    st.parent_run_id = parent_run_id
```

3c. In `server.py`, dove si gestisce l'azione/risultato subagent, collega il nodo:

```python
            node = taskgraph.add_node(graph, label_of_subagent_goal, source="subagent",
                                      child_run_id=result["subagent_id"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/v140_subagent_todos.py`
Expected: `5/5`.

- [ ] **Step 5: Commit**

```bash
git add taskgraph.py subagent.py server.py tests/v140_subagent_todos.py
git commit -m "feat(subagent): todo annidati per run + legame padre-figlio (JAG-129C)"
```

---

## FASE D — Steer = preemption

### Task D1: steer iniettato subito, consumato anche a fine loop

**Files:**
- Modify: `server.py` — `has_steer`; drain prima del modello e prima del tool; drain al punto di chiusura ([server.py:1883](file:///z:/Repositories/sparkforge/server.py#L1883)).
- Test: `tests/v141_steer_preemption.py`

- [ ] **Step 1: Write the failing test**

Create `tests/v141_steer_preemption.py`:

```python
#!/usr/bin/env python3
"""v0.9.38 acceptance — steer preemption (JAG-129D)."""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


srv = open(os.path.join(REPO, "server.py"), encoding="utf-8", errors="replace").read()
check("D1 has has_steer helper", "def has_steer" in srv, "")
check("D2 steer drained before the model call", "drain_steer" in srv and
      srv.count("drain_steer") >= 2, "")
check("D3 steer drained at the close point too", "steer=has_steer" in srv, "")
check("D4 chat.steer carries applied flag", '"applied"' in srv or "applied=True" in srv, "")

total = len(results)
print("\n==== %d/%d checks passed ====" % (sum(results), total))
sys.exit(0 if all(results) else 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/v141_steer_preemption.py`
Expected: FAIL su D1-D4.

- [ ] **Step 3: Write minimal implementation**

3a. In `server.py`, dopo `drain_steer` ([server.py:1168](file:///z:/Repositories/sparkforge/server.py#L1168)):

```python
def has_steer(sess_id):
    """True se c'e' uno steer in attesa (usato dal loop per preempt-are)."""
    with _steer_lock:
        return bool(STEER_INBOX.get(sess_id))
```

3b. Nel punto di chiusura (già `steer=has_steer(sess["id"])` nel Task A2), aggiungi il drain+inject PRIMA del `continue`:

```python
            if _dec["continue"]:
                _kg_rounds += 1
                _kg_prev = _cur
                for _s in drain_steer(sess["id"]):
                    msgs.append({"role": "user", "content":
                                 "[user steering — take this into account now] " + _s})
                    on_event("chat.steer", session=sess["id"], text=_s, applied=True)
                on_event("plan.continuing", session=sess["id"], round=_kg_rounds,
                         open=len(_open), total=len(_nodes))
                ...
                continue
```

3c. Prima di OGNI chiamata al modello nel loop, aggiungi il controllo di prelazione (subito dopo il `for _s in drain_steer(...)` esistente in cima al `while`):

```python
        for _s in drain_steer(sess["id"]):
            msgs.append({"role": "user", "content":
                         "[user steering — take this into account now] " + _s})
            on_event("chat.steer", session=sess["id"], text=_s, applied=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/v141_steer_preemption.py`
Expected: `4/4`.

- [ ] **Step 5: Commit**

```bash
git add server.py tests/v141_steer_preemption.py
git commit -m "fix(chat): steer = preemption, consumato anche a fine loop (JAG-129D)"
```

---

## FASE E — Metriche per run

### Task E1: `runmetrics.py` + durata/giri/token/esito

**Files:**
- Create: `runmetrics.py`
- Modify: `server.py` — start/finish del turno; inclusione nella risposta finale.
- Modify: `api_v02.py` — `RunState.public()` include le metriche.
- Test: `tests/v142_run_metrics.py`

- [ ] **Step 1: Write the failing test**

Create `tests/v142_run_metrics.py`:

```python
#!/usr/bin/env python3
"""v0.9.38 acceptance — metriche per run (JAG-129E)."""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ["SPARKFORGE_RUNS_DIR"] = tempfile.mkdtemp()
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


import runmetrics  # noqa: E402

runmetrics.start("k1", model="m1")
rec = runmetrics.finish("k1", outcome="done", stop_reason="goal_reached",
                        iterations=3, steps=5, tokens=1234)
check("E1 duration recorded", rec.get("duration_s") is not None and rec["duration_s"] >= 0, "")
check("E2 fields recorded",
      rec["outcome"] == "done" and rec["stop_reason"] == "goal_reached"
      and rec["iterations"] == 3 and rec["steps"] == 5 and rec["tokens"] == 1234, str(rec))
check("E3 persisted to disk", runmetrics.get("k1")["outcome"] == "done", "")
check("E4 human readable line", "goal_reached" in runmetrics.human("k1"), "")

total = len(results)
print("\n==== %d/%d checks passed ====" % (sum(results), total))
sys.exit(0 if all(results) else 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/v142_run_metrics.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'runmetrics'`.

- [ ] **Step 3: Write minimal implementation**

Create `runmetrics.py`:

```python
#!/usr/bin/env python3
"""Metriche per run (JAG-129E): quanto ha lavorato un run.

Scrive data/runs/<key>.json con: started, ended, duration_s, iterations, steps,
tokens, model, outcome, stop_reason. `human()` produce la riga in chiaro.
"""
import json
import os
import time

REPO = os.path.dirname(os.path.abspath(__file__))
RUNS_DIR = os.environ.get("SPARKFORGE_RUNS_DIR", os.path.join(REPO, "data", "runs"))
_START = {}


def _path(key):
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in str(key))[:96]
    return os.path.join(RUNS_DIR, safe + ".json")


def start(key, model=None):
    rec = {"key": key, "model": model, "started": round(time.time(), 3),
           "ended": None, "duration_s": None, "iterations": 0, "steps": 0,
           "tokens": 0, "outcome": "running", "stop_reason": None}
    _START[key] = rec["started"]
    _write(key, rec)
    return rec


def finish(key, outcome="done", stop_reason=None, iterations=0, steps=0, tokens=0):
    rec = get(key)
    if not rec:
        rec = start(key)
    now = round(time.time(), 3)
    rec.update({"ended": now, "iterations": int(iterations), "steps": int(steps),
                "tokens": int(tokens), "outcome": outcome, "stop_reason": stop_reason})
    started = _START.get(key) or rec.get("started") or now
    rec["duration_s"] = round(now - float(started), 1)
    _write(key, rec)
    return rec


def _write(key, rec):
    os.makedirs(RUNS_DIR, exist_ok=True)
    tmp = _path(key) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _path(key))


def get(key):
    try:
        with open(_path(key), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def human(key):
    r = get(key) or {}
    return ("run %s · %s · %s giri · %s step · %s tok · %ss"
            % (key, r.get("stop_reason") or r.get("outcome"),
               r.get("iterations"), r.get("steps"), r.get("tokens"),
               r.get("duration_s")))
```

3b. In `server.py`, all'inizio di `chat_stream_gen` (dopo `clear_abort`):

```python
    import runmetrics
    runmetrics.start(sess["id"], model=model)
```

3c. Alla fine del turno, prima del `publish("chat.done", ...)`:

```python
    runmetrics.finish(sess["id"], outcome=("error" if meta.get("error") else "done"),
                      stop_reason=locals().get("_kg_stop_reason"),
                      iterations=_kg_rounds, steps=work_steps,
                      tokens=int(chat_usage.get("prompt_tokens") or 0)
                             + int(chat_usage.get("completion_tokens") or 0))
    publish("run.metrics", session=sess["id"], metrics=runmetrics.get(sess["id"]))
```

3d. Registra `_kg_stop_reason` nel punto di stop (Task A2): aggiungi `_kg_stop_reason = _dec["reason"]` nel ramo `else` del `if _dec["continue"]`, e inizializza `_kg_stop_reason = None` accanto a `_kg_rounds = 0`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/v142_run_metrics.py`
Expected: `4/4`.

- [ ] **Step 5: Verifica di non-regressione complessiva**

Run: `python3 tests/v138_keepgoing_loop.py` → `26/26`
Run: `python3 tests/v139_unified_tasklist.py` → `6/6`
Run: `python3 tests/v140_subagent_todos.py` → `5/5`
Run: `python3 tests/v141_steer_preemption.py` → `4/4`
Run: `python3 tests/v142_run_metrics.py` → `4/4`
Run: `python3 tests/v136_prompt_sections.py` → `19/19`
Run: `python3 tests/v134_plan_incomplete.py` → `8/8`

- [ ] **Step 6: Commit**

```bash
git add runmetrics.py server.py api_v02.py tests/v142_run_metrics.py
git commit -m "feat(runmetrics): durata/giri/step/token/esito per run (JAG-129E)"
```

---

## Self-review (gaps / placeholder check)

- **Spec coverage:** A → Task A1-A4 (decide, loop, abort, config). B → B1-B2 (alias, checklist). C → C1 (grafo per run + legame + depth). D → D1 (preemption). E → E1 (metriche). Coperto.
- **Placeholder scan:** nessun TBD; ogni step ha codice o comando+output atteso. Le sostituzioni "integralmente il blocco" citano ancore esatte; l'esecutore deve leggere il file prima di applicare.
- **Type consistency:** `keepgoing.decide(open_nodes, rounds, stale, started, now, aborted, blocked, steer, override)` coerente tra A1/A2/D1; `state_hash(nodes)`, `tool_hash(tool,args)`, `cfg(override)` coerenti; `runmetrics.start/finish/get/human` coerenti tra E1 e l'integrazione; `taskgraph.add_node(..., child_run_id=)` coerente tra C1 e i chiamanti; `subagent.depth_allowed(depth, max_depth)` coerente.
- **Nota di ordine:** A2 e D1 toccano lo stesso blocco del loop → eseguire A2 **prima** di D1 (D1 presuppone `steer=has_steer` introdotto in A2).
