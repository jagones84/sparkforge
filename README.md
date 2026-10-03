# SparkForge

**A frontier-style agent harness for the DGX Spark — chat, plan, tasks, agent loop, WebUI, CLI, and a mobile command API, all backed by the local llama.cpp router.**

© 2025-2026 Giovanni J. Agones ([jagones84](https://github.com/jagones84)) · licensed under AGPL-3.0 (see [LICENSE](LICENSE)).

SparkForge is the "super harness" successor to the SparkPulse mobile telemetry project (JAG-16): where SparkPulse *observes* the DGX from your phone, SparkForge *commands* it — a state-of-the-art (2026-pattern) harness wrapped around whatever LLM the local router (`:8080`) has loaded, with:

- 💬 **Streaming chat** with visible **Chain-of-Thought** timeline (`reasoning_content` or `<think>` parsing)
- 🧠 **PLAN** — model-generated strategy steps, tracked with progress
- ✅ **TASKS** — from v0.6 the panel *is* the current run's **LLM-generated task graph** (`write_todos`), streamed live over SSE and interactive
- ⚡ **Agent loop** — a real sense-think-act loop (`thought → action → observation`) that mutates plan/tasks **and calls real tools**
- 🛠️ **Tool registry** — declarative `shell`, `fs.read`, `fs.write`, `git`, `http`, `browser` with a JSON-schema allowlist (`config/tools.yaml`)
- 🔐 **Approval gates** — every world-touching action is recorded in `/api/approvals` (auto-approve for read-only patterns, hard-deny for destructive ones); a pending action pauses the run until a human decides
- 🧱 **Real sandbox** — `docker` (or `bubblewrap` / `nsjail`) with `--network none`, read-only rootfs, dropped capabilities and a throwaway `/work` scratch dir; the agent never sees the host
- ⏸️ **HITL** — pause / resume / abort a run mid-flight (`/api/agent/control`)
- 🔌 **MCP server mode** — expose the harness to Paperclip (or any MCP client) over stdio or HTTP
- 📡 **Loopback feed** — Server-Sent Events stream of every harness event (chat deltas, plan/task changes, agent iterations, tool calls, approvals) for mobile + WebUI live views
- 🖥️ **Frontier WebUI** — dark glassmorphism, live thinking, plan/tasks sidebar, command bar
- ✨ **UX harness moderna (v0.5)** — mobile tab bar (chat/sessions/tasks/context/feed), live CoT drawer, todo breakdown of every request onto the task board, token budget meter with one-tap compaction, session switch/create/delete, `self` tool for agent self-knowledge
- 🧩 **LLM task graph (v0.6)** — every run's first action is a model-generated `write_todos` call that builds a **live, interactive graph of that run** (nodes, deps, evidence; `graph.node.*` over SSE; evidence required for `done`)
- ⏹️ **Streams that actually end (v0.6.1)** — the chat/agent SSE terminates right after its terminal `done` and releases the socket, so the app leaves `busy` and the next message is never blocked; keep-alive stays a `/api/feed`-only tail
- 🧾 **No request without an answer (v0.6.2)** — every request persists one `user` + one `assistant` turn (reply **or** explicit error turn), so a session never ends on an orphan user message; verified by `tests/legacy/v062_session_persistence.py`
- 🔌 **Real MCP clients (v0.7)** — `config/mcp_clients.yaml` connects the agent to real MCP servers (e.g. `pmcp` on `:3344`, bearer auth via `${VAR}` headers + env_files); their tools appear as `<client>__<tool>` in the registry and the agent loop calls them through the approval gate, with the MCP output as observation; verified by `tests/legacy/v07_mcp_fsedit.py`
- ✂️ **`fs.edit` (v0.7)** — surgical search/replace file edit (single or `replace_all`, refuses missing/ambiguous matches) instead of rewriting whole files with `fs.write`
- 🧠 **Skills (v0.7.1, JAG-56)** — `skills/` holds the agent skill registry: one `SKILL.md` per skill under `skills/<category>/<name>/` (symlinked into the user skill distribution, e.g. `skills/ops -> ../../skills-autodist-skill/ops`); the `skills` tool (`{"action":"list"}` / `{"action":"read","name":"..."}`) lists and loads them, `self` reports the installed skills + how to add more; verified by `tests/legacy/v071_skills_pmcp.py`
- 🗃️ **Real agent memory (v0.7.6, JAG-73)** — the `memory` tool (`action=store|recall|recent`) lets the agent deliberately remember durable facts and recall them; relevant memories are also auto-injected each turn, and the system prompt now carries an explicit **memory policy** (what it is + when to store/recall); verified by `tests/legacy/v076_memory_tool.py`
- ⏱️ **Act, don't announce (v0.7.7, JAG-74)** — if the model only *promises* an action ("Carico…"/"I'll…") without calling a tool, the turn nudges it once to actually run it (or conclude); the announcement is never persisted; verified by `tests/legacy/v077_act_not_announce.py`
- 🔌 **MCP sessions self-heal (v0.7.7, JAG-74)** — a streamable-HTTP MCP session that expires server-side ("Session not found") is re-initialized and the call replayed, so `pmcp` tools keep working without a restart
- 🪝 **Deterministic hooks (v0.7.3, JAG-69)** — `hooks.py` + `config/hooks.yaml` (empty by default): shell scripts on `PreToolUse` (exit 2 **blocks** the call, Claude Code contract), `PostToolUse` (observation in `$SPARKFORGE_OBSERVATION`) and `Stop`; no model in the loop, every hook emits `hook.run`; `GET /api/hooks`; verified by `tests/legacy/v073_hooks.py`
- ⏹️ **Stop a running tool (v0.7.2, JAG-68)** — `sandbox.run` uses Popen with a process group, so `POST /api/tools/cancel {run_id}` SIGTERM→SIGKILLs the actual job (and `docker kill`s a container); `GET /api/tools/running` lists live jobs; the app's STOP kills the job, not just the socket
- 🧩 **Model-authored task list (JAG-65)** — the todo list is written **inline** by the model on its own first turn (harness action `write_todos`), never by a separate blocking planner call; session-keyed, persistent, re-injected every turn, and the reasoning streams live during tool steps
- 🔄 **The model drives the graph itself (v0.7.8, JAG-75)** — after authoring the plan the model advances it mid-run: `update_todos` marks a step `doing` → `done` **with evidence**, and `replan_todos` briefly re-plans (only new steps are generated) then resumes the plan; every change streams `graph.node.updated` to the app; verified by `tests/legacy/v078_taskgraph_selfupdate.py`
- 📏 **Real context budget (JAG-66)** — the compaction budget is derived from the model's actual window (`meta.n_ctx`, e.g. 258048 for the 256k models) minus a reply reserve, instead of a fixed 6000
- 🔀 **Providers & model picker (v0.7.5, JAG-71)** — `config/providers.yaml` + `providers.py` catalogue llama.cpp (DGX **and** Windows), vLLM, **OpenRouter** (GLM-flash / DeepSeek-flash families) and the **original DeepSeek** API; a model reference is `<provider>:<model>` (bare id resolves local-first); keys come from a gitignored `.env`/`~/.hermes/.env`, never the repo; `GET /api/providers` feeds the phone picker and `&model=` routes any chat/agent/context request
- 📈 **Honest `ctx x / max` (JAG-70/72)** — `x` is the REAL prompt (system prompt + compacted transcript + message) measured with the same assembler, model-aware budget and memory the turn actually uses; `max` is the model's real window (local `n_ctx`, remote from live OpenRouter metadata, no guess); auto-compaction fires at **75%**
- ⚡ **No more stalls (JAG-72)** — the memory embedder is loaded **once** and a dead embeddings endpoint is disabled after a single probe; previously the model was rebuilt / a 30s timeout was paid per memory kind on every search
- 💬 **Chat UI leggibile (v0.7.1, JAG-55)** — la **risposta** è il testo principale del messaggio (il reasoning resta nel drawer CoT, mai al posto della reply); **copia** con un tap per messaggio (⧉) e transcript selezionabile; **tool call inline** nella chat come mini-card 🔧→✅/⛔ con esito (`tool.call`/`tool.result` sullo stream, coerenti con i nodi del task graph); indicatore **contesto onesto**: con `session` reale mostra token/budget/messaggi veri, senza sessione `/api/context` risponde `available:false` e la UI mostra **n/d** invece del finto 6000/0
- ⌨️ **CLI** (`forge.py`) — chat, agent runs, plan/task control from the terminal
- 📱 **Mobile-ready API** — bind to `0.0.0.0` and command the DGX from the phone over Tailscale, same as SparkPulse

## ✨ Sperimentale — frontier features

- 🧬 **Meta-harness self-improvement**: outer-loop proposes variants, evaluates on Pareto frontier (quality vs. cost)
- 🔄 **ACP (Agent Client Protocol)**: bidirectional interop between harnesses
- 🐝 **Swarm / blackboard**: multiple agents cooperate on shared state
- 🧠 **Persistent memory**: append-only markdown + numpy vector index
- 🔌 **MCP client**: connect external MCP servers as native tools
- 👶 **Subagent delegation**: spawn child agent runs for delegated subtasks

## Quick start

```bash
./run.sh                     # WebUI + API on http://127.0.0.1:8790
./run.sh --host 0.0.0.0      # expose on the Tailscale IP for the phone
```

Then open `http://127.0.0.1:8790` (or `http://<dgx-tailscale-ip>:8790` from the phone).

On Windows (native, no WSL) the same core runs with Python 3.10+ on PATH:

```powershell
.\run.ps1                     # WebUI + API on http://127.0.0.1:8790
.\run.ps1 --host 0.0.0.0      # expose on the LAN for the phone
```

Shell execution, process-tree kill and `npx` MCP launch all route through
`osutil.py`, so no POSIX assumption leaks into the core; `deploy/sparkforge.service`
stays a Linux-only convenience (on Windows install it as a service with `nssm`).

```bash
python3 forge.py chat "hello, who are you?"       # one-shot chat
python3 forge.py chat --stream                    # streaming chat in terminal
python3 forge.py agent "plan a backup routine"    # agent loop demo
python3 forge.py plan show                        # current plan + remaining
python3 forge.py tasks ls                         # task board + remaining bullets
python3 forge.py models                           # router model roster/status
```

> 📖 **Full CLI reference** — every command, every endpoint, examples: **[CLI.md](docs/CLI.md)**.

### Regression battery (the gate)

The **only** regression gate is a single 3-test battery — deterministic, fast and
fully isolated: it points every `SPARKFORGE_*` data dir at a throwaway temp dir, so
it never touches the live `data/` and never litters the WebUI with sessions.

```bash
bash tests/battery.sh
```

It runs exactly three checks:
- `tests/v140_subagent_todos.py` — subagent spawning, per-child todo lists, depth cap, taskgraph nesting;
- `tests/v174_session_isolation.py` — per-session independence (queue / feed / plan) + abort guard;
- `tests/v177_session_delete_cascade.py` — deleting a session removes transcript + graph + run + edits.

Everything else under `tests/legacy/` is historic acceptance evidence, run ad hoc,
and is **not** part of the gate.

### v0.2 — tools, sandbox, approvals, MCP

```bash
python3 forge.py sandbox                                  # probe the sandbox backend (evidence)
python3 forge.py tools ls                                 # registry + allowlist + approval policy
python3 forge.py tools call shell '{"command":"uname -m && echo hi"}'   # auto-approved (read-only)
python3 forge.py approvals ls                             # the approval queue
python3 forge.py approvals approve <id>                   # decide a pending action
python3 forge.py runs ls                                  # agent runs + HITL status
python3 forge.py control abort run_ab12cd34               # pause | resume | abort a live run
python3 forge.py mcp                                      # open an MCP session and list tools
python3 tests/legacy/v02_acceptance.py                           # end-to-end evidence (8 checks)
```

Agent runs accept a **script** for deterministic, reproducible runs:

```bash
curl -sX POST localhost:8790/api/agent/run -H 'content-type: application/json' -d '{
  "goal": "prove the sandbox",
  "script": [
    {"thought":"run it","action":"tool","tool":"shell","args":{"command":"mkdir -p out && uname -a > out/u.txt && cat out/u.txt"}},
    {"action":"finish","summary":"done"}]}'
```

Register SparkForge as an MCP server (stdio):

```json
{ "mcpServers": { "sparkforge": {
    "command": "python3",
    "args": ["/home/jagones/Repositories/sparkforge/mcp_server.py"],
    "env": {"SPARKFORGE_URL": "http://127.0.0.1:8790"} } } }
```

### v0.3 — checkpoints, context engineering, multi-model routing

```bash
python3 tests/legacy/v03_acceptance.py                # end-to-end evidence (7 checks, live service)
# checkpoints: snapshot plan+tasks+transcript, idempotent, rollback-able
curl -sX POST localhost:8790/api/checkpoints -d '{"label":"before risky run","idempotency_key":"run-42"}'
curl -s localhost:8790/api/checkpoints         # list
curl -sX POST localhost:8790/api/checkpoints/cp_xxx/rollback   # restore state
# context engineering: compaction + token budget + memory retrieval
curl -sX POST localhost:8790/api/context/preview -d '{"session":"<sid>","message":"...","budget_tokens":2000}'
# multi-model routing: role selection from the router roster, DeepSeek fallback
curl -s localhost:8790/api/routing
```

- **Auto-checkpoint on every agent run** (`agent-run:<run_id>`): plan/tasks/transcript survive and can be rolled back after a bad run.
- **Chat context**: transcript is compacted under a token budget and relevant memories from previous sessions are injected (`context.built` events in the feed show the stats).
- **Fallback chain**: if the primary role model fails on a call, the harness walks the role chain down to the DeepSeek alias automatically (`model.failover` events).

### v0.4 — ops, tracing, voice, eval

```bash
python3 tests/legacy/v04_acceptance.py                # end-to-end evidence (17 checks, live service)
curl -s http://127.0.0.1:8790/api/eval/tasks   # gold task set
curl -sX POST http://127.0.0.1:8790/api/eval/run -d '{"task_id":"plan-hello"}'  # score a run
curl -s http://127.0.0.1:8790/api/runs/<id>/trace   # OTel spans + token/cost per run
curl -s http://127.0.0.1:8790/api/voice/status      # STT/TTS backend availability
# STT: POST the recorded wav as audio/wav; TTS: {"text":"..."} -> wav served from
# /api/voice/audio/<file> — both power phone voice commands over Tailscale.
```

Always-on service (user unit, auto-restart, token via `~/.config/sparkforge/env`):

```bash
cp deploy/sparkforge.service ~/.config/systemd/user/ && systemctl --user daemon-reload
systemctl --user enable --now sparkforge.service
journalctl --user -u sparkforge.service -f
```

- **Durable events**: the SSE feed replays from SQLite — reconnect with `/api/feed?since=<id>`, or read the backlog as JSON via `/api/feed/recent`.
- **Tracing**: runs carry genuine OpenTelemetry spans (trace_id, hierarchy, ns timestamps) when the OTel SDK is installed; token/cost accounting is recorded for every run.

### v0.5.1 — chat/LLM server hardening

```bash
python3 tests/legacy/v051_acceptance.py               # end-to-end evidence (9 checks)
curl -s localhost:8790/api/selfcheck           # version, model, router, token, LLM latency
curl -sX POST localhost:8790/api/model/ensure -d '{}'          # warm the chat model
curl -sN localhost:8790/api/chat/stream -d '{"message":"ciao"}'  # POST alias of the GET SSE stream
```

- **Cold-model warm-up**: the chat stream emits `model.loading` (< 2 s first byte) and loads
  the model before the first token — no silent stall on the router's autoload.
- **`GET /api/selfcheck`**: `{version, model_requested, model_loaded, router_reachable,
  router_latency_ms, llm_latency_ms, token_configured, host, port}` (status `ok|degraded`).
- **`POST /api/model/ensure`**: idempotent warm-up (`already_loaded` / `loaded` / `timeout`).
- **Router resilience**: transient `503 model not loaded` is retried with exponential
  backoff (`model.retry` feed events) before any fallback.

### v0.6 — LLM task graph (live, bound to the run, interactive)

```bash
python3 tests/legacy/v06_taskgraph.py                       # end-to-end evidence (15 checks)
curl -sN localhost:8790/api/chat/stream -d '{"message":"analizza il README in 3 step"}'  # live graph over SSE
curl -s  localhost:8790/api/runs/<run_id>/graph      # persisted graph of that run
curl -sX POST localhost:8790/api/runs/<run_id>/graph/nodes \
     -d '{"action":"add","label":"Verifica manuale"}'                    # add a node
curl -sX POST localhost:8790/api/runs/<run_id>/graph/nodes \
     -d '{"action":"replan","note":"aggiungi la verifica finale"}'       # incremental re-plan
```

- **Per-run graph, not a global list.** `taskgraph.py` keeps one graph per run in
  `data/graphs/<run_id>.json`, bound to `run_id` + `session_id`; nodes carry
  `id, label, status (todo|doing|done|blocked|cancelled), deps[], evidence[]`.
- **First action = `write_todos`.** Every run asks the model (planner role) for a
  `write_todos` tool call — never a static template. The reply is consumed
  incrementally (NDJSON one todo per line, or a nested `{"todos":[…]}` object), so
  each `graph.node.added` lands on the SSE stream the moment the model emits it
  (measured: 3 todo nodes in **0.08 s** with the mock router).
- **Legacy actions mapped.** `plan_step`, `complete_plan_step`, `add_task`,
  `complete_task` (both agent loops) now also mutate the run graph.
- **Evidence is mandatory for `done`.** A node can only move to `done` with a
  non-empty evidence entry (command + output); runs finalize by closing every open
  node with evidence, so a finished run shows all nodes `done` with proof.
- **Interactive.** `POST /api/runs/<id>/graph/nodes` adds/cancels/updates a node and
  re-plans incrementally (`{action:"replan"}` asks the model only for the missing steps).
- **UI.** The WebUI **TASKS** panel *is* the current run's graph (live badges, `⤷` deps,
  `📎` evidence count, tap a node for its evidence + one-tap done/cancel/replan);
  the SparkPulse app (v1.6) has the same graph as a **tap-to-detail** panel.

### v0.6.1 — chat SSE closes after `done`

```bash
python3 tests/legacy/v061_stream_close.py --live     # end-to-end evidence (8 checks, mock + live)
```

- **Terminal `done` ends the stream.** `GET|POST /api/chat/stream` (and
  `/api/agent/run`) emit exactly one `done`, the generator is exhausted and the
  socket is closed (flush + `SHUT_WR`) — clients that wait for EOF are released
  immediately, so the next message is never blocked.
- **Keep-alive is `/api/feed`-only.** Chat streams carry no `: ping` filler;
  `/api/feed` and `/api/blackboard/watch` keep their keep-alive tail.
- **Stalled upstream can't hang the run.** A silent router stream ends after
  `SPARKFORGE_ROUTER_IDLE_TIMEOUT` (default 120 s) keeping the partial answer,
  and the chat stream itself gives up after `SPARKFORGE_CHAT_STREAM_IDLE`
  (default 900 s) with `error` + `done` instead of staying ESTAB forever.

### v0.6.2 — no request without an answer (session persistence)

```bash
python3 tests/legacy/v062_session_persistence.py       # end-to-end evidence (mock router)
python3 tests/legacy/v062_session_persistence.py --live  # also against the live service
```

- **The invariant.** Every request on a session persists **exactly one `user`
  message followed by exactly one `assistant` message** — either the reply or an
  explicit error turn (`role:"assistant"`, `error:true`, `error_detail:"…"`).
  A session can never end on an orphan `user` message (bug: `data/sessions/
  dc65e66e9b3d.json` had 1 message, no answer).
- **Failure paths covered.** A router error on `POST /api/chat` now stores the
  error turn *before* returning `502 {session, run_id, stored_error:true}`; a
  failure inside the SSE worker of `/api/chat/stream` stores it too, *and* emits
  the `error` SSE event (`{error, session, stored:true}`). The in-process MCP
  `chat` tool follows the same contract. A silent empty answer is stored as an
  explicit error turn instead of a blank bubble.
- **Helper.** `server.ensure_reply_persisted(sess, mark, error=…)` +
  `server.session_mark(sess)` implement it; idempotent, so `except` + `finally`
  paths never double-append.
- **Evidence.** 3 sequential requests on the same session save **6 messages
  (3 user + 3 assistant)** — over both the POST and the SSE path — and a
  router-down session saves 3 user + 3 error assistant turns (counted from
  `/api/history?session=…`).

### session parameter contract — `POST /api/chat`, `GET|POST /api/chat/stream`

| `session` | behaviour |
|---|---|
| omitted / empty / `null` | a **new** session is created with a generated id (`uuid4().hex[:12]`); the id is returned in the JSON body (`{"session": "<id>", …}`) or in the SSE `chat.user`/`chat.delta`/`chat.done` payloads |
| unknown id | a new session is **created with that exact id** (no id is ever silently replaced) |
| existing id | the request is **appended** to that session's `messages[]` |

Per request, on that session (persisted to `data/sessions/<id>.json`):

1. one `user` message — `{role:"user", content, ts}`;
2. one `assistant` message — `{role:"assistant", content, ts, model, reasoning?}`
   on success, or `{role:"assistant", content:"⚠️ errore: …", ts, model,
   error:true, error_detail:"…"}` when the router call failed or returned
   nothing.

So after **N** requests a session holds **exactly 2N messages**; `GET
/api/history?session=<id>` returns them. Streaming requests are asynchronous
(the SSE body arrives before the answer), but the same 2-message rule holds once
the stream ends — read the session back after the terminal `done`.

## API (mobile contract)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/status` | Router roster + DGX telemetry summary |
| POST | `/api/chat` | One-shot chat `{session?, message, model?}` |
| GET | `/api/chat/stream?session&message&model` | SSE chat stream (tokens + thinking), closes after `done` |
| POST | `/api/chat/stream` | SSE chat stream — alias of the GET (`{message, session?, model?}`), closes after `done` |
| GET | `/api/selfcheck` | Health/version/model/router/token + LLM latency |
| POST | `/api/model/ensure` | Warm the chat model (or `{model}`) before chatting |
| GET | `/api/feed` | SSE harness event feed (`?since=<id>` to resume) — **keep-alive** tail |
| GET/POST | `/api/plan` | Read / set goal; `POST /api/plan/generate {goal}` |
| GET/POST/PATCH | `/api/tasks` | Task board; `PATCH /api/tasks {id, status?}` |
| POST | `/api/agent/run` | Agent loop `{goal, max_steps, script?}` (also GET `/api/agent/run?goal=` for SSE) |
| GET | `/api/sessions`, `/api/history?session=` | Chat session store |
| POST | `/api/sessions`, `/api/sessions/new` | Create a session `{title?}` |
| DELETE | `/api/sessions/<id>` | Delete a session |
| GET | `/api/self` | Self-knowledge: paths, config, MCP/skill install recipe, systemd state |
| GET | `/api/context?session=&model=` | Effective prompt tokens vs the model's real budget (UI indicator) |
| POST | `/api/context/compact` | Compact a session transcript in place `{session, budget_tokens?}` |
| GET | `/api/runs`, `/api/runs/<id>/trace` | Run trace + token/cost accounting |
| GET | `/api/runs/<id>/graph` | **v0.6** — the run's LLM task graph (nodes, deps, evidence, counts) |
| POST | `/api/runs/<id>/graph/nodes` | **v0.6** — `{action: add\|update\|cancel\|complete\|replan, …}` (evidence required for `done`) |
| GET | `/api/eval/tasks`, `/api/eval/run` | Eval harness (gold tasks + scoring) |
| GET/POST | `/api/voice/status`, `/api/voice/stt`, `/api/voice/tts` | Speech I/O (whisper.cpp + sherpa-onnx) |
| GET/POST | `/api/memory` | Persistent memory store (keyword + semantic search) |
| GET | `/api/mcp/clients` | Connected MCP client status |
| GET | `/api/subagent` | Subagent status list |
| POST | `/api/subagent/spawn`, `/api/subagent/collect` | Subagent delegation |
| GET/POST | `/api/meta` | Meta-harness self-improvement |
| POST | `/api/acp` | ACP JSON-RPC (server mode) |
| POST | `/api/acp/connect` | ACP client connect |
| GET/POST | `/api/blackboard` | Swarm blackboard |
| GET | `/api/blackboard/watch` | SSE blackboard watcher |
| POST | `/api/swarm/run` | Swarm coordinator |
| GET/POST | `/api/tools` | Tool registry (allowlist); POST flips `enabled`/`approval` |
| POST | `/api/tools/call` | Run one tool through the approval gate `{tool, args, wait?}` |
| GET | `/api/tools/running` | Jobs currently executing (job, pid, command, seconds) |
| POST | `/api/tools/cancel` | Stop a running tool job `{job\|run_id}` |
| GET | `/api/hooks` | Lifecycle hooks (`PreToolUse`/`PostToolUse`/`Stop`); `?reload=1` to re-read |
| GET | `/api/providers` | Provider/model catalogue (dgx, win, vllm, openrouter, deepseek) with live availability + real context windows |
| GET | `/api/approvals`, `/api/approvals/<id>` | Approval queue + stats / one record |
| POST | `/api/approvals/<id>` | `{decision: approve\|deny, by}` |
| POST | `/api/agent/control` | `{runId, action: pause\|resume\|abort}` |
| GET | `/api/agent/runs`, `/api/agent/runs/<id>` | Live run status + thought/action/observation trace |
| GET | `/api/sandbox`, `/api/feed/recent` | Sandbox backend probe / feed backlog as JSON |
| POST | `/mcp` | MCP JSON-RPC 2.0 (`initialize`, `tools/list`, `tools/call`) |

Optional auth: start with `--token <t>` and send `Authorization: Bearer <t>`.

## Safety model (v0.2) — sandbox-first, nothing without evidence

1. **Allowlist first.** A tool must be `enabled: true` in `config/tools.yaml`; everything else is denied. `browser` ships disabled.
2. **Per-action approval gate.** `registry.classify(tool, args)` returns `auto | required | denied | disabled`. Read-only patterns (e.g. `^ls`, `^git status`, `fs.read`) are auto-approved *and still recorded*; anything else creates a `pending` approval that pauses the run until a human decides.
3. **Hard denies.** Regexes like `rm -rf /`, `mkfs`, `dd if=/dev/zero`, `shutdown` and `git push` are blocked even with an approval.
4. **Real sandbox.** `shell` runs on a fresh per-run scratch dir in `docker --network none --read-only --cap-drop ALL --user 65534` (falls back to `bwrap`/`nsjail`, and refuses to silently degrade to the host). Verified: network egress fails inside the container.
5. **Observable.** Every decision and tool result is a feed event and lands in the run trace; `tests/legacy/v02_acceptance.py` proves each claim with command + output + numbers.

**Verification.** `tests/legacy/v02_acceptance.py` passes **8/8** against a running instance
(`./run.sh`; report in `data/v02-acceptance.json`), and the two v0.2 acceptance criteria
were reproduced by hand — an agent run executing a real sandboxed shell command with a
recorded approval whose output is the observation, and a Paperclip-style MCP session that
receives a reply. Raw command + output evidence: [docs/evidence/V02-EVIDENCE.md](docs/evidence/V02-EVIDENCE.md).

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and the research base in
[docs/RESEARCH-frontier-harnesses-2026.md](docs/RESEARCH-frontier-harnesses-2026.md).
Roadmap and remaining work: [docs/PLAN.md](docs/PLAN.md).

## Relationship to SparkPulse

SparkPulse (app + server) stays the telemetry/mobile dashboard. SparkForge consumes the
same router and can be reached from the same phone; a future bridge task (see PLAN)
will surface SparkForge inside the SparkPulse app as a "Command" tab.
