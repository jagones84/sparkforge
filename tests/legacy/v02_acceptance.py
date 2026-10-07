#!/usr/bin/env python3
"""SparkForge v0.2 acceptance — evidence, not claims.

Verifies, against a *running* SparkForge, with command + output + numbers:
  A. sandbox backend is real and isolated (network blocked, scratch /work)
  B. a deterministic agent run executes a REAL shell command in the sandbox,
     with a recorded approval, and the output comes back as an observation
  C. the same loop is driven by the local model (best effort, reported)
  D. HITL: pause / resume / abort a run mid-flight via /api/agent/control
  E. MCP over stdio: Paperclip-style client opens a session, lists tools,
     and receives a response (initialize -> tools/list -> tools/call)
  F. MCP over HTTP: POST /mcp honours initialize + tools/call

Usage:  python3 tests/v02_acceptance.py [--base http://127.0.0.1:8790]
Exit code 0 iff every check passed. Prints a JSON report at the end.
"""

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASE = os.environ.get("SPARKFORGE_URL", "http://127.0.0.1:8790")
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


# ---------------------------------------------------------------- helpers ---

class AutoApprover(threading.Thread):
    """Background worker that approves any pending approval for a run."""

    def __init__(self, tag, decision="approve", poll=0.25):
        super().__init__(daemon=True)
        self.tag, self.decision, self.poll = tag, decision, poll
        self.stop = False
        self.seen = []

    def run(self):
        while not self.stop:
            out = http("GET", "/api/approvals?status=pending", timeout=10)
            for rec in out.get("approvals", []):
                if rec["id"] in self.seen:
                    continue
                self.seen.append(rec["id"])
                print("   [%s] deciding %s (%s) -> %s"
                      % (self.tag, rec["id"], rec["summary"][:60], self.decision))
                http("POST", "/api/approvals/" + rec["id"],
                     {"decision": self.decision, "by": self.tag}, timeout=30)
            time.sleep(self.poll)


# ---------------------------------------------------------------- checks ---

def check_sandbox():
    probe = http("GET", "/api/sandbox?force=1")
    avail = probe.get("available", {})
    detail = "; ".join("%s=%s" % (k, v["detail"][:70]) for k, v in avail.items())
    return check("A. real sandbox backend",
                 probe.get("isolated") is True and probe.get("backend") != "none",
                 "backend=%s isolated=%s | %s" % (probe.get("backend"), probe.get("isolated"), detail))


def check_scripted_tool_run():
    """Deterministic: script -> shell (needs approval) -> approve -> sandbox -> observation."""
    cmd = ("mkdir -p out && date -u +%Y-%m-%dT%H:%M:%SZ > out/stamp.txt && "
           "printf 'kernel=%s\\n' \"$(uname -r)\" >> out/stamp.txt && cat out/stamp.txt")
    script = [
        {"thought": "verify the sandbox by writing and reading a file",
         "action": "tool", "tool": "shell", "args": {"command": cmd}},
        {"thought": "report the observed output", "action": "finish",
         "summary": "sandbox shell command executed with approval"},
    ]
    box = {}

    def run():
        box["res"] = http("POST", "/api/agent/run",
                          {"goal": "prove the sandbox works", "max_steps": 3, "script": script},
                          timeout=300)

    th = threading.Thread(target=run, daemon=True)
    th.start()
    # wait for the approval to appear, then decide it as a human
    aid, approval = None, None
    for _ in range(120):
        out = http("GET", "/api/approvals?status=pending", timeout=10)
        if out.get("approvals"):
            approval = out["approvals"][0]
            aid = approval["id"]
            break
        if not th.is_alive():
            break
        time.sleep(0.25)
    approved_by = None
    if aid:
        decided = http("POST", "/api/approvals/" + aid,
                       {"decision": "approve", "by": "acceptance-test"}, timeout=30)
        approved_by = decided.get("decided_by")
    th.join(timeout=180)
    res = box.get("res") or {"error": "run did not return"}
    trace = res.get("trace") or []
    tool_entry = next((t for t in trace if t.get("action") == "tool"), {})
    meta = tool_entry.get("tool_result") or {}
    obs = tool_entry.get("observation") or ""
    stdout = meta.get("stdout", "")
    ok = (aid and approved_by == "acceptance-test" and meta.get("approval_status") == "approved"
          and meta.get("sandboxed") is True and meta.get("exit_code") == 0
          and meta.get("approval_id") == aid and "kernel=" in stdout)
    evidence = ("approval=%s decided_by=%s status=%s | sandbox=%s exit=%s approval_id=%s "
                "duration_ms=%s | observation=%r"
                % (aid, approved_by, meta.get("approval_status"), meta.get("sandbox_backend"),
                   meta.get("exit_code"), meta.get("approval_id"), meta.get("duration_ms"),
                   obs[:160]))
    return check("B. agent run -> sandboxed shell with recorded approval + observation",
                 ok, evidence,
                 command=cmd, run_id=res.get("run_id"), stdout=stdout)


