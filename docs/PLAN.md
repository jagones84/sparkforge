# SparkForge Plan

*Living document — mirrors the in-app PLAN store (`GET /api/plan`). Updated 2026-09-29.*

## Goal
A state-of-the-art, mobile-commandable agent harness on the DGX Spark: local LLM (router :8080) inside a frontier-style harness with visible reasoning, planning, task execution, a live loopback feed, WebUI, CLI — and, from v0.2, **real tools executed in a real sandbox behind approval gates**.

## Done — v0.1 "Genesis" (2026-09-28)

- ✅ Frontier-harness research survey with 2026 citations (docs/RESEARCH-frontier-harnesses-2026.md)
- ✅ Harness server: chat (one-shot + SSE stream) with visible CoT (`reasoning_content` + `<think>`)
- ✅ Planner module: goal → JSON strategy steps (model-generated, robust extraction)
- ✅ TASKS board: status machine `todo → doing → done` + remaining bullets
- ✅ Agent loop: `thought → action → observation`, structurally sandboxed to harness stores
- ✅ Loopback feed: SSE `/api/feed`, monotonic ids, backlog replay (`?since=`)
- ✅ Frontier WebUI: dark glass UI, thinking timeline, plan/tasks panels, live feed rail
- ✅ CLI `forge.py`: chat/agent/plan/tasks/status/models/feed
- ✅ Mobile API: `--host 0.0.0.0` for Tailscale exposure, optional bearer token
- ✅ SparkPulse preserved & backed up: `/home/jagones/Backups/sparkpulse-backup-20260928-231607.tar.gz` (38 MB, 1501 files)

## Done — v0.2 "safe execution + interop" (2026-09-29)

Deliverable from `docs/specs/2026-09-29-frontier-harness-design.md` §3 (v0.2).
Everything below is verified by `tests/v02_acceptance.py` (8/8 checks) — see
[docs/V02-EVIDENCE.md](V02-EVIDENCE.md) for the raw command+output evidence.
Re-verified independently on 2026-09-29 by a by-hand run (agent run `run_684e5723`
→ approval `e65e4b7e90` → sandboxed shell `exit=0`, `NET_BLOCKED`; MCP stdio session
`initialize`/`tools/list`/`tools/call` → reply) — same evidence file, §"Independent
re-verification".

- ✅ **Tool registry** — `config/tools.yaml` declares `shell`, `fs.read`, `fs.write`, `git`, `http`, `browser` with a JSON schema, `enabled` allowlist, `approval` policy, per-tool `auto_approve` regexes and hard `deny` regexes (`registry.py`, `tools.py`)
- ✅ **Approval gates** — `/api/approvals` queue: every action is recorded (auto-approved, pending, approved, denied, expired); `/api/tools/call` and the agent loop both go through it; the tool result becomes the agent's `observation`
- ✅ **Real sandbox** — `sandbox.py` auto-detects `docker` → `bwrap` → `nsjail`; on this host the Docker backend is used: `--network none --read-only --cap-drop ALL --user 65534 --tmpfs /tmp`, one writable `/work` scratch dir, per-run. Network egress verified blocked
- ✅ **HITL** — `/api/agent/control` `{runId, action: pause|resume|abort}`; a run pauses while waiting for an approval and can be aborted mid-flight; `GET /api/agent/runs[/<id>]` exposes live status + trace
- ✅ **MCP server mode** — `mcp_server.py` (stdio JSON-RPC 2.0) and `POST /mcp` (HTTP) expose `sparkforge_{status,chat,plan,tasks,agent_run,feed,tools,approvals}` so Paperclip can open an MCP session and pilot the harness
- ✅ **WebUI + CLI** — approvals panel with approve/deny, sandbox pill, live tool events; `forge.py tools|approvals|runs|control|sandbox|mcp`

## Done — Sperimentale (frontiera "non ancora rilasciata") — 2026-09-29

