# Design — SparkForge Agents & Jobs (orchestration v1)

Status: approved (user delegated scope; "scegli tu", "simile a Paperclip ma semplificata").
Iteration: JAG-287. Date: 2026-10-04.

## Goal

Turn SparkForge from "one chat at a time" into a **single harness where agents are
sessions**: async, parallelizable, and optionally organized into an org chart that
runs **jobs** — WITHOUT becoming a second meta-harness. We want a simplified,
native version of Paperclip's model, not a copy.

## Domain model (five objects, five levels)

> **Revision (JAG-324)** — the model gained the **Subjob** level. **Revision
> (JAG-339)** — it gained the **Team** level on top, and the todo id became `AX.nY`
> (`T` is now the TEAM namespace). It is a strict containment hierarchy and the
> links between levels MUST stay coherent everywhere in the codebase (this is a
> *fundamental* structural finding, not a UI detail):
>
>     Team TN  ──▶  Job JN  ──▶  Subjob JN.j  ──▶  Agent AX (= a session)  ──▶  Todo AX.nY

| Object | Letter | Is | Lives |
|---|---|---|---|
| **Team** | `TN` | a named group of agents (`T1`, `T2`, …) with a symbol, a colour and an organigram; an agent may be in SEVERAL teams | `data/teams.json` |
| **Job** | `JN` | the top goal; orchestrates ONE OR MANY agents, with a coordinator and dependencies | `data/jobs.json` |
| **Subjob** | `JN.j` | one tracked piece of the job, bound to ONE agent, with its own deps (a DAG) and status | `job["subjobs"]` in `data/jobs.json` |
| **Agent** | `AX` | a session, with all harness powers (tools, todos, workspace); it can embrace MANY subjobs and belong to MANY teams | `data/sessions/<sid>.json` + a designation record |
| **Todo** | `AX.nY` | a step of an agent's task list | the agent's task graph |

**Team membership is owned by the TEAM** (`team["members"]`, a list of agent ids);
`agents.py` only READS it (`AgentRegistry.teams_for`), so the two stores cannot drift.
`scripts/seed_teams.py` materialises 3 diversified teams (with real organigrams) from
the local agency-agents clone.

**The two invariants that keep the levels related:**

1. **A Todo carries BOTH `jid` and `subjob`.** Every node stores its job (`JN`) and
   the subjob (`JN.j`) it was produced for: `taskgraph.add_node` stamps both from
   the graph's current tags and `chat_stream_gen` sets the per-turn tags. A subjob
   therefore *embraces the subset* of its agent's todos tagged with its id
   (`JobRegistry.subjob_todos`).
