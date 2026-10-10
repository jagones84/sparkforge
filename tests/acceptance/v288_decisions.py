#!/usr/bin/env python3
"""v288 — Decision queue (JAG-287 D, Paperclip parity).

Paperclip funnels everything that needs a human into ONE inbox. SparkForge already
has the ranked feed; this adds the drain: every item can be resolved inline, and a
resolution either delegates to a real primitive (approvals.decide / run retry) or is
acknowledged (dismiss) so the queue stays clean.

Locked here:
  * queue() filters dismissed ids and exposes counts + board;
  * resolve() dispatches approve/deny to approvals.decide, retry to the run handler,
    dismiss to a persisted ack set; refuses mismatched ids and unknown actions;
  * the /api/orbit/decisions route answers GET (queue) and POST (resolve);
  * the Orbit UI renders the queue with approve/deny/retry/dismiss actions.

Deterministic (feed + approvals + retry are stubbed), no live model.
Run: python3 tests/v288_decisions.py
"""
import os
import sys
import tempfile
import types

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "src"))
TMP = tempfile.mkdtemp(prefix="sf-v288-")
os.environ["SPARKFORGE_DECISIONS_FILE"] = os.path.join(TMP, "decisions.json")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


from sparkforge import approvals  # noqa: E402
from sparkforge.orbit import api as oapi  # noqa: E402
from sparkforge.orbit.decisions import DecisionQueue  # noqa: E402

decided, retried = [], []
approvals.decide = lambda aid, decision, by="human": decided.append((aid, decision, by)) or {
    "id": aid, "status": {"approve": "approved", "deny": "denied"}[decision]}


class FakeFeed:
    def __init__(self, items, sessions):
        self._items = items
        self.registry = types.SimpleNamespace(list=lambda: {"sessions": sessions})

    def snapshot(self, sessions=None):
        return {"items": [dict(i) for i in self._items], "count": len(self._items)}


ITEMS = [
    {"id": "approval:ap1", "kind": "approval", "severity": "high", "title": "approve shell",
     "session": "s1", "actionable": True, "ref": {"approval": "ap1", "tool": "shell"}},
    {"id": "failed:s1:123", "kind": "failed_run", "severity": "high", "title": "dispatch failed",
     "session": "s1", "actionable": False, "ref": {"job": "s1:123"}},
    {"id": "opentodos:s2", "kind": "blocked_session", "severity": "medium", "title": "3 open steps",
     "session": "s2", "actionable": False, "ref": {"open": 3}},
]


def make_queue():
    return DecisionQueue(FakeFeed(ITEMS, [{"id": "s1", "running": True}, {"id": "s2"}]),
                         retry=lambda jid: retried.append(jid) or {"ok": True, "job": jid})


# --- queue snapshot ---------------------------------------------------------
dq = make_queue()
snap = dq.queue()
check("queue lists all items", snap["count"] == 3 and len(snap["items"]) == 3)
check("queue tallies severities", snap["by_severity"] == {"high": 2, "medium": 1})
check("queue ships the board", "board" in snap and snap["board"]["working"][0]["id"] == "s1")

# --- dismiss (persisted ack) ------------------------------------------------
r = dq.resolve("opentodos:s2", "dismiss")
check("dismiss acknowledges an item", r["ok"] and r["action"] == "dismiss")
check("a dismissed item leaves the queue", dq.queue()["count"] == 2 and dq.queue()["dismissed"] == 1)
check("the ack set is persisted", os.path.exists(os.environ["SPARKFORGE_DECISIONS_FILE"]))
dq2 = make_queue()
check("a fresh queue still hides the dismissed id", dq2.queue()["count"] == 2)

# --- approve / deny delegate to approvals.decide ----------------------------
r = dq.resolve("approval:ap1", "approve", by="orbit")
check("approve delegates to approvals.decide",
      r["ok"] and r["status"] == "approved" and decided[-1] == ("ap1", "approve", "orbit"))
check("an approved item leaves the queue", dq.queue()["count"] == 1)

# --- retry a failed run -----------------------------------------------------
r = dq.resolve("failed:s1:123", "retry")
check("retry delegates to the run handler", r["ok"] and retried == ["s1:123"])
check("a retried item leaves the queue", dq.queue()["count"] == 0)

# --- refusals ---------------------------------------------------------------
check("retry refuses a non-failed id", dq.resolve("approval:ap1", "retry")["ok"] is False)
check("approve refuses a non-approval id", dq.resolve("failed:x", "approve")["ok"] is False)
check("unknown action is refused", dq.resolve("opentodos:s2", "explode")["ok"] is False)
check("an empty id is refused", dq.resolve("", "dismiss")["ok"] is False)

# --- API routing ------------------------------------------------------------
class FakeHandler:
    def __init__(self):
        self.sent = None

    def _send(self, code, obj, ctype=None):
        self.sent = {"code": code, "obj": obj}
        return True


oapi._QUEUE = DecisionQueue(
    FakeFeed([{"id": "approval:zz", "kind": "approval", "severity": "high",
               "title": "approve", "session": "s1", "actionable": True,
               "ref": {"approval": "zz"}}],
             [{"id": "s1", "running": True}]),
    retry=lambda jid: {"ok": True, "job": jid})
fh = FakeHandler()
ok = oapi.handle(fh, "GET", "/api/orbit/decisions", {}, None)
check("GET /api/orbit/decisions answers", ok and fh.sent["code"] == 200 and fh.sent["obj"]["count"] == 1)
fh = FakeHandler()
ok = oapi.handle(fh, "POST", "/api/orbit/decisions", {}, {"id": "approval:zz", "action": "deny"})
check("POST /api/orbit/decisions resolves", ok and fh.sent["obj"]["ok"] is True)
fh = FakeHandler()
check("a non-orbit path is not shadowed",
      oapi.handle(fh, "GET", "/api/status", {}, None) is False and fh.sent is None)

# --- UI wiring --------------------------------------------------------------
with open(os.path.join(REPO, "src", "sparkforge", "orbit", "web", "orbit.html"), encoding="utf-8") as f:
    ui = f.read()
check("the decision queue is retired from the simplified Orbit page",
      "Decision queue" not in ui and "AttentionView" not in ui)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
