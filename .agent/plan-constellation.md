# Orbit Constellation Window — Implementation Plan (JAG-296)

> **For agentic workers:** execute task-by-task. Steps use `- [ ]`. Spec:
> `.agent/design-constellation.md`. Project rule: run `tests/battery.sh` and keep it GREEN.

**Goal:** turn the Orbit tactical modal into a single floating, non-modal constellation
window (per-agent and ALL modes) and make Orbit deep-link into the main app.

**Architecture:** one aggregate read-only endpoint feeds the UI; the UI is dependency-free
vanilla JS + hand-rolled SVG; the main app gains `?session=&node=` deep-link handling.

**Tech Stack:** Python stdlib (http.server), vanilla JS, SVG. No new dependencies.

---

## File structure
- Modify `src2/orbit_beta/api.py` — add `GET /api/orbit/constellation` + `_constellation()`.
- Modify `src2/orbit_beta/web/orbit.html` — replace the modal with the floating
  `Constellation` window; keep `OrgChartView`, `JobsView`; add deep-link on dblclick.
- Modify `webui/index.html` — honour `?session=` and `?node=` on startup.
- Create `tests/v294_constellation.py` — endpoint + UI + deep-link assertions.
- Modify `tests/battery.sh` — add v294 (battery → 59).

---

## Task 1 — Aggregate endpoint `GET /api/orbit/constellation`

**Files:** Modify `src2/orbit_beta/api.py`. Test `tests/v294_constellation.py`.

- [ ] **Step 1: failing test** (create `tests/v294_constellation.py`)

```python
#!/usr/bin/env python3
"""v294 — Orbit constellation: aggregate endpoint + non-modal window + deep-link."""
import os, sys
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "src2"))
results = []
def check(n, ok, d=""):
    results.append(bool(ok)); print(("PASS " if ok else "FAIL ") + n + ((" :: " + d) if d else ""))

from orbit_beta import api as oapi
check("api exposes _constellation", hasattr(oapi, "_constellation"))
c = oapi._constellation()
check("constellation shape", set(["agents", "jobs", "graphs"]) <= set(c.keys()))
check("agents is a list", isinstance(c["agents"], list))
check("graphs is a dict", isinstance(c["graphs"], dict))

with open(os.path.join(REPO, "src2", "orbit_beta", "api.py"), encoding="utf-8") as f:
    a = f.read()
check("constellation route registered", '"/api/orbit/constellation"' in a)

with open(os.path.join(REPO, "src2", "orbit_beta", "web", "orbit.html"), encoding="utf-8") as f:
    ui = f.read()
check("float window id exists", 'id="constWin"' in ui)
check("NO modal backdrop", 'class="modal"' not in ui and "tacModal" not in ui)
check("AGENT/ALL toggle", 'id="constAgent"' in ui and 'id="constAll"' in ui)
check("clusters per agent", "clusterOf" in ui or "byAgent" in ui)
check("deep-link carries session+node", "session=" in ui and "node=" in ui)

with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    gui = f.read()
check("main reads ?session param", 'searchParams.get("session")' in gui)
check("main reads ?node param", 'searchParams.get("node")' in gui)

print("---"); p = sum(results); print("%d/%d PASS" % (p, len(results)))
sys.exit(0 if p == len(results) else 1)
```

- [ ] **Step 2: run it — expect FAIL** on `_constellation` missing.
- [ ] **Step 3: implement** in `src2/orbit_beta/api.py` (add helper + route):

```python
def _constellation():
    """Aggregate agents + jobs + every agent's task graph for the Orbit constellation."""
    from sparkforge import agents as _agents, jobs as _jobs, taskgraph as _tg
    ags = _agents.REGISTRY.list().get("agents", [])
    jbs = _jobs.REGISTRY.list().get("jobs", [])
    graphs = {}
    for a in ags:
        sid = a.get("session")
        if not sid:
            continue
        g = _tg.load(sid) or {}
        graphs[sid] = {"nodes": g.get("nodes", []), "run_id": g.get("run_id")}
    return {
        "agents": [{"id": a.get("id"), "session": a.get("session"), "name": a.get("name"),
                    "role": a.get("role"), "reports_to": a.get("reports_to"),
                    "model": a.get("model")} for a in ags],
        "jobs": [{"id": j.get("id"), "status": j.get("status"),
                  "coordinator": j.get("coordinator"), "agents": j.get("agents") or [],
                  "blocked_by": j.get("blocked_by") or [], "goal": j.get("goal")} for j in jbs],
        "graphs": graphs,
    }
```
and in `handle()` GET branch: `if path == "/api/orbit/constellation": return _json(handler, 200, _constellation())`.

- [ ] **Step 4:** re-run `python3 tests/v294_constellation.py` → endpoint checks PASS.

---

## Task 2 — Main app deep-link `?session=&node=`

**Files:** Modify `webui/index.html`.

- [ ] **Step 1:** in `ensureToken()` (reads `token`) also stash `session`/`node`:

```js
  try {
    const u = new URL(location.href);
    const qt = u.searchParams.get("token");
    if (qt) { TOKEN = qt; localStorage.setItem("sf_token", qt); }
    window._deepSession = u.searchParams.get("session") || null;
    window._deepNode = u.searchParams.get("node") || null;
  } catch (e) {}
```
- [ ] **Step 2:** at the end of `loadHistory()` (after the transcript is rebuilt), honour it:

