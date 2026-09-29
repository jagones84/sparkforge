# SparkForge v0.2 — acceptance evidence

*Generated 2026-09-29T10:05:08 by `tests/v02_acceptance.py` — every claim below is a command with output.*

**Result: 8/8 checks passed** against `http://127.0.0.1:8790` (the canonical instance, same code as commit `e3f7621`).

## Environment

| what | value |
|---|---|
| host | `Linux 7.0.0-1019-nvidia aarch64` |
| docker | `29.6.2` |
| bubblewrap | `bubblewrap 0.9.0` (unusable here: `apparmor_restrict_unprivileged_userns=1` blocks unprivileged user namespaces) |
| nsjail | `not installed` |
| router model | `['nex-n25-mini-uncensored-q8']` |

## Checks

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

### PASS B. agent run -> sandboxed shell with recorded approval + observation

```
approval=982873b20c decided_by=acceptance-test status=approved | sandbox=docker(alpine:latest) exit=0 approval_id=982873b20c duration_ms=201 | observation='[shell] exit=0 backend=docker(alpine:latest) sandboxed=True\nstdout: 2026-09-29T08:04:46Z\nkernel=7.0.0-1019-nvidia'
```

command run: `mkdir -p out && date -u +%Y-%m-%dT%H:%M:%SZ > out/stamp.txt && printf 'kernel=%s\n' "$(uname -r)" >> out/stamp.txt && cat out/stamp.txt`

run id: `run_992dbc27`

### PASS D. HITL pause / resume / abort mid-run

```
run=run_e86f6167 pause->paused (observed paused) resume->running abort->aborting final=aborted blocked_on_approval=f22f092940
```

### PASS C. model-driven agent run uses a tool (informational)

```
model=nex-n25-mini-uncensored-q8 run_id=run_b240ee7f steps=7 tool_calls=6 executed_in_sandbox=6 approvals=['7b1ae46d58', '2c5c051cad', 'cbc74fe6d8', '6164069837', '77ab0fd03c', '27a4c50d7a'] | decisions=['7b1ae46d58', '2c5c051cad', 'cbc74fe6d8', '6164069837', '77ab0fd03c', '27a4c50d7a']
```

### PASS E. MCP session over stdio (initialize / tools/list / tools/call)

```
server=sparkforge protocol=2025-06-18 tools=8 ['sparkforge_status', 'sparkforge_chat', 'sparkforge_plan', 'sparkforge_tasks', 'sparkforge_agent_run', 'sparkforge_feed', 'sparkforge_tools', 'sparkforge_approvals'] | status_reply_chars=1739 | chat_reply='{\n  "session": "3ddbafba5c41",\n  "reply": "MCP-OK",\n  "reasoning": null\n}'
```

### PASS F. MCP over HTTP (POST /mcp)

```
server=sparkforge tools=8 tools_call_chars=5371
```

## Reproduce

```bash
cd /home/jagones/Repositories/sparkforge
./run.sh &                        # canonical instance on :8790
python3 tests/v02_acceptance.py   # defaults to http://127.0.0.1:8790
```
