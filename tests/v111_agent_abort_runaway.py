#!/usr/bin/env python3
"""v0.9.17 acceptance — a runaway model does not hang the run, and stop works (JAG-111).

Root causes fixed here:
  * the SSE agent loop never registered an abortable run (so /api/agent/control
    could not stop it) and `agent.start` carried no run id (the WebUI's
    activeRunId was undefined);
  * `_router_stream` had no max_tokens and no repetition guard, so a model stuck
    in a repetition loop streamed forever (no idle -> the ROUTER_IDLE_TIMEOUT
    guard never fired -> the run looked "stuck at 5/6").
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(prefix="sf-jag111-")
os.environ["SPARKFORGE_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["SPARKFORGE_DB"] = os.path.join(tmp, "events.db")
os.environ["SPARKFORGE_GRAPH_DIR"] = os.path.join(tmp, "graphs")
os.makedirs(os.environ["SPARKFORGE_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["SPARKFORGE_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, REPO)

import api_v02  # noqa: E402
import server  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# ---- R1: repetition guard ---------------------------------------------------
g = server._RepetitionGuard(min_period=12, max_period=60, limit=3)
unit = "alfa bravo charlie delta echo foxtrot "
check("R1a one copy is not runaway", not g.feed(unit))
check("R1b two copies is not runaway", not g.feed(unit))
check("R1c three copies -> runaway", g.feed(unit))

g2 = server._RepetitionGuard(min_period=12, max_period=60, limit=3)
ok = True
for i in range(60):
    if g2.feed("parola numero %d " % i):
        ok = False
check("R1d distinct text never trips the guard", ok)

# ---- R2: guard wired into _router_stream ------------------------------------
server.ROUTER_IDLE_TIMEOUT = 0
server._chat_endpoint = lambda m: ("http://x", {}, m)

REPS = 30
chunk = "CONTESTO-RIPETUTO " * 8
lines = [("data: %s\n" % json.dumps({"choices": [{"delta": {"content": chunk}}]})).encode()
         for _ in range(REPS)]
lines.append(b"data: [DONE]\n")


class _FakeResp:
    def __init__(self, ls):
        self.ls = ls

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter(self.ls)


server._open_with_retry = lambda req, timeout: _FakeResp(lines)
_events = []
_orig_pub = server.publish
server.publish = lambda k, **d: _events.append((k, d))
ans, _think = server._router_stream([{"role": "user", "content": "x"}], "mock-alpha",
                                    lambda c, t: None, 5, None)
server.publish = _orig_pub
check("R2 runaway published", any(k == "model.runaway" for k, _ in _events),
      str([k for k, _ in _events]))
check("R2b the stream was cut before all repeats", ans.count("CONTESTO-RIPETUTO") < REPS,
      "got %d of %d" % (ans.count("CONTESTO-RIPETUTO"), REPS))

# ---- A1: agent_run registers an abortable run + agent.start carries run -----
server._router_stream = lambda msgs, model, on_delta, *a, **k: (
    '{"action":"finish","summary":"ok"}', "")
seen = []
res = server.agent_run("obiettivo di prova", 3, "mock-model",
                       on_event=lambda k, **d: seen.append((k, d)))
check("A1 agent.start carries a run id",
      any(k == "agent.start" and d.get("run") for k, d in seen),
      str([d for k, d in seen if k == "agent.start"]))
rid = next((d["run"] for k, d in seen if k == "agent.start"), None)
check("A1b the run is registered in api_v02.RUNS", api_v02.run_get(rid) is not None, str(rid))

# ---- A2: abort mid-run stops the loop before max_steps ----------------------
calls = {"n": 0}


def _counting_router(msgs, model, on_delta, *a, **k):
    calls["n"] += 1
    return ('{"action":"note","detail":"x"}', "")


server._router_stream = _counting_router
seen2 = []
box = {}


def _ev(k, **d):
    seen2.append((k, d))
    if k == "agent.start":
        box["id"] = d.get("run")
    if k == "agent.iteration" and d.get("i") == 2:
        api_v02.run_control(box["id"], "abort")


server.agent_run("obiettivo", 6, "mock-model", on_event=_ev)
check("A2 abort stops the loop early", calls["n"] < 6, "router calls=%d" % calls["n"])
check("A2b agent.aborted emitted", any(k == "agent.aborted" for k, _ in seen2),
      str([k for k, _ in seen2 if k.startswith("agent.")]))

# ---- A3: closing the stream generator aborts the run (client gone) ----------
captured = {}


def _slow_agent(goal, max_steps, model, on_event, trace=None, run_state=None,
                workspace=None):
    captured["st"] = run_state
    on_event("agent.start", goal=goal, run=run_state.id)
    import time
    for _ in range(200):
        if run_state.abort:
            break
        time.sleep(0.02)
    on_event("agent.finish", summary="aborted" if run_state.abort else "done")


server.agent_run = _slow_agent
gen = server.agent_stream_gen("g", 3, "m")
next(gen)  # open comment
import time  # noqa: E402
for _ in range(200):
    if captured.get("st") is not None:
        break
    time.sleep(0.01)
gen.close()  # simulate client disconnect
check("A3 disconnect sets abort on the run",
      bool(captured.get("st")) and captured["st"].abort is True, str(captured.get("st")))

# ---- M1: completion body / max_tokens --------------------------------------
b1 = server._completion_body("m", [], True, 2048)
b2 = server._completion_body("m", [], True, None)
b3 = server._completion_body("m", [], False, None)
check("M1 max_tokens included only when > 0",
      b1.get("max_tokens") == 2048 and "max_tokens" not in b2, str(b1.get("max_tokens")))
check("M1b stream_options only on streamed requests",
      "stream_options" in b1 and "stream_options" not in b3, str(sorted(b3.keys())))

total = len(results)
passed = sum(results)
print("\n==== %d/%d checks passed ====" % (passed, total))
sys.exit(0 if passed == total else 1)