def check_model_tool_run():
    goal = ("Usa il tool `shell` per eseguire esattamente il comando: "
            "`mkdir -p out && uname -a > out/uname.txt && cat out/uname.txt` — "
            "poi riporta l'output e chiama finish.")
    approver = AutoApprover("acceptance-auto")
    approver.start()
    res = http("POST", "/api/agent/run", {"goal": goal, "max_steps": 6}, timeout=600)
    approver.stop = True
    trace = res.get("trace") or []
    tools_used = [t for t in trace if t.get("action") == "tool"]
    executed = [t for t in tools_used
                if (t.get("tool_result") or {}).get("sandboxed") is True]
    approval_ids = [t["tool_result"].get("approval_id") for t in executed]
    evidence = ("model=%s run_id=%s steps=%d tool_calls=%d executed_in_sandbox=%d "
                "approvals=%s | decisions=%s"
                % (res.get("model"), res.get("run_id"), len(trace), len(tools_used),
                   len(executed), approval_ids, approver.seen))
    # This one is model-dependent: report it, but only the deterministic run gates PASS.
    return check("C. model-driven agent run uses a tool (informational)",
                 len(executed) >= 1, evidence, model_run=res)


def check_hitl():
    script = [
        {"thought": "needs approval, so the run will block here",
         "action": "tool", "tool": "shell", "args": {"command": "mkdir -p out/hitl"}},
        {"action": "finish", "summary": "should never be reached after abort"},
    ]
    box = {}

    def run():
        box["res"] = http("POST", "/api/agent/run",
                          {"goal": "hitl demo", "max_steps": 3, "script": script}, timeout=300)

    th = threading.Thread(target=run, daemon=True)
    th.start()
    rid, pending = None, None
    for _ in range(160):  # wait for THIS run (goal='hitl demo') to appear, not just any run
        runs = http("GET", "/api/agent/runs", timeout=10).get("runs", [])
        for r in runs:
            if r.get("goal") == "hitl demo" and r.get("status") in ("running", "paused"):
                rid = r["id"]
                break
        if rid:
            break
        time.sleep(0.25)
    for _ in range(160):
        out = http("GET", "/api/approvals?status=pending", timeout=10)
        match = [a for a in out.get("approvals", []) if a.get("run_id") == rid]
        if match:
            pending = match[0]["id"]
            break
        time.sleep(0.25)

    paused = http("POST", "/api/agent/control", {"runId": rid, "action": "pause"}, timeout=20)
    time.sleep(0.6)
    mid = http("GET", "/api/agent/runs/" + str(rid), timeout=20)
    resumed = http("POST", "/api/agent/control", {"runId": rid, "action": "resume"}, timeout=20)
    time.sleep(0.6)
    aborted = http("POST", "/api/agent/control", {"runId": rid, "action": "abort"}, timeout=20)
    th.join(timeout=60)
    res = box.get("res") or {}
    final = http("GET", "/api/agent/runs/" + str(rid), timeout=20)
    # clean up the approval the aborted run was waiting on
    if pending:
        http("POST", "/api/approvals/" + pending, {"decision": "deny", "by": "cleanup"}, timeout=20)
    ok = (paused.get("status") == "paused" and mid.get("status") == "paused"
          and resumed.get("status") == "running" and aborted.get("status") == "aborting"
          and final.get("status") == "aborted" and res.get("status") == "aborted")
    evidence = ("run=%s pause->%s (observed %s) resume->%s abort->%s final=%s "
                "blocked_on_approval=%s"
                % (rid, paused.get("status"), mid.get("status"), resumed.get("status"),
                   aborted.get("status"), final.get("status"), pending))
    return check("D. HITL pause / resume / abort mid-run", ok, evidence)


