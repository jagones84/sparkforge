#!/usr/bin/env python3
"""v183 — chat-loop core: a turn runs, concludes, and never loops forever on a
call that already failed (JAG-183).

Deterministic: the LLM and the tool gate are MOCKED (no router, no GPU, no
network, isolated temp data dir). Two scenarios on two sessions:

  A) a NORMAL turn: the model asks for a tool -> it runs -> the model concludes ->
     the assistant reply is PERSISTED (proves the loop + the "no request without
     an answer" contract).
  B) a STUCK model: it re-issues the EXACT same FAILED call five times. The harness
     must execute it ONCE, then BLOCK the verbatim re-runs with a directive.
     Before JAG-183 it executed it every time and the model resigned.

Run:  python3 tests/v183_chat_core.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import atexit  # noqa: E402
import shutil  # noqa: E402
tmp = tempfile.mkdtemp(prefix="sf-183-")
atexit.register(lambda: shutil.rmtree(tmp, ignore_errors=True))
os.environ["SPARKFORGE_CONFIG_DIR"] = os.path.join(tmp, "cfg")
os.environ["SPARKFORGE_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["SPARKFORGE_DB"] = os.path.join(tmp, "events.db")
os.environ["SPARKFORGE_GRAPH_DIR"] = tmp
os.environ["SPARKFORGE_EDITS_DIR"] = os.path.join(tmp, "edits")
os.environ["SPARKFORGE_RUNS_DIR"] = os.path.join(tmp, "runs")
for d in ("cfg", "sessions", "graphs", "edits", "runs"):
    os.makedirs(os.path.join(tmp, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

import py_compile  # noqa: E402
py_compile.compile(os.path.join(REPO, "src", "sparkforge", "server.py"), doraise=True)
print("[compile] server.py OK")

from sparkforge import server  # noqa: E402

results = []
def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))

CALL_OK = '{"action":"tool","tool":"shell","args":{"command":"echo hi"}}'
CALL_BAD = '{"action":"tool","tool":"shell","args":{"command":"adb -s dev input tap 100 200"}}'


def run_turn(sid, script, gated):
    """Drive chat_once with a scripted model (`script(n)` -> text) and a mocked
    tool gate (`gated()` -> result dict). Returns (events, execution count)."""
    state = {"n": 0}
    execs = {"n": 0}

    def fake_gated(tool, args, **kw):
        execs["n"] += 1
        return gated()

    def fake_stream(msgs, model, role, on_delta, usage=None, cancel=None, **kw):
        text = script(state["n"])
        state["n"] += 1
        on_delta("answer", text)
        return text, "", model

    events = []
    server.stream_with_fallback = fake_stream
    server.api_v02.gated_call = fake_gated
    server.chat_once({"id": sid, "messages": [], "workspace": ""}, "go", model="mock",
                     on_delta=lambda c, t: None,
                     on_event=lambda kind, **d: events.append((kind, d)))
    return events, execs["n"]


def blocked(events):
    return [d for k, d in events
            if k == "harness.inject" and "CALL BLOCKED" in (d.get("text") or "")]


# ---- scenario A: a normal turn ---------------------------------------------
def gated_ok():
    return {"status": "executed",
            "observation": "[shell] exit=0 backend=stub sandboxed=False\nstdout: hi",
            "result": {"ok": True, "exit_code": 0, "stdout": "hi", "stderr": "",
                       "backend": "stub"}}


def script_ok(n):
    return CALL_OK if n == 0 else "fatto: comando eseguito."


ev_a, ex_a = run_turn("v183a", script_ok, gated_ok)
check("A1 tool executed exactly once", ex_a == 1, "execs=%d" % ex_a)
check("A2 tool.call card emitted", len([1 for k, _ in ev_a if k == "tool.call"]) == 1)
check("A3 no spurious block on a normal turn", not blocked(ev_a), "blocked=%d" % len(blocked(ev_a)))
sess = server.load_session("v183a") or {}
msgs = sess.get("messages", [])
last = msgs[-1] if msgs else {}
check("A4 assistant reply persisted",
      last.get("role") == "assistant" and "fatto" in (last.get("content") or ""),
      "%s: %r" % (last.get("role"), (last.get("content") or "")[:40]))


# ---- scenario B: stuck model, anti-loop (JAG-183) --------------------------
def gated_bad():
    err = "RuntimeError: adb: unknown command input"
    return {"status": "executed",
            "observation": "[shell] exit=1 backend=stub sandboxed=False\nstderr: " + err,
            "result": {"ok": False, "exit_code": 1, "stdout": "", "stderr": err,
                       "backend": "stub"}}


def script_bad(n):
    return CALL_BAD if n <= 4 else "mi fermo e chiedo."


ev_b, ex_b = run_turn("v183b", script_bad, gated_bad)
check("B1 failed call executed only ONCE", ex_b == 1, "execs=%d" % ex_b)
check("B2 verbatim re-runs BLOCKED (JAG-183)", len(blocked(ev_b)) >= 1,
      "blocked=%d" % len(blocked(ev_b)))

print("\n==== %d/%d checks passed ====" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
