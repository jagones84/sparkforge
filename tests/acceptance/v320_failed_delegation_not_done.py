#!/usr/bin/env python3
"""v320 — a failed delegation cannot be followed by a "done" claim (JAG-320).

Observed live: an agent delegated a step to a subagent; the subagent TIMED OUT
(exit 1), yet the step was later closed as `done` with invented evidence
("A5 produced the schema...") — source `model:update_todos`. The harness accepted
it because the only gate is that the evidence string is non-empty; it never
cross-checked the objective outcome of the delegation. The failure observation
even said the subagent "finished".

JAG-320 (a) says FAILED instead of "finished", and (b) stores the delegation
OUTCOME durably ON the node, so a `done` on a step whose subagent failed is
refused. The marker is durable (survives restarts and long gaps — the real claim
came ~8.6h after the failure) and node-scoped (one step's failure must not block
another step). The refusal is ONE-SHOT: the marker is consumed, so a genuine
retry or a self-completed step is never blocked forever.

Deterministic, no model. Run: python3 tests/acceptance/v320_failed_delegation_not_done.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-320-")
os.environ["SPARKFORGE_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["SPARKFORGE_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["SPARKFORGE_DB"] = os.path.join(TMP, "events.db")
os.makedirs(os.environ["SPARKFORGE_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["SPARKFORGE_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from sparkforge import server, taskgraph  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


ev = []
on_event = lambda kind, **kw: ev.append((kind, kw))  # noqa: E731

SID = "v320"
sess = {"id": SID, "messages": []}
g = taskgraph.ensure(SID, session_id=SID, goal="ship the schema")
NID = taskgraph.add_node(g, "Assign A5 to specify the Book JSON schema")["id"]
OID = taskgraph.add_node(g, "Unrelated step")["id"]


def status_of(nid):
    n = taskgraph.find(taskgraph.load(SID), node_id=nid)
    return (n or {}).get("status")


def record_fail(nid, err="subagent timeout"):
    taskgraph.record_delegation(taskgraph.load(SID), nid, False, error=err,
                                subagent_id="sub_x")


def done(nid, evidence="A5 produced the schema"):
    server._apply_chat_todo_updates(
        sess, {"steps": [{"id": nid, "status": "done", "evidence": evidence}]}, on_event)


# ---- A: a FAILED delegation blocks the done claim on that step -------------
record_fail(NID)
ev.clear()
done(NID)
check("A1 the node is NOT marked done after a failed delegation",
      status_of(NID) != "done", str(status_of(NID)))
check("A2 the refusal is surfaced as an error",
      any("refusing 'done'" in str(kw) for _k, kw in ev), str(ev[-1:]))
check("A3 the fabricated evidence was not persisted",
      "A5 produced the schema" not in str(taskgraph.load(SID)), "")
check("A4 the failed-delegation marker is consumed after the refusal (one-shot)",
      "delegation" not in (taskgraph.find(taskgraph.load(SID), node_id=NID) or {}))

# ---- B: the refusal is one-shot — a genuine second attempt is allowed -------
ev.clear()
done(NID, "did the work myself")
check("B1 a second done attempt is accepted (never blocked forever)",
      status_of(NID) == "done", str(status_of(NID)))

# ---- C: a SUCCESSFUL retry clears the marker -> first attempt accepted -----
taskgraph.update_node(taskgraph.load(SID), NID, status="todo", source="test")
record_fail(NID)
taskgraph.record_delegation(taskgraph.load(SID), NID, True, subagent_id="sub_ok")
check("C1 a successful delegation cleared the marker",
      "delegation" not in (taskgraph.find(taskgraph.load(SID), node_id=NID) or {}))
ev.clear()
done(NID, "A5 delivered the schema")
check("C2 a done claim is accepted after a successful delegation",
      status_of(NID) == "done", str(status_of(NID)))

# ---- D: node-scoped — one step's failure must not block another step -------
taskgraph.update_node(taskgraph.load(SID), NID, status="todo", source="test")
record_fail(NID)
ev.clear()
done(OID, "unrelated work finished")
check("D1 a failure on one step does not block an unrelated step",
      status_of(OID) == "done", str(status_of(OID)))

# ---- E: source wiring ------------------------------------------------------
_tg = open(os.path.join(REPO, "src", "sparkforge", "taskgraph.py"), encoding="utf-8").read()
src = open(os.path.join(REPO, "src", "sparkforge", "server.py"), encoding="utf-8").read()
check("E1 taskgraph exposes the durable recorder", "def record_delegation(" in _tg)
check("E2 taskgraph exposes the marker consumer", "def clear_delegation(" in _tg)
check("E3 the guard is in the todo-done path", "refusing 'done'" in src)
check("E4 the delegation outcome is recorded on the step's node",
      "taskgraph.record_delegation(_g, node, ok" in src)
check("E5 the failure observation says FAILED, not finished",
      "FAILED: %s. This delegated step is NOT done" in src)

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