def check_mcp_stdio():
    """Spawn the stdio MCP server and drive a real session."""
    env = dict(os.environ, SPARKFORGE_URL=BASE)
    if TOKEN:
        env["SPARKFORGE_TOKEN"] = TOKEN
    proc = subprocess.Popen([sys.executable, os.path.join(REPO, "mcp_server.py")],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, env=env, cwd=REPO)
    lock = threading.Lock()

    def send(obj):
        with lock:
            proc.stdin.write(json.dumps(obj) + "\n")
            proc.stdin.flush()

    def recv(timeout=60):
        line = proc.stdout.readline()
        return json.loads(line) if line.strip() else None

    transcript = []
    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2025-06-18",
                         "clientInfo": {"name": "paperclip-acceptance", "version": "1"},
                         "capabilities": {}}})
        init = recv()
        transcript.append(init)
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tlist = recv()
        transcript.append(tlist)
        send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
              "params": {"name": "sparkforge_status", "arguments": {}}})
        status = recv()
        transcript.append(status)
        send({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
              "params": {"name": "sparkforge_chat",
                         "arguments": {"message": "Rispondi con la parola: MCP-OK"}}})
        chat = recv()
        transcript.append(chat)
    finally:
        try:
            proc.stdin.close()
            proc.wait(timeout=10)
        except Exception:
            proc.kill()

    server_info = (init or {}).get("result", {}).get("serverInfo", {})
    tools = [t["name"] for t in (tlist or {}).get("result", {}).get("tools", [])]
    status_text = json.dumps(((status or {}).get("result", {}).get("content") or [{}])[0], ensure_ascii=False)
    chat_text = (((chat or {}).get("result", {}).get("content") or [{}])[0]
                 or {}).get("text", "")
    ok = (server_info.get("name") == "sparkforge" and len(tools) >= 5
          and "sandbox" in status_text and len(chat_text) > 0
          and (chat or {}).get("result", {}).get("isError") is False)
    evidence = ("server=%s protocol=%s tools=%d %s | status_reply_chars=%d | chat_reply=%r"
                % (server_info.get("name"), (init or {}).get("result", {}).get("protocolVersion"),
                   len(tools), tools, len(status_text), chat_text[:80]))
    return check("E. MCP session over stdio (initialize / tools/list / tools/call)",
                 ok, evidence, transcript=transcript)


def check_mcp_http():
    init = http("POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                 "params": {"protocolVersion": "2025-06-18"}}, timeout=30)
    tlist = http("POST", "/mcp", {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, timeout=30)
    call = http("POST", "/mcp", {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                 "params": {"name": "sparkforge_tools", "arguments": {}}}, timeout=60)
    name = init.get("result", {}).get("serverInfo", {}).get("name")
    ntools = len(tlist.get("result", {}).get("tools", []))
    text = ((call.get("result", {}).get("content") or [{}])[0] or {}).get("text", "")
    ok = name == "sparkforge" and ntools >= 5 and "shell" in text
    return check("F. MCP over HTTP (POST /mcp)", ok,
                 "server=%s tools=%d tools_call_chars=%d" % (name, ntools, len(text)))


def check_registry():
    cat = http("GET", "/api/tools")
    names = {t["name"]: t for t in cat.get("tools", [])}
    need = {"shell", "fs.read", "fs.write", "git", "http", "browser"}
    ok = need.issubset(names) and names["shell"]["approval"] == "required"
    return check("G. tool registry + allowlist", ok,
                 "tools=%s shell.approval=%s enabled=%s"
                 % (sorted(names), names.get("shell", {}).get("approval"),
                    [n for n, t in names.items() if t["enabled"]]))


def check_deny():
    out = http("POST", "/api/tools/call", {"tool": "shell", "args": {"command": "rm -rf /"}}, timeout=60)
    ok = out.get("status") == "blocked"
    return check("H. destructive action is hard-denied", ok,
                 "status=%s reason=%s" % (out.get("status"), str(out.get("reason"))[:90]))


def main():
    global BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    args = ap.parse_args()
    BASE = args.base
    print("SparkForge v0.2 acceptance against %s" % BASE)
    probe = http("GET", "/api/status", timeout=30)
    if probe.get("error"):
        print("FAIL: server unreachable: %s" % probe["error"])
        return 2
    print("server: %s v%s  sandbox=%s" % (probe.get("service"), probe.get("version"),
                                          probe.get("sandbox")))
    check_sandbox()
    check_registry()
    check_deny()
    check_scripted_tool_run()
    check_hitl()
    check_model_tool_run()
    check_mcp_stdio()
    check_mcp_http()
    passed = sum(1 for r in results if r["ok"])
    print("\n" + "=" * 72)
    print("EVIDENCE SUMMARY: %d/%d checks passed" % (passed, len(results)))
    for r in results:
        print(" %s  %s" % ("PASS" if r["ok"] else "FAIL", r["check"]))
    report = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "base": BASE,
              "passed": passed, "total": len(results), "checks": results}
    out_dir = os.path.join(REPO, "data")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "v02-acceptance.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print("report: %s" % path)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