Implemented per `docs/specs/2026-09-29-frontier-harness-design.md` §Sperimentale.
See evidence in `tests/v02_acceptance.py` (meta, acp, swarm are tested through MCP dispatch).

- ✅ **Meta-harness self-improvement** (`meta.py`): outer-loop campiona varianti della
  harness (modello, prompt stile, approval policy, sandbox, temperature, max_steps, ecc.),
  le valuta su un task eval standard, e calcola la frontiera di Pareto (qualità vs costo).
  Endpoint: `GET/POST /api/meta`, MCP: `sparkforge_meta`.
- ✅ **ACP (Agent Client Protocol)** (`acp.py`): SparkForge espone un endpoint ACP
  JSON-RPC 2.0 (`POST /api/acp`) per essere pilotato da altri harness, e un client
  ACP per connettersi e pilotare altri agenti (`POST /api/acp/connect`).
  MCP: `sparkforge_acp`.
- ✅ **Swarm / blackboard** (`swarm.py`): blackboard condiviso (append-only, versionato,
  con SSE watcher `GET /api/blackboard/watch`). Coordinator agent che decomponi il
  goal, spawna worker via subagent, e sintetizza i risultati.
  Endpoint: `GET/POST /api/blackboard`, `POST /api/swarm/run`.
  MCP: `sparkforge_blackboard`, `sparkforge_swarm`.
- ✅ **Persistent memory** (`memory.py`): scrittura append-only in markdown, indice
  vettoriale numpy per ricerca semantica (sentence-transformers, endpoint embedding locale,
  o bag-of-words fallback). Endpoint: `GET/POST /api/memory`. MCP: `sparkforge_memory`.
- ✅ **MCP client** (`mcp_client.py`): connessione stdio o HTTP a server MCP esterni,
  discovery tool via tools/list, namespace collision-free (`clientname__toolname`).
  Config: `config/mcp_clients.yaml`. Endpoint: `GET /api/mcp/clients`.
- ✅ **Subagent delegation** (`subagent.py`): spawn `agent_run_v2` in background thread,
  raccogli risultato con `collect()`. Azione agent: `{"action":"subagent","goal":"..."}`.
  Endpoint: `POST /api/subagent/spawn`, `POST /api/subagent/collect`.
  MCP: `sparkforge_subagent`.

## Done — v0.4 "ops + mobile + eval" (2026-09-29)

Deliverable from `docs/specs/2026-09-29-frontier-harness-design.md` §3 (v0.4).
Verified by `tests/v04_acceptance.py` — raw report in `data/v04-acceptance.json`
(generated against the live systemd service on `127.0.0.1:8790`).

- ✅ **Durable event store (SQLite)** — every harness event lands in `data/events.db`
  (`events` table, monotonic ids); the in-memory buffer is only a cache, so
  backlog replay works after restart; SSE feed reconnects with `?since=<id>`
  and replays every event after it
- ✅ **OpenTelemetry tracing** — `otel_tracing.py`: when the OTel SDK is installed,
  each run records genuine spans (shared `trace_id`, span hierarchy, nanosecond
  timestamps) exported synchronously into the `runs` table; without the SDK a
  local span list is kept. `GET /api/runs/<id>/trace` serves spans + token/cost
- ✅ **Token/cost accounting** — every chat/agent run tracks tokens in/out and
  estimated USD cost (local models price 0 by default; `MODEL_PRICES` table)
- ✅ **systemd always-on** — `deploy/sparkforge.service` (user unit, `Restart=always`,
  token via `~/.config/sparkforge/env` EnvironmentFile); API refuses
  unauthenticated requests (401) when started with `--token`
- ✅ **WebUI auth flow** — token prompt persisted to `localStorage`, `?token=` on
  every EventSource/API call
- ✅ **Voice** — `POST /api/voice/stt` (raw `audio/wav` upload or path) via whisper
  (whisper.cpp or openai-whisper CLI auto-detected), `POST /api/voice/tts` via
  sherpa-onnx VITS (+ `tokens.txt`/`espeak-ng-data` config), `GET /api/voice/audio/<file>`
  serves the wav back, `GET /api/voice/status` reports backend availability
