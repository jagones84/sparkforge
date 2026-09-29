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

## Remaining (v0.3 / v0.4 / polish)

- [ ] **v0.2 — SparkPulse bridge**: "Command" tab in the SparkPulse Android app hitting `/api/chat/stream` + `/api/feed`; `POST /api/commands` adapter in sparkpulse-server
- [ ] **v0.2 — WebUI auth flow** for `--token` mode (token prompt + `?token=` on EventSource) — *present in the tree, not covered by this task's acceptance run*
- [ ] **v0.3 — MCP client**: connect the existing MCP servers (Filesystem, Playwright, memory) as native tools (Goose pattern)
- [ ] **v0.3 — Subagent delegation** (deepagents pattern): spawn child agent runs from the loop
- [ ] **v0.3 — Checkpoint / resume / rollback** of plan, tasks and transcript with idempotency
- [ ] **v0.3 — Persistent memory store** with write rules (markdown + optional vector index)
- [ ] **v0.3 — Context engineering**: transcript compaction, token budget, retrieval
- [ ] **v0.4 — Durable event store (SQLite) + replay**, OTel tracing + token/cost accounting per run
- [ ] **v0.4 — systemd unit** for always-on service (loopback feed alive for the phone 24/7) + API auth token
- [ ] **v0.4 — Mobile streaming** in SparkPulse (SSE) + Command tab with live approvals
- [ ] **v0.4 — Voice**: whisper.cpp STT + sherpa-onnx TTS
- [ ] **v0.4 — Eval harness**: gold task set + scoring of loop quality (Winder.AI pattern)

## Remaining bullets (machine-readable)

`GET /api/tasks` exposes the same list as the tasks board; this file is the human mirror.
