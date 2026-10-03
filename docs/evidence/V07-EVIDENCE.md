# SparkForge v0.7 — EVIDENCE (JAG-54: MCP client collegato + fs.edit)

Data: 2026-09-29 — verified by `tests/v07_mcp_fsedit.py` (14/14 PASS, report:
`data/v07-acceptance.json`).

## 1. config/mcp_clients.yaml — pmcp reale

`config/` prima conteneva solo `routing.yaml` e `tools.yaml`; ora:

```yaml
env_files:
  - ~/.hermes/.env          # same source Hermes uses for PMCP_AUTH_TOKEN

clients:
  pmcp:
    url: http://127.0.0.1:3344/mcp
    enabled: true
    headers:
      Authorization: Bearer ${PMCP_AUTH_TOKEN}
```

`mcp_client.py` fixes/upgrade (streamable-HTTP):
- `_send_raw` HTTP branch sent the JSON-RPC request **without `id` and without
  `"jsonrpc":"2.0"`** → pmcp rejected every call with -32602. Fixed: `id` +
  `jsonrpc: 2.0` added; `notifications/*` sent without `id`.
- captures `Mcp-Session-Id` from the initialize response and echoes it back.
- parses SSE (`text/event-stream`) responses, not only bare JSON.
- supports per-client `headers` (with `${VAR}` expansion) and repo-level
  `env_files`.
- fixed `log()` which printed literal `%s` placeholders.

Evidence (client initialize + tools/list reali):
```
[mcp-client] pmcp: initialized (protocol 2025-06-18)
[mcp-client] pmcp: 26 tools available
A1 PASS pmcp connected {'pmcp': {'connected': True, 'tools': 26}}
A2 PASS tools/list real 26 external tools
A3 PASS external tools in registry catalog catalog=26 external=26
```

## 2. Tool MCP nel agent-loop (routing, non solo elenco)

- `registry.tool_names()/tool_spec()` merge external tools from `mcp_client`
  (schema = tools/list `inputSchema`; policy default `approval: required`,
  per-tool override in `config/tools.yaml`, e.g. read-only gateway probes
  `pmcp__gateway.health|config_status|tasks_list` → `auto`).
- `tools.execute()` routes unknown tools containing `__` to
  `mcp_client.call_tool()`; the observation is the real MCP output:
```
## approval.auto  {"tool": "pmcp__gateway.health", "id": "26dd6c6a17"}
## tool.call      {"tool": "pmcp__gateway.health", "args": {}}
## tool.result    {"ok": true, "exit_code": 0, "backend": "mcp(pmcp)"}
## agent.observation  "[pmcp__gateway.health] exit=0 backend=mcp(pmcp) ...
stdout: { \"revision_id\": \"rev-1790715131873-231fu8\", \"servers\": [ ... ]"
```
- Live agent run (real LLM via router :8080): run `run_5c4efb55` executed
  `pmcp__gateway.health` 5/5 iterations, each with a real MCP observation;
  also gated via `POST /api/tools/call` → `status: executed`,
  `backend: mcp(pmcp)`.

## 3. fs.edit chirurgico

`registry.TOOL_SCHEMAS["fs.edit"]` + `tools._fs_edit` + policy in
`config/tools.yaml` (roots `data/sandbox`, approval `required`):
- search/replace esatto; `replace_all` opzionale.
- rifiuta search assente e match ambiguo (nessuna scrittura parziale).

Test evidence (C1..C4 in `tests/v07_mcp_fsedit.py`):
```
C1 PASS search not found -> error        (file invariato)
C2 PASS ambiguous match -> error         (2 match, replace_all=false)
C3 PASS single replacement  replacements=1
C4 PASS replace_all         replacements=2
```

Also executed through the approval gate on a live instance:
`POST /api/tools/call {tool: fs.edit}` → pending → approve → `status:
executed`, `replacements: 1`, file content updated on disk.

## Regressioni

- `tests/v062_session_persistence.py` → 11/11 PASS
- `tests/v06_taskgraph.py` → 15/15 PASS
