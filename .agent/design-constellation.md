# Design — Orbit "Constellation" window (JAG-296)

Status: approved (brainstorming, visual companion). Implementation plan:
`.agent/plan-constellation.md` (written next).

## 1. Goal
Turn the Orbit tactical modal into a single **floating, non-modal constellation
window** that shows task dependencies, and make Orbit a real launchpad into the
main app (deep-link to a session and to an exact task).

## 2. The object model (confirmed)
Three distinct object types, five relations:

| Prefix | Object | Notes |
|--------|--------|-------|
| `JN` | JOB | a goal given to a coordinator agent (+ team); edges `blocked_by` (job→job) |
| `AX` | AGENT | 1:1 with a session; edges `reports_to` (agent→agent, org chart) |
| `AX.TY` | TASK | a todo node inside agent X's session; edges `deps` (task→task, SAME agent) |

- A JOB does NOT contain tasks: it **assigns** agents; each agent works in its **own**
  task graph.
- A task's `AX` prefix is the agent that **owns** the session, not the job.
- The SAME agent (session) may be used by several jobs → its task list is **persistent
  and shared**. Therefore in the ALL view we cluster **per AGENT** (each agent once),
  with jobs drawn as pills/edges above.

## 3. Approaches considered
- **A1 (chosen)** one aggregate endpoint `GET /api/orbit/constellation` → UI stays simple.
- A2 client fetches existing endpoints (N+2 round-trips, merge in the client) — rejected.
- A3 a JS graph library (d3/cytoscape) — rejected: the project is dependency-free
  (vanilla JS + hand-rolled SVG, consistent with the existing `TacticalView`).

## 4. Backend
`src2/orbit_beta/api.py`, `GET /api/orbit/constellation` →
```json
{
  "agents": [{"id":"A3","session":"<sid>","name":"...","role":"...","reports_to":"A3","model":"..."}],
  "jobs":   [{"id":"J4","status":"running","coordinator":"A3","agents":["A3","A5"],
              "blocked_by":["J3"],"goal":"..."}],
  "graphs": {"<sid>": {"nodes":[{"id":"n1","label":"...","status":"done","deps":["n0"],
              "parent":null,"evidence":"...","reason":null}]}}
}
```
Reads `agents.REGISTRY.list()`, `jobs.REGISTRY.list()`, `taskgraph.load(sid)` for each
agent session. Read-only, cheap.

## 5. Orbit UI — the Constellation window
Replaces the blocking `#tacModal` with a **floating, non-modal** `#constWin`:
- No backdrop → the page behind stays interactive. `position:fixed`, high `z-index`.
- Titlebar = drag handle (pointer events); corner = resize; `–` minimize; `✕` close.
- Header: **AGENT / ALL** toggle + compact status legend.
- **AGENT mode**: the selected agent's task nodes (+ sub-tasks via `parent`) and `deps`
  edges. Opened by double-clicking an agent in the org chart or the jobs list.
- **ALL mode**: one **rectangle per AGENT** (each agent once); inside, its tasks; above,
  **JOB** pills with `blocked_by` job→job edges; dashed job→agent edges = "assigns".
- Shapes/colors: JOB = amber pill; AGENT = cyan box; TASK = circle colored by status
  (`done/doing/todo/blocked/superseded|cancelled`).
- Interactions:
  - hover a task → tooltip (label + status).
  - **click a task** → "chat extract" popover: label, status, the owning agent, the
    jobs that include that agent (if any), `evidence`/`reason`, plus the last chat lines
    for that node (from `/api/history` filtered by `m.node`) and an "open in main" link.
  - **double-click a task** → open the main app at the exact task: `/?token=..&session=<sid>&node=<nid>`.
  - **double-click an agent** (org chart / jobs) → open the main app at that session:
    `/?token=..&session=<sid>`. Same tab.

## 6. Main app deep-link
The main WebUI currently honours only `?token=`. Add:
- `session` query param → set `sessionId` (overrides localStorage) and select it.
- `node` query param → after `loadHistory()` finishes, call `_scrollToNode(<nid>)`.
Applied **in the same tab** (Orbit → main).

## 7. Tests
`tests/v294_constellation.py`:
- the aggregate endpoint exists and returns the `agents`/`jobs`/`graphs` shape;
- Orbit has a NON-modal floating window (no backdrop element), the AGENT/ALL toggle,
  and clusters per agent (no per-job task duplication);
- the main WebUI reads `session` + `node` query params and calls `_scrollToNode`.
Keep the `$()`-id guard from v291/v293.

## 8. Out of scope
- Editing tasks from the constellation (read-only view + navigation only).
- Skill/tool tailoring (dropped earlier by the user).
- Any third-party graph library.
