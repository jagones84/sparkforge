#!/usr/bin/env python3
"""JAG-57 v2 — capture agent result body (trace is inline, /trace endpoint 404s)."""
import json
import sys
import time
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8790"
TOKEN = "REDACTED-COMPROMISED-TOKEN"
HDR = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def post(path, body, timeout=900):
    r = urllib.request.Request(
        f"{BASE}{path}", data=json.dumps(body).encode(),
        headers=HDR, method="POST")
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode())


def get(path, timeout=60):
    r = urllib.request.Request(f"{BASE}{path}", headers=HDR)
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode())


print("=== STEP 1: list live MCP clients ===")
s, d = get("/api/mcp/clients")
print(json.dumps(d, indent=2))

print("\n=== STEP 2: trigger agent run ===")
GOAL = (
    "First call the `skills` tool (action=list) to discover skill categories. "
    "Then call the `skills` tool (action=read, name=paperclip) to load a skill. "
    "Then call a tool exposed by the `pmcp` MCP client (the tool name starts with `pmcp__`). "
    "Finally use `fs.write` to write a 1-line summary to "
    "/home/jagones/Repositories/sparkforge/data/llm_uses_tools.txt saying 'skills+tools+MCP verified'. "
    "Stop after that file is written."
)
s, d = post("/api/agent/run", {"goal": GOAL, "max_steps": 10}, timeout=900)
run_id = d.get("run_id")
print(f"status={s} run_id={run_id} status_done={d.get('status')}")
print(f"summary={d.get('summary','')[:300]}")

trace = d.get("trace") or []
print(f"\ninline trace items={len(trace)}")
print(f"trace keys (first item)={list(trace[0].keys()) if trace else 'EMPTY'}")
print("\n--- all trace steps ---")
for i, t in enumerate(trace):
    role = t.get("role") or t.get("event") or t.get("type") or "?"
    txt = (t.get("content") or t.get("text") or t.get("summary") or t.get("message") or "")
    tool = t.get("tool") or ""
    args = t.get("args") or t.get("tool_args") or ""
    out = t.get("output") or t.get("observation") or t.get("result") or ""
    print(f"[{i:02d}] role={role} tool={tool} args={str(args)[:140]}")
    if txt:
        print(f"     text={str(txt)[:200]}")
    if out:
        print(f"     out={str(out)[:300]}")

print("\n=== STEP 3: evidence of skills/MCP/fs calls ===")
tool_calls = [t for t in trace if t.get("tool")]
print(f"tool_calls_count={len(tool_calls)}")
for tc in tool_calls:
    print(f"  - tool={tc.get('tool')} args={str(tc.get('args',''))[:140]}")

# Specific checks
called_skills = any(t.get("tool") == "skills" for t in trace)
called_pmcp = any(str(t.get("tool","")).startswith("pmcp__") for t in trace)
called_fs = any(t.get("tool") == "fs.write" for t in trace)
print(f"\nCHECK A: skills tool called = {called_skills}")
print(f"CHECK B: pmcp__* tool called = {called_pmcp}")
print(f"CHECK C: fs.write tool called = {called_fs}")

print("\n=== STEP 4: file written check ===")
import subprocess
out = subprocess.run(
    ["ssh", "dgx", "cat /home/jagones/Repositories/sparkforge/data/llm_uses_tools.txt 2>/dev/null"],
    capture_output=True, text=True, timeout=20)
print(f"file_exists={bool(out.stdout.strip())}")
print(f"file_content={out.stdout.strip()[:300]!r}")

print(f"\n=== STEP 5: graph for run {run_id} ===")
try:
    s, g = get(f"/api/runs/{run_id}/graph")
    nodes = (g or {}).get("nodes") or []
    print(f"graph nodes={len(nodes)}")
    for n in nodes[:10]:
        print(f"  - {n.get('status')} {n.get('label','')[:100]} ev={len(n.get('evidence',[]))}")
except Exception as e:
    print(f"graph err: {e}")
