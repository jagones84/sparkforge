# SparkForge Architecture

*Version 0.1 — 2026-09-28*

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
