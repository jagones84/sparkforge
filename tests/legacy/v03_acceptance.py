#!/usr/bin/env python3
"""SparkForge v0.3 acceptance — evidence, not claims.

Verifies, against a *running* SparkForge, with command + output + numbers:
  A. checkpoint / resume / rollback: create with idempotency key (same key →
     same id), mutate plan+tasks, rollback, state restored; auto-checkpoint on
     agent runs (per-run idempotency key)
  B. context engineering: compaction under a token budget with retrieval
     stats; memory written in one step is retrieved for a later message
  C. multi-model routing: role selection from the live router roster with a
     fallback chain that ends on the DeepSeek alias; live failover path
     verified offline with a stubbed router call
  D. MCP: the new sparkforge_checkpoint / sparkforge_context /
     sparkforge_routing tools answer over POST /mcp

Usage:  python3 tests/v03_acceptance.py [--base http://127.0.0.1:8791]
Exit code 0 iff every check passed. Prints a JSON report and writes
data/v03-acceptance.json.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.environ.get("SPARKFORGE_URL", "http://127.0.0.1:8791")
TOKEN = os.environ.get("SPARKFORGE_TOKEN")

results = []


def http(method, path, body=None, timeout=600):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if TOKEN:
        headers["Authorization"] = "Bearer " + TOKEN
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"error": "HTTP %d" % e.code}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


def check(name, ok, evidence, **extra):
    rec = {"check": name, "ok": bool(ok), "evidence": evidence, **extra}
    results.append(rec)
    print("\n%s %s\n   %s" % ("PASS" if ok else "FAIL", name, evidence))
    return ok


# ------------------------------------------------------- checkpoints (A) ----

def check_checkpoint_idempotency():
    key = "v03-acceptance-%d" % int(time.time())
    c1 = http("POST", "/api/checkpoints",
              {"label": "v0.3 acceptance", "idempotency_key": key})
    c2 = http("POST", "/api/checkpoints",
              {"label": "v0.3 acceptance", "idempotency_key": key})
    ok = (c1.get("id") and c1.get("id") == c2.get("id")
          and c2.get("idempotent") is True
          and c1["sizes"]["tasks"] >= 0)
    return check("A1. checkpoint create is idempotent",
                 ok, "create x2 key=%s -> id=%s, 2nd call idempotent=%s, sizes=%s"
                 % (key, c1.get("id"), c2.get("idempotent"), c1.get("sizes")),
                 checkpoint_id=c1.get("id"), key=key)


def check_rollback_restores_state():
    cps = http("GET", "/api/checkpoints").get("checkpoints", [])
    marker_plan = "V03-ROLLBACK-MARKER-PLAN %d" % int(time.time())
    marker_task = "v03 rollback marker task %d" % int(time.time())
    http("POST", "/api/plan", {"goal": marker_plan})
    http("POST", "/api/tasks", {"title": marker_task})
    after_mut = http("GET", "/api/plan")
    tasks_after = http("GET", "/api/tasks")
    plan_has = marker_plan in json.dumps(after_mut)
    task_has = any(marker_task in t.get("title", "") for t in tasks_after.get("tasks", []))
    cp_id = next((c["id"] for c in cps if c.get("label") == "v0.3 acceptance"), None)
    if not cp_id:
        return check("A2. rollback restores plan+tasks", False,
                     "no 'v0.3 acceptance' checkpoint found among %d" % len(cps))
    rb = http("POST", "/api/checkpoints/%s/rollback" % cp_id, {})
    plan_restored = http("GET", "/api/plan")
    tasks_restored = http("GET", "/api/tasks")
    gone = (marker_plan not in json.dumps(plan_restored)
            and not any(marker_task in t.get("title", "")
                        for t in tasks_restored.get("tasks", [])))
    rb2 = http("POST", "/api/checkpoints/%s/rollback" % cp_id, {})
    return check("A2. rollback restores plan+tasks (idempotent re-run)",
                 rb.get("ok") and plan_has and task_has and gone and rb2.get("ok"),
                 "marker visible after mutation (plan=%s task=%s); after rollback "
                 "markers gone=%s; rollback_count=%s"
                 % (plan_has, task_has, gone,
                    rb2.get("restored", {}).get("rollback_count")))


def check_agent_auto_checkpoint():
    script = [
        {"thought": "note the goal", "action": "note", "detail": "v0.3 auto-checkpoint probe"},
        {"thought": "done", "action": "finish", "summary": "auto-checkpoint probe complete"},
    ]
    res = http("POST", "/api/agent/run",
               {"goal": "v0.3 auto checkpoint probe", "max_steps": 2, "script": script},
               timeout=300)
    rid = res.get("run_id")
    cps = http("GET", "/api/checkpoints").get("checkpoints", [])
    auto = next((c for c in cps if c.get("idempotency_key") == "agent-run:" + rid), None)
    return check("A3. agent run takes an idempotent auto-checkpoint",
                 bool(rid) and auto is not None,
                 "run_id=%s -> checkpoint %s (by %s, tasks=%s, plan_steps=%s)"
                 % (rid, auto and auto.get("id"), auto and auto.get("created_by"),
                    auto and auto["sizes"].get("tasks"),
                    auto and auto["sizes"].get("plan_steps")))


# ------------------------------------------------- context engineering (B) ----

def check_context_compaction_and_retrieval():
    marker = "SPARKFORGE-V03-MEMORY-MARKER-%d" % int(time.time())
    mem = http("POST", "/api/memory", {"kind": "memory.store",
                                       "content": marker + " permanent vector note"})
    sess = http("POST", "/api/chat", {"message": "v0.3 context test, reply briefly"})
    sid = sess.get("session")
    turns = 1
    for i in range(3):
        filler = ("filler turn %d. " % i) + ("lorem ipsum analysis detail repeated here. " * 20)
        http("POST", "/api/chat", {"session": sid, "message": filler[:400]})
        turns += 1
    pv = http("POST", "/api/context/preview",
              {"session": sid, "message": marker, "budget_tokens": 200})
    hits = pv.get("retrieval_hits", 0)
    samples = json.dumps(pv.get("retrieval_samples", []))
    ok = (pv.get("compaction", {}).get("compacted", 0) >= 0
          and pv.get("transcript_messages", 0) >= turns
          and pv.get("final_tokens", 10**9) < pv.get("compaction", {}).get("input_tokens", 0)
          and hits >= 1 and marker.split("-MARKER-")[0] in samples.replace("-MARKER-", "-MARKER-"))
    hit_marker = marker[:30] in samples
    return check("B1. compaction + budget + cross-session memory retrieval",
                 ok and hit_marker,
                 "session=%s turns=%d compacted=%s final_tokens=%s < input_tokens=%s; "
                 "memory hits=%d marker_in_hits=%s"
                 % (sid, turns, pv.get("compaction", {}).get("compacted"),
                    pv.get("final_tokens"),
                    pv.get("compaction", {}).get("input_tokens"), hits, hit_marker),
                 memory_record_id=str(mem.get("ts")), session=sid)


# ---------------------------------------------------------- routing (C) ----

def check_routing_status():
    st = http("GET", "/api/routing")
    roster = [m["alias"] for m in st.get("roster", [])]
    chat = st.get("roles", {}).get("chat", {})
    sel, chain = chat.get("selected"), chat.get("chain") or []
    loaded = [m["alias"] for m in st.get("roster", []) if m.get("loaded")]
    sel_ok = sel is not None and (not loaded or sel in loaded)
    last = chain[-1] if chain else ""
    return check("C1. role-based routing selects a live model with DeepSeek fallback",
                 sel_ok and any("deepseek" in a.lower() for a in roster) and
                 "deepseek" in last.lower(),
                 "roster=%s; chat.selected=%s (loaded=%s); chat chain=%s (last=%s)"
                 % (roster[:4], sel, sel in loaded if sel else None, chain, last))


def check_fallback_logic_offline():
    """Drive server.stream_with_fallback with a stubbed router: the primary
    model must fail over to the next chain entry (evidence of the live path)."""
    sys.path.insert(0, os.path.join(REPO, "src"))
    os.environ.setdefault("SPARKFORGE_DB", os.path.join(REPO, "data", "events.db"))
    from sparkforge import server

    calls = []

    def fake_stream(messages, model, on_delta, timeout=300, usage=None):
        calls.append(model)
        if model == "primary-broken":
            raise RuntimeError("router: model failed (stub)")
        return "ok", ""

    orig = server._router_stream
    server._router_stream = fake_stream
    try:
        # force a chain of known aliases by stubbing the roster too
        orig_roster = server.router_models
        server.router_models = lambda: [
            {"alias": "primary-broken", "status": "loaded", "loaded": True},
            {"alias": "deepseek-v4-flash-q2", "status": "unloaded", "loaded": False},
        ]
        orig_pick = server.routing.pick
        server.routing.pick = lambda role, preferred=None: "primary-broken"
        answer, think, used = server.stream_with_fallback(
            [{"role": "user", "content": "x"}], None, "chat", lambda c, t: None)
    finally:
        server._router_stream = orig
        server.routing.pick = orig_pick
        try:
            server.router_models = orig_roster
        except Exception:
            pass
    ok = calls == ["primary-broken", "deepseek-v4-flash-q2"] and used == "deepseek-v4-flash-q2"
    return check("C2. live-call fallback walks the chain to DeepSeek",
                 ok, "router calls=%s -> model_used=%s" % (calls, used))


# --------------------------------------------------------------- MCP (D) ----

def check_mcp_v03_tools():
    tlist = http("POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = [t["name"] for t in tlist.get("result", {}).get("tools", [])]
    need = ["sparkforge_checkpoint", "sparkforge_context", "sparkforge_routing"]
    have = all(t in names for t in need)
    ck = http("POST", "/mcp", {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                               "params": {"name": "sparkforge_checkpoint",
                                          "arguments": {"action": "list"}}})
    ck_ok = not ck.get("result", {}).get("content", [{}])[0].get("isError", False)
    rt = http("POST", "/mcp", {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                               "params": {"name": "sparkforge_routing",
                                          "arguments": {}}})
    rt_text = rt.get("result", {}).get("content", [{}])[0].get("text", "")
    return check("D1. v0.3 tools available over MCP (POST /mcp)",
                 have and ck_ok and "roles" in rt_text,
                 "tools/list has %s; checkpoint list isError=%s; routing text has "
                 "roles=%s (tools=%d total)"
                 % (need, not ck_ok, "roles" in rt_text, len(names)))


# ------------------------------------------------------------------ main ----

def main():
    global BASE, TOKEN
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    args = ap.parse_args()
    BASE = args.base
    print("SparkForge v0.3 acceptance against %s" % BASE)

    check_checkpoint_idempotency()
    check_rollback_restores_state()
    check_agent_auto_checkpoint()
    check_context_compaction_and_retrieval()
    check_routing_status()
    check_fallback_logic_offline()
    check_mcp_v03_tools()

    passed = sum(1 for r in results if r["ok"])
    report = {"base": BASE, "ts": time.time(), "passed": passed,
              "total": len(results), "results": results}
    print("\n=== v0.3 acceptance: %d/%d checks passed ===" % (passed, len(results)))
    out = os.path.join(REPO, "data", "v03-acceptance.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print("report written to %s" % out)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())