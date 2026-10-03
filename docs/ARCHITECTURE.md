# SparkForge Architecture

*Version 0.2 — 2026-09-29*

```
┌────────────────────────────────────────────────────────────────────┐
│                         SPARKFORGE (dgx)                            │
│                                                                     │
│  WebUI (webui/index.html)   CLI (forge.py)   Mobile (SparkPulse /   │
│  EventSource + fetch        SSE consumer     future Command tab)     │
│        │  SSE  ▲   │            │  SSE ▲                             │
│        ▼      │   │ HTTP        ▼     │                             │
│  ┌──────────────────────────────────────────┐                       │
│  │            server.py  (:8790)             │                       │
│  │  ┌──────────┐ ┌──────────┐ ┌───────────┐ │                       │
│  │  │ chat     │ │ planner  │ │ agent     │ │   reason → act →      │
│  │  │ (stream) │ │ (JSON    │ │ loop      │ │   observe, sandboxed  │
│  │  │          │ │  steps)  │ │ (thought/ │ │   to harness stores)  │
│  │  └────┬─────┘ └────┬─────┘ │ action/   │ │                       │
│  │       │            │       │  observe) │ │                       │
│  │  ┌────▼────────────▼───────▼─────────┐ │ │                       │
│  │  │  EVENT BUS  publish() → /api/feed │ │ │  SSE, ids + backlog   │
│  │  └────┬──────────────────────────────┘ │ │                       │
│  │  ┌────▼──────────────────────────────┐ │ │                       │
│  │  │ STORES (data/, atomic JSON)       │ │ │                       │
│  │  │ plan.json · tasks.json · sessions/│ │ │                       │
│  │  └───────────────────────────────────┘ │ │                       │
│  └────────────────┬───────────────────────┘                       │
└───────────────────┼───────────────────────────────────────────────┘
                    │ OpenAI-compatible, stream
                    ▼
        llama.cpp router :8080 (local-dgx models)
        deepseek-v4-flash · glm-5.3-flash-iq2 · … (262k ctx presets)
                    ▲
        telemetry: SparkPulse server :8787 (JAG-16, unchanged)
```

## Components

### server.py — harness core (stdlib-only Python)
- **Chat**: `/api/chat` (one-shot) and `/api/chat/stream` (SSE). Streams `reasoning_content` and inline `<think></think>` as a separate `think` channel — CoT is visible, never discarded.
- **Planner**: `/api/plan/generate {goal}` — model returns a JSON array of `{title, detail}` steps (robust extraction: direct parse → brace-slice fallback), stored with per-step `done` toggles.
- **Agent loop**: `/api/agent/run {goal, max_steps}` — per iteration the model sees goal + full harness state and emits one JSON action from `{plan_step, complete_plan_step, add_task, complete_task, note, finish}`. The harness applies it and feeds the observation back. **Structural sandboxing: the loop's only writable surface is the harness's own stores — no shell, no filesystem access, by construction.**
- **Event bus**: every mutation and chat delta is `publish()`ed with a monotonic id into a bounded ring (800 events) and fanned out to live SSE subscribers; `/api/feed?since=<id>` replays the backlog for reconnecting clients (mobile-safe).
- **Stores**: `data/plan.json`, `data/tasks.json`, `data/sessions/<id>.json` — atomic writes (tmp + `os.replace`), gitignored.
- **Auth**: optional `--token` (bearer). Default binds `127.0.0.1`; `--host 0.0.0.0` exposes the command API to the phone over Tailscale (same trust model as SparkPulse :8787).

### forge.py — CLI
`chat` (with `--stream`), `agent`, `plan show|generate|toggle`, `tasks ls|add|done|set`, `status`, `models`, `feed`. Talks HTTP to the server — the server is the single harness runtime (CLI is a thin client, like Claude Code vs. its backend loop).

### webui/index.html — frontier UI
Dark glassmorphism, gradient identity, live thinking timeline (collapsible), streaming chat, PLAN/TASKS panels with click-to-advance, live event feed rail, model/server pills. Mobile-responsive (sidebar collapses). No build step, no dependencies — served by the server itself.

## API contract (mobile)

Same conventions as SparkPulse: JSON over HTTP on the Tailscale IP. New capability vs SparkPulse:
- `GET /api/feed` (SSE): live harness events — the "loopback feed"
- `GET /api/chat/stream?session&message` (SSE): streaming chat with `chat.delta` events (`channel: think|answer`)
- `POST /api/agent/run` / `GET /api/agent/run?goal=`: agent loop (JSON result or SSE trace)
- `GET/POST /api/plan`, `POST /api/plan/generate`, `POST /api/plan/toggle`
- `GET/POST/PATCH /api/tasks` (status machine: `todo → doing → done`)
- `GET /api/status` (roster + telemetry summary), `GET /api/sessions`, `GET /api/history?session=`

