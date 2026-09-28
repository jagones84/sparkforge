# SparkForge

**A frontier-style agent harness for the DGX Spark — chat, plan, tasks, agent loop, WebUI, CLI, and a mobile command API, all backed by the local llama.cpp router.**

SparkForge is the "super harness" successor to the SparkPulse mobile telemetry project (JAG-16): where SparkPulse *observes* the DGX from your phone, SparkForge *commands* it — a state-of-the-art (2026-pattern) harness wrapped around whatever LLM the local router (`:8080`) has loaded, with:

- 💬 **Streaming chat** with visible **Chain-of-Thought** timeline (`reasoning_content` or `<think>` parsing)
- 🧠 **PLAN** — model-generated strategy steps, tracked with progress
- ✅ **TASKS** — execution units with status + remaining bullets
- ⚡ **Agent loop** — a real sense-think-act loop (`thought → action → observation`) that mutates plan/tasks, safe by design (no shell)
- 📡 **Loopback feed** — Server-Sent Events stream of every harness event (chat deltas, plan/task changes, agent iterations) for mobile + WebUI live views
- 🖥️ **Frontier WebUI** — dark glassmorphism, live thinking, plan/tasks sidebar, command bar
- ⌨️ **CLI** (`forge.py`) — chat, agent runs, plan/task control from the terminal
- 📱 **Mobile-ready API** — bind to `0.0.0.0` and command the DGX from the phone over Tailscale, same as SparkPulse

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

## API (mobile contract)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/status` | Router roster + DGX telemetry summary |
| POST | `/api/chat` | One-shot chat `{session?, message, model?}` |
| GET | `/api/chat/stream?session&message&model` | SSE chat stream (tokens + thinking) |
| GET | `/api/feed` | SSE harness event feed (`?since=<id>` to resume) |
| GET/POST | `/api/plan` | Read / set goal; `POST /api/plan/generate {goal}` |
| GET/POST/PATCH | `/api/tasks` | Task board; `PATCH /api/tasks {id, status?}` |
| POST | `/api/agent/run` | Agent loop `{goal, max_steps}` (also GET `/api/agent/run?goal=` for SSE) |
| GET | `/api/sessions`, `/api/history?session=` | Chat session store |

Optional auth: start with `--token <t>` and send `Authorization: Bearer <t>`.

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and the research base in
[docs/RESEARCH-frontier-harnesses-2026.md](docs/RESEARCH-frontier-harnesses-2026.md).
Roadmap and remaining work: [docs/PLAN.md](docs/PLAN.md).

## Relationship to SparkPulse

SparkPulse (app + server) stays the telemetry/mobile dashboard. SparkForge consumes the
same router and can be reached from the same phone; a future bridge task (see PLAN)
will surface SparkForge inside the SparkPulse app as a "Command" tab.
