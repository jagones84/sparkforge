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

## Done — v0.5 "UX harness moderna" (2026-09-29, JAG-41)

Follow-up dall'acceptance del Coordinator su JAG-33: API ok ma UX non da harness
moderna. Wave UX, verificata in live (chat reale via router, modello
`nex-n25-mini-uncensored-q8`) + regressioni v0.2 (8/8) e v0.3 (7/7) sul nuovo build.

- ✅ **Chat/CoT in UI sempre in streaming**: reasoning live visibile sia nel
  messaggio che nel drawer CoT mobile (`#cotDrawer`), con cursore di streaming;
  `reasoning` persistito in sessione e ri-mostrato da `/api/history`.
- ✅ **Todo dalla richiesta**: ogni richiesta utente viene spezzettata live in
  task sulla board (`breakdown_tasks()`, prompt planner-role, thread separato non
  bloccante, evento SSE `tasks.breakdown`). Evidenza: "ciao! ricordati che mi
  chiamo Dario…" → task `Salutare Dario`, `Creare tre task di test`, …
- ✅ **Compaction reale**: `POST /api/context/compact` compatta in-place il
  transcript di sessione (40 msg / 4040 tok → budget 800: 32 compattati, 8
  droppati, 1344 tok finali). `GET /api/context` + indicatore token con barra
  in header e pannello Context in UI; evento `context.compact` nel feed.
- ✅ **Sessioni UX**: lista/switch/crea (`GET/POST /api/sessions`,
  `/api/sessions/new`) + cancella (`DELETE /api/sessions/<id>`) dalla GUI,
  cronologia persistente ri-caricata dal file di sessione.
- ✅ **Self-knowledge agente**: tool `self` (registry, approval auto, anche via
  MCP) + `GET /api/self`: repo/data/config paths, ricetta install skill/MCP
  (`config/mcp_clients.yaml` + reload), stato systemd. Iniettato nel system
  prompt di chat e agent loop. Evidenza: alla domanda "dove sei installato e
  come installi una skill MCP?" il modello risponde con path e procedura reali.
- ✅ **GUI mobile arricchita** (webui 342 → 562 righe): stesso tema dark glass,
  tab bar mobile (chat/sessions/tasks/context/feed), drawer CoT live, meter
  contesto, pulsante compact, badge approvazioni.

## Done — v0.5.1 "chat/LLM server hardening" (2026-09-29, JAG-43)

Follow-up server wave from JAG-33 §A. Live diagnosis before the change:
`POST /api/chat` → 200 (reply ok, 6.69 s); `GET /api/chat/stream?message=` → 200 SSE
(first byte 0.02 s); **`POST /api/chat/stream` → 404**; no auth → 401.
Verified live by `tests/v051_acceptance.py` (9/9) — report in `data/v051-acceptance.json`.

- ✅ **`POST /api/chat/stream`** is now an alias of the GET SSE endpoint (JSON body
  `{message, session?, model?}`), so it answers `200 text/event-stream` instead of 404.
- ✅ **Warm-up before the first token**: the chat stream resolves the target alias and,
  if the model is cold, emits an SSE **`model.loading`** event (alias + `< 2 s` first byte)
  and drives an explicit `POST /models/load` before streaming — no more silent stall on
  the router's autoload. **`POST /api/model/ensure`** exposes the same warm-up as JSON
  (`{model?, action: already_loaded|loaded|timeout|unknown_model, seconds}`), and
  `ensure_model()` re-checks the roster after loading (`model.ready` /
  `model.load_failed` events).
- ✅ **`GET /api/selfcheck`** → 200 JSON: `version`, `model_requested`, `model_loaded`
  (+`model_loaded_alias` + full roster), `router_reachable` + `router_latency_ms`,
  `token_configured` (bool), `host`/`port`, and measured **`llm_latency_ms`** (1-token
  completion, `?llm=0` to skip); overall `status: ok|degraded`.
- ✅ **Router retry/backoff on 503 "model not loaded"** (`_open_with_retry`): the
  streaming *and* non-streaming chat calls retry with exponential backoff
  (`SPARKFORGE_ROUTER_RETRIES`=5, base 0.75 s → max 8 s) and emit `model.retry` feed
  events before giving up.

## Done — v0.6 "task graph generato dall'LLM (live, legato al run, interattivo)" (2026-09-29, JAG-45)

Deliverable from the Piano v2 on JAG-33. Problem: the TASKS panel was a *global* list
disconnected from the chat and not interactive; modern harnesses (Claude Code Agent SDK
todo-tracking, Deep Agents `write_todos`, plan/act/check with visible state) keep a live,
per-run graph the model itself produces. Verified by `tests/v06_taskgraph.py`
(**15/15** — 5 module checks, 8 mock-router end-to-end checks, 2 live-model checks) —
raw report in `data/v06-acceptance.json`, raw command+output in
[docs/V06-EVIDENCE.md](V06-EVIDENCE.md).

- ✅ **`plan_graph` per run** (`taskgraph.py`): one graph per run in `data/graphs/<run_id>.json`,
  bound to `session_id` + `run_id`; nodes `{id, label, status todo|doing|done|blocked|cancelled,
  deps[], evidence[]}`; `GET /api/runs/<id>/graph` serves it.
- ✅ **First action = model-generated `write_todos`** (no static template): the run streams
  the tool call and parses it incrementally (NDJSON one todo per line, or nested
  `{"todos":[…]}`), so nodes appear live. Measured with the mock router: **3 todo nodes in
  0.085 s**; live model (`nex-n25-mini-uncensored-q8`): 3 request-specific nodes.
- ✅ **Existing actions mapped** onto the graph: `plan_step` / `complete_plan_step` /
  `add_task` / `complete_task` (both the v0.1 loop and the v0.2 tool loop) now add/complete
  graph nodes; a `write_todos` action is also accepted inside the agent loop prompts.
- ✅ **Live SSE** `graph.node.added` / `graph.node.updated` (on the chat/agent stream *and*
  the durable feed); `graph.generated` / `graph.finalized` summary events.
- ✅ **Evidence mandatory on `done`**: a node cannot become `done` without a non-empty
  evidence entry (`ValueError` → HTTP 400), and at run end every open node is closed with
  evidence — acceptance "a fine run tutti done con evidenza".
- ✅ **`POST /api/runs/<id>/graph/nodes`**: add / update / cancel / complete a node and
  **incremental re-plan** (`{action:"replan"}` asks the model only for the still-missing
  steps; the mock proves duplicates are dropped).
- ✅ **WebUI**: the **TASKS** panel is now the current run's graph — live status badges,
  `⤷` deps, `📎` evidence count, tap a node for its evidence and one-tap
  done/doing/blocked/cancel, plus a `+` add-node and a `↻ replan` action.
- ✅ **SparkPulse app v1.6**: new 🧩 GRAFO panel — same live graph, **tap a node for detail**
  (deps + evidence), run id in the header; parsers covered by `ForgeGraphTest` (38/38
  unit tests green, debug APK assembles).

## Remaining (v0.4 leftovers / polish)

- [ ] **SparkPulse app-side streaming** (native SSE): consume `/api/chat/stream` + `/api/feed?since=` in the Forge tab instead of one-shot REST, Command tab with live plan/tasks/approvals — server-side contract is live and authed

## Remaining bullets (machine-readable)

`GET /api/tasks` exposes the same list as the tasks board; this file is the human mirror.
