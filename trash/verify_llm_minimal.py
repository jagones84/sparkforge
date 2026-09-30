#!/usr/bin/env python3
"""JAG-57 v3 — minimal agent goals to isolate the loop bug."""
import json
import urllib.request

BASE = "http://127.0.0.1:8790"
TOKEN = "REDACTED-COMPROMISED-TOKEN"
HDR = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def post(p, body, timeout=300):
    r = urllib.request.Request(f"{BASE}{p}", data=json.dumps(body).encode(),
                                headers=HDR, method="POST")
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode())


CASES = [
    ("GOAL-1", "Use the skills tool with action=read and name=paperclip. "
               "After reading it, call action=finish with summary=done.", 4),
    ("GOAL-2", "Call the fs.read tool on /etc/hostname. Then call action=finish.", 4),
    ("GOAL-3", "Use skills action=read name=brainstorming. Then action=finish summary=read.", 4),
]

for name, goal, mx in CASES:
    print(f"\n=== {name} max_steps={mx} ===")
    print(f"GOAL: {goal[:120]}")
    s, d = post("/api/agent/run", {"goal": goal, "max_steps": mx}, timeout=300)
    print(f"status={d.get('status')} summary={d.get('summary','')[:120]}")
    trace = d.get("trace") or []
    print(f"trace_items={len(trace)}")
    for i, t in enumerate(trace):
        tool = t.get("tool")
        args = t.get("args")
        obs = t.get("observation") or t.get("tool_result")
        thr = t.get("thought", "")
        if tool:
            print(f"  [{i:02d}] tool={tool} args={str(args)[:80]}")
            print(f"       obs_head={str(obs)[:200]}")
        elif thr:
            print(f"  [{i:02d}] thought={str(thr)[:160]}")
    called = [t.get("tool") for t in trace if t.get("tool")]
    print(f"  called_tools={called}")
