#!/usr/bin/env python3
"""v262 — startup recovery of turns killed by a restart, and a queryable event
log (JAG-262).

Root cause of the "stuck session": a systemd restart (SIGTERM) kills an in-flight
chat turn; its `finally` never runs, so the session keeps a trailing `user`
message with no reply and the WebUI shows it as still working. On startup nothing
is in flight, so any session ending on a `user` turn is an orphan and is closed
with an explicit assistant notice. `query_events` gives the post-mortem view.

Deterministic, no live server, no network. Run: python3 tests/v262_recovery.py
"""
import os
import sys
import json
import time
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v262-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun import server as s  # noqa: E402
from longrun import tools as _tools  # noqa: E402
from longrun import registry as _registry  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


os.makedirs(s.SESSIONS_DIR, exist_ok=True)


def write(sid, msgs):
    with open(os.path.join(s.SESSIONS_DIR, sid + ".json"), "w", encoding="utf-8") as f:
        json.dump({"id": sid, "title": sid, "messages": msgs}, f)


write("orphan1", [{"role": "user", "content": "hi"}])
write("ok1", [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}])

n = s.reconcile_orphan_turns()
check("reconciles exactly the orphan session", n == 1, "n=%s" % n)

orph = s.load_session("orphan1")
check("orphan now ends on an assistant turn",
      orph["messages"][-1]["role"] == "assistant",
      orph["messages"][-1]["role"])
check("orphan reply is flagged interrupted",
      orph["messages"][-1].get("interrupted") is True
      and orph["messages"][-1].get("error") is True)
check("notice is in English",
      "interrupted" in orph["messages"][-1]["content"]
      and "errore" not in orph["messages"][-1]["content"])

ok = s.load_session("ok1")
check("a healthy session is untouched (idempotent)",
      len(ok["messages"]) == 2 and ok["messages"][-1]["role"] == "assistant")

# a second run must not double-close anything
check("second reconcile is a no-op", s.reconcile_orphan_turns() == 0)

# the queryable event log
s.publish("custom.thing", session="orphan1", foo="bar")
check("query_events filters by session",
      any(e["kind"] == "custom.thing" for e in s.query_events(session="orphan1")))
check("query_events filters by kind",
      any(e["kind"] == "custom.thing" for e in s.query_events(kind="custom.thing")))
check("query_events newest-first",
      [e["id"] for e in s.query_events(limit=10)] ==
      sorted([e["id"] for e in s.query_events(limit=10)], reverse=True))

# JAG-263: the agent can run it itself through the tool registry
write("orphan2", [{"role": "user", "content": "stuck?"}])
res = _tools.execute("reconcile", {"session": "orphan2"})
check("reconcile tool returns ok", res.get("ok") is True, str(res)[:90])
check("reconcile tool closed exactly the orphan", res.get("reconciled") == 1,
      str(res.get("reconciled")))
check("orphan2 now ends on an assistant turn",
      s.load_session("orphan2")["messages"][-1]["role"] == "assistant")
check("reconcile is a registered tool", "reconcile" in _registry.TOOL_SCHEMAS)
check("reconcile description states WHEN to use it",
      "stuck" in _registry.TOOL_SCHEMAS["reconcile"]["description"].lower())
with open(os.path.join(REPO, "config", "tools.yaml"), encoding="utf-8") as f:
    _ty = f.read()
check("reconcile is enabled in config/tools.yaml",
      "reconcile:" in _ty and "enabled: true" in _ty.split("reconcile:")[1][:80])

# JAG-262b: a LIVE turn has a trailing user message too, so a sweep must NEVER
# touch a session that currently owns a turn (that was the "it breaks the one
# that IS working" trap).
write("active1", [{"role": "user", "content": "work in progress"}])
with s._ACTIVE_CHAT_LOCK:
    s._ACTIVE_CHAT["active1"] = {"ev0": 0, "ts": time.time()}
try:
    n_live = s.reconcile_orphan_turns()
    check("a live session is skipped by the sweep", n_live == 0, "n=%s" % n_live)
    check("a live session is left untouched",
          s.load_session("active1")["messages"][-1]["role"] == "user")
finally:
    with s._ACTIVE_CHAT_LOCK:
        s._ACTIVE_CHAT.pop("active1", None)
check("once the turn ends it is recoverable",
      s.reconcile_orphan_turns(session="active1") == 1)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