2. **Subjobs form a DAG.** `JN.j` depends on the subjobs of the agents it waits on
   (`deps`, mirroring the job's agent-level `deps`), so subjob order mirrors the
   dependency waves — the same idea as todo deps, one level higher. The coordinator
   **DECLARES** the order: its decomposition ends a bullet with `(after AX)` when
   that teammate must wait, and the runner unions those declarations with the job's
   own `deps` (`jobs.parse_plan_deps` / `merge_deps`) before scheduling — so ordered
   work (coder 2 after coder 1) is ENFORCED, never run in parallel.

Naming change: the old session id `JX` is renamed **`AX`** (agent). The letter **`J`
is reserved for Jobs** and **`T` for Teams**; a todo is **`AX.nY`** (node id `nY`).
`X`/`N` are stable, allocated once and persisted.

The **constellation maps all five levels** (Team → Job → Subjob → Agent → Todo):
Orbit renders the subjob lane between jobs and agent clusters, and a team selector
scopes every panel; it never invents a level (`src2/orbit_beta/api.py::_constellation`,
`_subjobs_of`).

## Designated agents (persistent, remembered by the GUI)

Most sessions are ad-hoc ("apri una sessione a caso per farti i cazzi tuoi"). Only
sessions the user **designates** are org agents:

- an org agent has: `name`, `role`, `reports_to` (another `AX` or null), `model`,
  `workspace`, `created`.
- the UI shows a **badge** (⬢ agent) on org-agent sessions in the roster and in the
  chat header, so they are recognizable at a glance.
- **delete is guarded**: deleting an org agent requires an explicit confirm; it is
  refused while the agent has reports or is part of a running job.
- ad-hoc sessions behave exactly as today (no badge, normal delete).

Storage: `data/agents.json` = `{"agents": {session_id: {...}}, "seq": N}`.

## Jobs

A Job = `{id: "JN", goal, coordinator: "AX", agents: ["AX", ...], deps: {AX: [AX,...]},
mode: "coordinator"|"fanout", status, created}`.

- **deps** = a DAG: "who first, who after". `reports_to` gives the org tree; `deps`
  gives the execution order for a job.
- **mode coordinator** (default): the coordinator agent receives the goal, decomposes
  it, and each worker agent runs its slice; the coordinator aggregates and reports.
- **mode fanout**: every agent gets the same goal independently, results collected.

Execution reuses the existing per-session turn machinery (`chat_stream_gen`), so each
agent turn is a normal, persisted turn with its own task list. Dependencies are honored
by a small scheduler inside the job runner.

Storage: `data/jobs.json` = `{"jobs": {id: {...}}, "seq": N}`.

### Worker outcome contract (JAG-337)

A delegated subjob is never "assumed done". Every worker ends its report with an
explicit status line — `STATUS: DONE`, `STATUS: BLOCKED: <why>` or `STATUS: FAILED:
<why>` (`jobs.parse_status`). A missing status is DONE **only** when the worker left no
OPEN plan step (`jobs.open_steps`); otherwise it counts as BLOCKED. A non-DONE attempt
is RETRIED up to `SPARKFORGE_JOB_RETRIES` (default `1`) extra times with a "Resume
subjob" reinject. If it still cannot finish:

- the subjob is marked `failed` (NEVER `done`) and the run `failed` with the reason;
- `_log_escalation` writes a `handoff` inject into BOTH chats — the worker's ("returning
  subjob …") and the coordinator's ("… could not finish … — BACK TO YOU");
- the coordinator's synthesis message lists the UNFINISHED SUBJOBS;
- the job record carries `failed_subjobs` and status `partial`.

This is the Paperclip rule "never sit silently on blocked work": the ball being passed
back to the master is always visible and attributable.

## Teams (JAG-339)

A Team (`TN`) is a real group of agents — not a display label. `src/sparkforge/teams.py`
(`TeamRegistry`) owns `data/teams.json`; the API surface is `/api/teams` (GET list,
POST create), `/api/teams/<id>` (GET detail, POST update, DELETE), and
`/api/teams/<id>/members` (POST `{session|agent, action}`). Agents expose `teams`
(read-only, from the team store) on `/api/agents` and `/api/agents/tree`.

Orbit: a header **team selector** scopes the Agents table, the Org chart, the Job list
and the Constellation (`/api/orbit/constellation?team=TN`); `ALL` = everything. The
main app tags each session row with its team symbol(s). Multiple teams per agent are
supported (`agent.teams = [TN, …]`).

**Model policy (JAG-343).** A team may use at most ONE LOCAL model per machine
(`dgx`/`win`) — otherwise every agent defaults to the same local model on one GPU.
`TeamRegistry.assign_models` sends the LEADS (an agent someone reports to, or a team
root) to the strongest cheap cloud and everyone else to the cheap cloud, keeping at
most one local per machine among the non-leads. Applied via `POST /api/teams/<id>/models`
(Orbit "model policy" button) or `scripts/seed_teams.py --models`; the agent-model setter
is guarded (`local_conflict`) so a 2nd local on a machine within a team is refused.
Defaults are overridable: `SPARKFORGE_TEAM_LEAD_MODEL`, `SPARKFORGE_TEAM_MEMBER_MODEL`,
`SPARKFORGE_TEAM_LOCAL_SLOTS`.

## Concurrency (verified facts, JAG-287 investigation)

- HTTP server is `ThreadingHTTPServer`; turns serialize **per session** (`_turn_lock`),
  not globally → two agents run truly in parallel.
- Global locks (sqlite `_db_lock`, feed lock, `GRAPH_LOCK`, config cache, MCP
  per-connection, single embedder) are brief metadata sections, not turn mutexes.
- **The one real cross-agent constraint is the local model router**: two local models
  on the SAME GPU thrash VRAM. Policy: **one heavy local model per GPU**; the rest of
  the team uses cheap cloud models (OpenRouter). Different GPUs (dgx vs win) are fine.
  The job runner warns (and will serialize warm-up) when two agents on the same GPU
  disagree on the local model.
- Fixed a real intra-session race: `taskgraph._write_json` used a fixed `.tmp`
  (now a unique temp, mirroring JAG-201).

## Where the code lives

- **Native model** (must be visible to the main GUI): `src/sparkforge/agents.py`
  (`AgentRegistry`) and `src/sparkforge/jobs.py` (`JobRegistry` + runner). Small,
  object-oriented, no new framework.
- **Orbit GUI** (the orchestration deck): stays the detachable beta in `src2/orbit_beta`
  — board, org chart, jobs, and the restored orbital theme + Tactical Task Graph.
- Main GUI reads the agent registry through a small endpoint to render the badge and
  to guard delete; if the beta is removed, the badge simply disappears.

## API

- `GET /api/agents` · `POST /api/agents` (designate) · `DELETE /api/agents/<sid>`
  (guarded) · `GET /api/agents/tree`
- `GET /api/jobs` · `POST /api/jobs` (create) · `POST /api/jobs/<id>/dispatch` ·
  `GET /api/jobs/<id>` (JAG-324: enriched by `JobRegistry.detail` with each subjob's
  todo membership)

## UI

- **Main chat**: ⬢ badge on org-agent sessions; guarded delete; `AX` ids everywhere.
- **Orbit**: restore the orbital theme + **Tactical Task Graph** (nodes = todos with
  `AX.TY` ids and dependency links); add an **Org chart** view (reports_to tree) and a
  **Jobs** board (create goal + coordinator + agents + deps, dispatch, live status).

> **Revision (JAG-293)** — the Orbit UI was simplified: 5 panels only (Agents table,
> graphical Org chart, Job = goal + assignee, Routines, Feed). The Board, Tactical
> Task Graph, Command, Team models, Model Bay and Decision queue were removed. See
> `design-orbit-simple.md`.

## Iteration plan

- **A — foundation (this iteration)**: copy cleanup, `AX` rename, deck link → `/orbit`,
  taskgraph `.tmp` fix, spec. *Done here.*
- **B — agents & jobs**: `agents.py` + `jobs.py` + API; main-GUI badge + delete guard.
- **C — Orbit GUI**: theme + tactical graph + org chart + jobs board.
- **D — Paperclip extras**: per-agent budget, heartbeats/routines, decision queue.

## Testing

Deterministic unit tests per module (no live model): id allocation + stability,
designation + tree, delete guard, job DAG ordering, attention reuse. Battery stays green.
Live checks on the DGX for the API + browser render of Orbit.
