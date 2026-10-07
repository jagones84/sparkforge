# SparkForge Architecture

*v1.0.0 — 2026-10-07. The code is the source of truth; this is the map.*

SparkForge is a **stdlib-only Python agent harness**. It drives one LLM with disciplined
context and a real tool loop, then composes that harness into **meta-agents organised in
teams**. It serves a single-file WebUI, a mission-control deck (Orbit), a CLI and a
mobile-ready HTTP API — all from one process on `:8790`.

```
        WebUI (webui/index.html)   Orbit (src2/orbit_beta)   CLI (forge.py)   Mobile
              │  SSE  ▲  │ HTTP          │  SSE ▲                │ SSE ▲         │
              ▼       │  ▼               ▼      │                ▼     │         ▼
        ┌───────────────────────────────────────────────────────────────────────────┐
        │                         server.py  (:8790)                                  │
        │   chat (stream)   │   agent loop   │   jobs/orchestration   │   teams         │
        │   ────────────────┼────────────────┼────────────────────────┼──────────────   │
        │   taskgraph       │   tools+registry│  providers/routing    │   memory         │
        │   keepgoing loop  │   approvals    │   sandbox             │   skills         │
        │   ────────────────┴────────────────┴────────────────────────┴──────────────   │
        │   EVENT BUS  publish() → /api/feed   (SSE, monotonic ids + replay backlog)     │
        │   STORES     data/… (atomic JSON + SQLite events.db)                           │
        └───────────────────────────────────┬───────────────────────────────────────────┘
                                            │ OpenAI-compatible, stream
                        ┌───────────────────┼───────────────────────┐
                        ▼                   ▼                       ▼
                 llama.cpp router      vLLM router            cloud providers
                 (DGX / Windows)       (local)      OpenRouter · DeepSeek · OpenAI · Anthropic · Google
```

## The object model (five levels)

The whole product is one hierarchy, from a business goal to a checklist item:

```
Team  TN      a symbol + a roster (owns its members)
 └ Job     JN      a goal given to a coordinator
    └ Subjob JN.j   one assignment, bound to ONE agent, with dependencies
       └ Agent  AX   IS a session — its own harness, tools, skills, memory, chat
          └ Todo AX.nY  a step, closable only with evidence
```

Membership is owned by the **team** (`teams.py`); `agents.py` only reads it, so the two
stores can never drift. Todo ids are `AX.nY` — the `T` namespace belongs to teams.

## A team job, end to end

1. `POST /api/jobs {goal, assignee}` — the assignee is the coordinator; its team is the
   assignee plus its direct reports.
2. `POST /api/jobs/<id>/dispatch` runs the job in the background:
   - **PLAN turn** — the coordinator decomposes the goal. This turn is **plan-only and
     read-only**: a tight tool budget, no completion loop, and only `fs.read` / `skills`
     / `memory` / `self` may run. It records the plan and stops; it cannot do the work.
   - `parse_plan_deps` reads the declared `(after AX)` edges; `plan_subjobs` turns the
     plan into numbered subjobs with deps; the delegation is written into **both** chats.
   - **Worker waves** — `waves()` topologically orders the subjobs; each worker runs a
     full harness turn and reports with `STATUS: DONE` / `STATUS: BLOCKED: <why>`.
   - **SYNTHESIS turn** — the coordinator receives the team report (unfinished subjobs
     are explicitly flagged) and produces the final deliverable.
3. Bounded retry: a BLOCKED subjob is retried a bounded number of times, then marked
   **failed**; the job becomes **partial** and the failure is surfaced, never hidden.

## Request / turn lifecycle (one chat turn)

`assemble_turn` builds the exact prompt (system sections + compacted transcript +
message + tool registry + skills index); the provider is called over an
OpenAI-compatible stream; the model may answer **or** emit a harness action
(`tool`, `write_todos`, `update_todos`, `replan_todos`, `subagent`). Tool calls go
through the **approval gate** and the **sandbox**; observations are fed back; the
**completion loop** (`keepgoing.py`) decides whether to continue, with typed stops
(`goal_reached · no_progress · budget · blocked`). Every step is published to the event
bus and persisted, so a reload rebuilds the transcript and the task graph.

## Components (`src/sparkforge/`)

| Area | Modules |
|---|---|
| Core server | `server.py`, `api_v02.py`, `forge.py` |
| Agents & orchestration | `agents.py`, `jobs.py`, `orchestration.py`, `teams.py`, `subagent.py`, `swarm.py` |
| Planning / execution | `taskgraph.py`, `keepgoing.py`, `difficulty.py`, `bestofn.py`, `prm.py`, `heldout.py`, `verify.py` |
| Tools & safety | `tools.py`, `registry.py`, `approvals.py`, `sandbox.py`, `hooks.py`, `edits.py`, `term.py` |
| Models | `providers.py`, `routing.py`, `context_engine.py`, `prompt.py`, `runmetrics.py`, `otel_tracing.py` |
| Knowledge | `memory.py`, `skills.py`, `rules.py`, `roles.py`, `checkpoints.py` |
| Interop | `mcp.py`, `mcp_client.py`, `mcp_server.py`, `acp.py` |
| Cross-cutting | `osutil.py` (all platform specifics), `paths.py`, `routines.py`, `meta.py`, `selfevolve.py`, `improve.py` |

## Data stores (`data/`, gitignored)

`sessions/` (transcripts) · `graphs/` (per-session task graphs) · `runs/` (traces +
token/cost) · `edits/` (diff journal) · `memory/` · `checkpoints/` · `offload/` (oversized
observations spilled to files) · `agents.json` · `teams.json` · `jobs.json` ·
`events.db` (durable SSE feed). Writes are atomic (`tmp` + `os.replace`).

## Safety model

Allowlist registry (a tool must be `enabled` in `config/tools.yaml`) → per-action
classification (`auto | required | denied | disabled`) → approval queue for anything
world-touching → **real sandbox** (`docker --network none --read-only --cap-drop ALL`,
or `bwrap` / `nsjail`) so the agent never touches the host. Hard-denied patterns
(`rm -rf /`, `mkfs`, `git push`, …) are blocked even with approval.

## Interfaces

- **WebUI** `webui/index.html` — one file, no build step; chat + CoT, task graph, feed.
- **Orbit** `src2/orbit_beta/` — beta mission-control deck at `/orbit`: org chart,
  constellation, job create/dispatch, team selector, model policy.
- **CLI** `forge.py` — chat, agent runs, tasks, models, MCP.
- **HTTP API** — see [CLI.md](CLI.md); optional bearer auth (`--token`).

## Entry points

The repo-root `server.py`, `forge.py`, `mcp_server.py` are **launcher shims** (they put
`src/` on `sys.path` and call the package `main()`). Real code lives in
`src/sparkforge/`; the modules use relative imports and cannot run standalone.