## Honest maturity statement (v0.1)
Implemented and tested: chat (stream + one-shot), visible CoT, planner, tasks/plan stores, agent loop (safe actions only), SSE feed with backlog, WebUI, CLI, optional bearer auth, `--host` exposure.

Not yet (roadmap in PLAN.md): shell/file tools with approval gates, MCP client, subagent delegation, speech I/O, WebUI auth flow for `--token` mode (server enforces it; UI does not prompt yet), persistent vector memory, eval harness.

---

# v0.2 — safe execution surface

```
        agent loop (thought → action → observation)
                │  action = {"tool":"shell","args":{…}}
                ▼
   ┌──────────────────────────┐    registry.classify(tool,args)
   │  registry.py             │──▶ auto │ required │ denied │ disabled
   │  config/tools.yaml       │
   └───────────┬──────────────┘
               │ required
               ▼
   ┌──────────────────────────┐   pending  ┌──────────────────────────┐
   │ approvals.py             │───────────▶│ /api/approvals  (HITL)   │
   │ auto / pending / decided │◀───────────│ WebUI · phone · MCP · CLI│
   └───────────┬──────────────┘  approve   └──────────────────────────┘
               │ / deny / expire
               ▼
   ┌──────────────────────────┐   docker --network none --read-only
   │ tools.py → sandbox.py    │──▶ bwrap --unshare-all (fallback)
   │ shell / fs / git / http  │   nsjail (fallback)
   └───────────┬──────────────┘   per-run /work scratch dir
               ▼
        observation  ──▶ run trace + feed (tool.call / tool.result)

   api_v02.py  — owns the v0.2 HTTP surface; server.py delegates via
                 `if api_v02.handle(self, method, path, qs, body): return`
   mcp.py      — MCP JSON-RPC 2.0 logic (transport-agnostic)
   mcp_server.py — stdio transport → HttpApi → running server
   LocalApi    — in-process transport for `POST /mcp`
```

## Components (v0.2)

- **`config/tools.yaml` + `registry.py`** — the declarative registry: per-tool JSON schema,
  `enabled` (allowlist), `approval` (`auto|required|denied`), `auto_approve` regexes and hard
  `deny` regexes. `classify()` is the single decision point; `resolve_path()` keeps `fs.*`
  inside its allowed roots. Sandbox settings (backend, image, limits, network, workspace) live
  here too.
- **`approvals.py`** — durable approval queue (`data/approvals-v02.json`) with a
  `threading.Event` wake-up so a blocked run resumes the instant a human decides. Auto-approved
  actions are recorded too ("no decision" is never silent).
- **`sandbox.py`** — probes `docker` → `bwrap` → `nsjail` once and caches the result; `run()`
  executes a command with a timeout, a per-run scratch dir and no host network. `backend: none`
  is opt-in only and reports `sandboxed: false`.
- **`tools.py`** — the six tool implementations + `observation()` rendering. Policy is *not*
  enforced here; it only runs already-permitted actions.
- **`api_v02.py`** — HITL run registry (`pause`/`resume`/`abort` via checkpoints inside the loop
  and inside `approvals.wait`), the tool-enabled agent loop (`agent_run_v2`, with a `script`
  mode for reproducible runs), the MCP `LocalApi`, and the HTTP glue.
- **`mcp.py` / `mcp_server.py`** — MCP server exposing `sparkforge_status`, `sparkforge_chat`,
  `sparkforge_plan`, `sparkforge_tasks`, `sparkforge_agent_run`, `sparkforge_feed`,
  `sparkforge_tools`, `sparkforge_approvals`. Registration snippet in the README.

## Honest maturity statement (v0.2)

Implemented and verified by `tests/v02_acceptance.py` (8/8, raw evidence in
[docs/evidence/V02-EVIDENCE.md](evidence/V02-EVIDENCE.md)): Docker sandbox with blocked egress; registry +
allowlist; hard-deny; an agent run that executes a real shell command in the sandbox with a
recorded human approval and the output returned as observation; pause/resume/abort; MCP over
stdio and HTTP.

Known limits: `fs.*` and `git` run host-side inside declared roots (only `shell` is
containerised); `http`/`browser` need the network so they are not containerised and are
restricted to a host allowlist; `browser` is a lightweight HTML→text fetcher, not a headless
browser, and ships disabled. `bubblewrap` cannot be used on this host because Ubuntu's
`apparmor_restrict_unprivileged_userns=1` blocks unprivileged user namespaces (the probe
reports this).
