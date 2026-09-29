# SparkForge v0.2 — acceptance evidence

*Claim → command → output → number. Nothing below is asserted without a run.*

**Result: 8/8 checks passed** by `tests/v02_acceptance.py` (run `2026-09-29T10:10:58`
against `http://127.0.0.1:8790`, code = commit `314ed16`), plus an **independent
re-verification** (JAG-35, this document's second section) that reproduces both
acceptance criteria by hand: an agent run executing a real sandboxed shell command
with a recorded approval and an observation, and an MCP session that receives a reply.

## Environment

| what | value |
|---|---|
| host | `Linux 7.0.0-1019-nvidia aarch64` |
| docker | `29.6.2` (backend in use, image `alpine:latest`) |
| bubblewrap | `bubblewrap 0.9.0` (unusable here: `apparmor_restrict_unprivileged_userns=1` blocks unprivileged user namespaces) |
| nsjail | `not installed` |
| router model | `nex-n25-mini-uncensored-q8` |

## Automated checks (`python3 tests/v02_acceptance.py` → 8/8)

### PASS A. real sandbox backend

```
backend=docker isolated=True | docker=docker 29.6.2 / image alpine:latest; bwrap=bwrap: bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted; nsjail=nsjail binary not found
```

### PASS G. tool registry + allowlist

```
tools=['browser', 'fs.read', 'fs.write', 'git', 'http', 'shell'] shell.approval=required enabled=['fs.read', 'fs.write', 'git', 'http', 'shell']
```

### PASS H. destructive action is hard-denied

```
status=blocked reason=matches hard-deny pattern 'rm\\s+-rf\\s+/(\\s|$)'
```

### PASS B. agent run → sandboxed shell with recorded approval + observation

```
approval=5779f60e31 decided_by=acceptance-test status=approved | sandbox=docker(alpine:latest) exit=0 approval_id=5779f60e31 duration_ms=217 | observation='[shell] exit=0 backend=docker(alpine:latest) sandboxed=True\nstdout: 2026-09-29T08:10:29Z\nkernel=7.0.0-1019-nvidia'
```

### PASS D. HITL pause / resume / abort mid-run

```
run=run_7fe7c067 pause->paused (observed paused) resume->running abort->aborting final=aborted blocked_on_approval=25363ba1eb
```

### PASS C. model-driven agent run uses a tool (informational)

```
model=nex-n25-mini-uncensored-q8 run_id=run_1c413ed9 steps=7 tool_calls=6 executed_in_sandbox=6 approvals=['4e3efcc274', '6d2ccd156d', '41b79f0d1a', 'dc3c2f95c8', 'dc16983b04', 'e51f36c389']
```

### PASS E. MCP session over stdio (initialize / tools/list / tools/call)

```
server=sparkforge protocol=2025-06-18 tools=8 ['sparkforge_status', 'sparkforge_chat', 'sparkforge_plan', 'sparkforge_tasks', 'sparkforge_agent_run', 'sparkforge_feed', 'sparkforge_tools', 'sparkforge_approvals'] | status_reply_chars=1739 | chat_reply='{"session": "1cb824b68795", "reply": "MCP-OK"}'
```

### PASS F. MCP over HTTP (POST /mcp)

```
server=sparkforge tools=8 tools_call_chars=5371
```

## Independent re-verification (JAG-35, 2026-09-29 ~10:11)

Run by hand against the same instance, **not** through the acceptance script — every
block below is the literal tool output. Restart a clean instance first:

```bash
cd /home/jagones/Repositories/sparkforge && ./run.sh   # :8790
```

### 1. Acceptance criterion A — agent run → real shell in sandbox, recorded approval, observation

Deterministic 2-step script (`/api/agent/run` with `script`), approval decided by a
human actor `jag35-crush`:

```
run_id: run_684e5723 | run status: done
approval_id: e65e4b7e90 | decided_by: jag35-crush | approval status: approved
tool_result: sandboxed=True backend=docker(alpine:latest) exit=0 approval_status=approved
tool command: mkdir -p jag35 && echo 'sparkforge v0.2 independent run' > jag35/proof.txt && \
              cat jag35/proof.txt && uname -srm && (wget -T3 -q -O- http://1.1.1.1 >/dev/null 2>&1 && echo NET_OK || echo NET_BLOCKED)
stdout:
sparkforge v0.2 independent run
Linux 7.0.0-1019-nvidia aarch64
NET_BLOCKED
observation:
[shell] exit=0 backend=docker(alpine:latest) sandboxed=True
stdout: sparkforge v0.2 independent run
Linux 7.0.0-1019-nvidia aarch64
NET_BLOCKED
```

The approval is durably recorded (`data/approvals-v02.json`, id `e65e4b7e90`,
`run_id: run_684e5723`, `decided_by: jag35-crush`). Note the `NET_BLOCKED` line: the
network is unreachable *inside the agent's own sandboxed command*, which is exactly the
sandbox-first guarantee.

### 2. Acceptance criterion B — Paperclip opens an MCP session and gets a response

Raw stdio session against `mcp_server.py` (`initialize` → `tools/list` → `tools/call`):

```
initialize -> {"name": "sparkforge", "title": "SparkForge agent harness", "version": "0.2.0"} protocol 2025-06-18
tools/list -> ['sparkforge_status', 'sparkforge_chat', 'sparkforge_plan', 'sparkforge_tasks',
               'sparkforge_agent_run', 'sparkforge_feed', 'sparkforge_tools', 'sparkforge_approvals']
tools/call sparkforge_status -> chars=1480 head={"service": "sparkforge", "version": "0.2.0", "ts": ..., "router": "http://127.0.0.1:8080", "models": ...
```

Reproduce:

```bash
printf '%s\n' \
'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"paperclip","version":"1.0"}}}' \
'{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
'{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"sparkforge_status","arguments":{}}}' \
| python3 mcp_server.py
```

### 3. Sandbox is *real* (raw docker, same flags as `sandbox.py`)

```
$ docker run --rm --network none --read-only --tmpfs /tmp --cap-drop ALL \
    --security-opt no-new-privileges --user 65534:65534 alpine:latest sh -c '...'
hostname=332e895fef1b      # container, not the host (host=spark-6263)
uid=65534 gid=65534        # nobody, non-root
network:
  NET_BLOCKED              # --network none
rootfs (/): bin dev etc ... var    # container root, host FS not visible
write to / :
touch: /nope: Read-only file system
```

### 4. Deny paths (no approval can override)

```
$ curl -sX POST :8790/api/tools/call -d '{"tool":"shell","args":{"command":"rm -rf /"}}'
{"status": "blocked", "reason": "matches hard-deny pattern 'rm\\s+-rf\\s+/(\\s|$)'"}

$ curl -sX POST :8790/api/tools/call -d '{"tool":"kernel.exec","args":{}}'
{"status": "error", "error": "unknown tool 'kernel.exec'"}
```

## Reproduce everything

```bash
cd /home/jagones/Repositories/sparkforge
./run.sh &                        # canonical instance on :8790
python3 tests/v02_acceptance.py   # the 8 automated checks
```

Machine-readable report of the automated run: `data/v02-acceptance.json`.