- ✅ **Eval harness** — `eval/gold_tasks.json` gold set; `POST /api/eval/run` runs
  the agent loop per task and scores it (expected actions present + in order as a
  subsequence, finished, summary non-empty, no stall → score in [0,1]); results
  persisted under `eval/results/eval-<ts>.json`
- ✅ **SparkForge-side mobile contract** — SSE endpoints (`/api/chat/stream`, `/api/feed?since=`)
  + approvals queue + `run_id` events on chat streams, so the phone can stream
  live (SparkPulse app-side SSE consumption tracked separately, see Remaining)

## Done — v0.3 "capacità agente + memoria" (2026-09-29)

Deliverable from `docs/specs/2026-09-29-frontier-harness-design.md` §3 (v0.3).
Verified by `tests/v03_acceptance.py` (7/7 checks) — raw report in
`data/v03-acceptance.json`; the v0.2 suite still passes 8/8 on the same build
(regression evidence).

- ✅ **MCP client** (`mcp_client.py`): connessione stdio o HTTP a server MCP esterni,
  discovery tool via tools/list, namespace collision-free (`clientname__toolname`).
  Config: `config/mcp_clients.yaml`. Endpoint: `GET /api/mcp/clients`. (shipped with the
  Sperimentale wave, re-verified by the v0.2 stdio MCP acceptance check)
- ✅ **Subagent delegation** (`subagent.py`): spawn `agent_run_v2` in background thread,
  raccogli risultato con `collect()`. Azione agent: `{"action":"subagent","goal":"..."}`.
  Endpoint: `POST /api/subagent/spawn`, `POST /api/subagent/collect`. (idem)
- ✅ **Checkpoint / resume / rollback** (`checkpoints.py`): snapshot atomico di
  plan + tasks + transcript di sessione in `data/checkpoints/`; idempotenza via
  `idempotency_key` (stessa chiave → stesso checkpoint, nessun duplicato) e
  rollback ripetibile che converge allo stesso stato; ogni run agente crea un
  auto-checkpoint (`agent-run:<run_id>`). API: `GET/POST /api/checkpoints`,
  `POST /api/checkpoints/<id>/rollback`. MCP: `sparkforge_checkpoint`.
  Fix di robustizia incluso: `publish()` non lascia più che un payload con `id`
  sovrascriva l'id numerico del feed (crash di replay risolto).
- ✅ **Context engineering** (`context_engine.py`): compazione estrattiva del
  transcript, budget di token (`SPARKFORGE_CONTEXT_BUDGET`, default 6000),
  retrieval dalla memoria (semantica + keyword fallback) iniettata nel prompt di
  chat; `context.built` events nel feed come evidenza. Endpoint:
  `POST /api/context/preview`. MCP: `sparkforge_context`.
- ✅ **Multi-model routing + fallback** (`routing.py`): selezione per ruolo
  (chat/planner/agent/subagent/summarizer) sul roster live del router `:8080`
  (`config/routing.yaml`), catena di fallback che termina sull'alias DeepSeek;
  failover a runtime via `stream_with_fallback` (event `model.failover` /
  `model.fallback`). API: `GET/POST /api/routing`. MCP: `sparkforge_routing`.
- ✅ **Memory write-rules fix** (`memory.py`): l'indice bag-of-words ora condivide
  il vocabolario tra indice e query (prima le dimensioni disallineate crashavano
  la ricerca semantica) e `_match` degrada a AND-of-words.

## Remaining (v0.4 leftovers / polish)

- [ ] **SparkPulse app-side streaming** (native SSE): consume `/api/chat/stream` + `/api/feed?since=` in the Forge tab instead of one-shot REST, Command tab with live plan/tasks/approvals — server-side contract is live and authed

## Remaining bullets (machine-readable)

`GET /api/tasks` exposes the same list as the tasks board; this file is the human mirror.