```js
  // JAG-296: deep-link from Orbit — jump to the exact task section after replay.
  if (window._deepNode) { const _dn = window._deepNode; window._deepNode = null;
    setTimeout(() => { try { _scrollToNode(_dn); } catch (e) {} }, 60); }
```
- [ ] **Step 3:** where the initial session is chosen, prefer the deep param:

```js
  if (window._deepSession) { sessionId = window._deepSession; localStorage.setItem("sf_session", sessionId); window._deepSession = null; }
```
(The exact call site is the startup path that currently calls `selectSession(...)` with
`localStorage['sf_session']`; insert the override BEFORE it.)

- [ ] **Step 4:** run the v294 test → main deep-link checks PASS.

---

## Task 3 — Orbit floating Constellation window (non-modal)

**Files:** Modify `src2/orbit_beta/web/orbit.html`.

- [ ] **Step 1:** delete the `#tacModal` markup + `.modal` CSS + `TacticalView` class.
- [ ] **Step 2:** add the window markup (no backdrop) before `</main>`:

```html
<section class="cwin" id="constWin" hidden>
  <div class="cbar" id="constBar">
    <span class="dots">⠿</span><b>CONSTELLATION</b>
    <span class="spacer"></span>
    <button class="btn ghost mini" id="constAgent">AGENT</button>
    <button class="btn ghost mini" id="constAll">ALL</button>
    <button class="btn ghost mini" id="constMin">–</button>
    <button class="btn ghost mini" id="constClose">✕</button>
  </div>
  <div class="cbody" id="constBody">
    <svg class="csvg" id="constSvg" viewBox="0 0 1000 620"></svg>
    <div class="cdetail" id="constDetail">click a task for its chat extract</div>
  </div>
  <span class="cgrip" id="constGrip"></span>
</section>
```
- [ ] **Step 3:** CSS (floating, modeless):

```css
.cwin{position:fixed;left:140px;top:90px;width:760px;height:460px;background:var(--panel);
  border:1px solid #3a4a6e;border-radius:12px;box-shadow:0 24px 60px rgba(0,0,0,.6);
  display:flex;flex-direction:column;overflow:hidden;z-index:60}
.cwin[hidden]{display:none}
.cbar{display:flex;align-items:center;gap:7px;padding:6px 9px;border-bottom:1px solid var(--line);
  background:var(--panel2);cursor:move;user-select:none}
.cbar b{font-size:10px;letter-spacing:.14em;color:var(--ice)}
.cbar .dots{color:var(--dim);letter-spacing:2px}
.cbody{flex:1;position:relative;background:#060912;min-height:0}
.csvg{display:block;width:100%;height:100%}
.cdetail{padding:7px 11px;border-top:1px solid var(--line);font-size:11px;color:var(--dim)}
.cgrip{position:absolute;right:2px;bottom:2px;width:16px;height:16px;cursor:nwse-resize;
  background:linear-gradient(135deg,transparent 55%,var(--line) 55% 62%,transparent 62% 70%,var(--line) 70% 77%,transparent 77%)}
.cnode{cursor:pointer}
.cpop{position:absolute;max-width:320px;background:var(--panel2);border:1px solid var(--line);
  border-radius:9px;padding:9px 11px;font-size:11px;color:var(--txt);z-index:70;box-shadow:0 12px 30px rgba(0,0,0,.5)}
```

- [ ] **Step 4:** commit.

---

## Task 4 — Constellation render (AGENT + ALL) + interactions

**Files:** Modify `src2/orbit_beta/web/orbit.html`.

- [ ] **Step 1:** `Constellation` class — mount chrome (drag/resize/minimize/close/toggle),
  `load()` (fetch `/api/orbit/constellation`, cache), `open(agent)` (AGENT mode),
  `setMode(mode)`, `draw()` (SVG), `extract(node)` (popover from `/api/history`),
  `gotoTask(agent,nid)` / `gotoAgent(agent)` (deep-link, same tab).
- [ ] **Step 2:** cluster logic `byAgent(data)` = `{sid: nodes[]}`; job edges from
  `jobs[].blocked_by`; agent edges from `jobs[].agents`; org edges from `agents[].reports_to`.
- [ ] **Step 3:** wire: `OrgChartView(onPick)` dblclick → `gotoAgent`; single click → select;
  `JobsView` row dblclick → `gotoAgent(coordinator)`; job `⇢` shows members.
- [ ] **Step 4:** node interactions: hover tooltip; click → `extract`; dblclick → `gotoTask`.
- [ ] **Step 5:** deep-link helper builds `/?token=<t>&session=<sid>&node=<nid>` and sets
  `location.href` (same tab).

---

## Task 5 — Wire the battery + verify + commit

- [ ] **Step 1:** add `v294_constellation` to `tests/battery.sh` TESTS list.
- [ ] **Step 2:** `bash tests/battery.sh` → expect `=== battery: 59/59 GREEN ===`.
- [ ] **Step 3:** restart `systemctl --user restart sparkforge.service`; live-verify in the
  browser: non-modal window (page behind clickable), AGENT/ALL toggle, cluster per agent,
  click extract, dblclick → main at the exact task.
- [ ] **Step 4:** write `trash/handoff_296.md` + `trash/do_296.sh`; commit + push.

---

## Self-review
- Spec §4 → Task 1. Spec §5 → Tasks 3–4. Spec §6 → Task 2. Spec §7 → Tasks 1–2, 5. ✔
- No placeholders; names consistent (`_constellation`, `#constWin`, `constAgent/constAll`,
  `_deepSession/_deepNode`, `gotoTask/gotoAgent`).
