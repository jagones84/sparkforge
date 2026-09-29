# SparkForge

**A frontier-style agent harness for the DGX Spark — chat, plan, tasks, agent loop, WebUI, CLI, and a mobile command API, all backed by the local llama.cpp router.**

SparkForge is the "super harness" successor to the SparkPulse mobile telemetry project (JAG-16): where SparkPulse *observes* the DGX from your phone, SparkForge *commands* it — a state-of-the-art (2026-pattern) harness wrapped around whatever LLM the local router (`:8080`) has loaded, with:

- 💬 **Streaming chat** with visible **Chain-of-Thought** timeline (`reasoning_content` or `<think>` parsing)
- 🧠 **PLAN** — model-generated strategy steps, tracked with progress
- ✅ **TASKS** — execution units with status + remaining bullets
- ⚡ **Agent loop** — a real sense-think-act loop (`thought → action → observation`) that mutates plan/tasks **and calls real tools**
- 🛠️ **Tool registry** — declarative `shell`, `fs.read`, `fs.write`, `git`, `http`, `browser` with a JSON-schema allowlist (`config/tools.yaml`)
- 🔐 **Approval gates** — every world-touching action is recorded in `/api/approvals` (auto-approve for read-only patterns, hard-deny for destructive ones); a pending action pauses the run until a human decides
- 🧱 **Real sandbox** — `docker` (or `bubblewrap` / `nsjail`) with `--network none`, read-only rootfs, dropped capabilities and a throwaway `/work` scratch dir; the agent never sees the host
- ⏸️ **HITL** — pause / resume / abort a run mid-flight (`/api/agent/control`)
- 🔌 **MCP server mode** — expose the harness to Paperclip (or any MCP client) over stdio or HTTP
- 📡 **Loopback feed** — Server-Sent Events stream of every harness event (chat deltas, plan/task changes, agent iterations, tool calls, approvals) for mobile + WebUI live views
- 🖥️ **Frontier WebUI** — dark glassmorphism, live thinking, plan/tasks sidebar, command bar
- ✨ **UX harness moderna (v0.5)** — mobile tab bar (chat/sessions/tasks/context/feed), live CoT drawer, todo breakdown of every request onto the task board, token budget meter with one-tap compaction, session switch/create/delete, `self` tool for agent self-knowledge
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

Then open `http://127.0.0.1:8790` (or `http://100.102.61.23:8790` from the phone).

```bash
python3 forge.py chat "hello, who are you?"       # one-shot chat
python3 forge.py chat --stream                    # streaming chat in terminal
python3 forge.py agent "plan a backup routine"    # agent loop demo
python3 forge.py plan show                        # current plan + remaining
python3 forge.py tasks ls                         # task board + remaining bullets
python3 forge.py models                           # router model roster/status
```

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
python3 tests/v02_acceptance.py                           # end-to-end evidence (8 checks)
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
python3 tests/v03_acceptance.py                # end-to-end evidence (7 checks, live service)
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
python3 tests/v04_acceptance.py                # end-to-end evidence (17 checks, live service)
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

## API (mobile contract)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/status` | Router roster + DGX telemetry summary |
| POST | `/api/chat` | One-shot chat `{session?, message, model?}` |
| GET | `/api/chat/stream?session&message&model` | SSE chat stream (tokens + thinking) |
| GET | `/api/feed` | SSE harness event feed (`?since=<id>` to resume) |
| GET/POST | `/api/plan` | Read / set goal; `POST /api/plan/generate {goal}` |
| GET/POST/PATCH | `/api/tasks` | Task board; `PATCH /api/tasks {id, status?}` |
| POST | `/api/agent/run` | Agent loop `{goal, max_steps, script?}` (also GET `/api/agent/run?goal=` for SSE) |
| GET | `/api/sessions`, `/api/history?session=` | Chat session store |
| POST | `/api/sessions`, `/api/sessions/new` | Create a session `{title?}` |
| DELETE | `/api/sessions/<id>` | Delete a session |
| GET | `/api/self` | Self-knowledge: paths, config, MCP/skill install recipe, systemd state |
| GET | `/api/context?session=` | Token usage vs context budget (UI indicator) |
| POST | `/api/context/compact` | Compact a session transcript in place `{session, budget_tokens?}` |
| GET | `/api/runs`, `/api/runs/<id>/trace` | Run trace + token/cost accounting |
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
5. **Observable.** Every decision and tool result is a feed event and lands in the run trace; `tests/v02_acceptance.py` proves each claim with command + output + numbers.

**Verification.** `tests/v02_acceptance.py` passes **8/8** against a running instance
(`./run.sh`; report in `data/v02-acceptance.json`), and the two v0.2 acceptance criteria
were reproduced by hand — an agent run executing a real sandboxed shell command with a
recorded approval whose output is the observation, and a Paperclip-style MCP session that
receives a reply. Raw command + output evidence: [docs/V02-EVIDENCE.md](docs/V02-EVIDENCE.md).

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and the research base in
[docs/RESEARCH-frontier-harnesses-2026.md](docs/RESEARCH-frontier-harnesses-2026.md).
Roadmap and remaining work: [docs/PLAN.md](docs/PLAN.md).

## Relationship to SparkPulse

SparkPulse (app + server) stays the telemetry/mobile dashboard. SparkForge consumes the
same router and can be reached from the same phone; a future bridge task (see PLAN)
will surface SparkForge inside the SparkPulse app as a "Command" tab.
