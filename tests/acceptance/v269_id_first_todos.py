#!/usr/bin/env python3
"""v269 — id-first todo addressing + a REQUIRED reason on 'superseded'.

JAG-269: a todo is an OBJECT addressed by its stable id (`n3`), never by its
position in a list. This suite locks:
  * 'superseded' is REJECTED without a reason (exactly like 'done' needs evidence);
  * update_todos is taught id-first (the 0-based `index` stays as a fallback);
  * the tool card shows the node id and the close reason;
  * a string dep resolves by an existing node id (id-first) or by a label;
  * a rejected close is surfaced to the model instead of being swallowed.

Deterministic, no live server, no network. Run: python3 tests/v269_id_first_todos.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v269-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR", "DB"):
    os.environ["SPARKFORGE_" + _k] = os.path.join(TMP, _k)
sys.path.insert(0, os.path.join(REPO, "src"))

from sparkforge import server as S  # noqa: E402
from sparkforge import taskgraph as TG  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# --- reason is REQUIRED to close a step as 'superseded' ----------------------
g = TG.ensure("id1", session_id="id1")
a = TG.add_node(g, "alpha")
b = TG.add_node(g, "beta")
check("nodes carry stable ids", a["id"] == "n1" and b["id"] == "n2",
      "%s/%s" % (a["id"], b["id"]))

raised = False
try:
    TG.update_node(TG.load("id1"), a["id"], status="superseded")
except ValueError as e:
    raised = "reason" in str(e)
check("superseded WITHOUT a reason is rejected", raised)

raised = False
try:
    TG.update_node(TG.load("id1"), a["id"], status="superseded", reason="   ")
except ValueError:
    raised = True
check("a blank reason is rejected too", raised)

n = TG.update_node(TG.load("id1"), a["id"], status="superseded", reason="no longer wanted")
check("superseded WITH a reason is accepted",
      n["status"] == "superseded" and n["reason"] == "no longer wanted")

raised = False
try:
    TG.update_node(TG.load("id1"), b["id"], status="cancelled")
except ValueError:
    raised = True
check("cancelled still needs no reason (harness soft-cancel)", not raised)

raised = False
try:
    TG.update_node(TG.load("id1"), b["id"], status="done")
except ValueError as e:
    raised = "evidence" in str(e)
check("done still REQUIRES evidence", raised)

# --- resolution is id-first, index is only a fallback ------------------------
g2 = TG.ensure("id2", session_id="id2")
TG.add_node(g2, "one")
TG.add_node(g2, "two")
TG.add_node(g2, "three")
g2 = TG.load("id2")
check("resolve by id", S._resolve_graph_node(g2, {"id": "n2"})["label"] == "two")
check("id wins over index when both are given",
      S._resolve_graph_node(g2, {"id": "n2", "index": 0})["label"] == "two")
check("resolve by index (fallback)",
      S._resolve_graph_node(g2, {"index": 0})["label"] == "one")

# --- a string dep may be an existing node id (id-first) ----------------------
g3 = TG.ensure("id3", session_id="id3")
base = TG.add_node(g3, "base")
added = TG.apply_write_todos(TG.load("id3"), [{"label": "child", "deps": [base["id"]]}])
check("a string dep resolves by node id",
      bool(added) and added[0]["deps"] == [base["id"]], str(added[0]["deps"]) if added else "")

# --- the contract taught to the model is id-first ----------------------------
check("CHAT_TOOL_PROMPT teaches the node id",
      "address each step by its STABLE id" in S.CHAT_TOOL_PROMPT
      and '"id":"<node id' in S.CHAT_TOOL_PROMPT)
check("CHAT_TOOL_PROMPT keeps index as a fallback",
      "fallback" in S.CHAT_TOOL_PROMPT and "index" in S.CHAT_TOOL_PROMPT)
check("TASK_POLICY closes 'superseded' by id with a REQUIRED reason",
      "by its id" in S.TASK_POLICY and "REQUIRED" in S.TASK_POLICY
      and '"id":"<node id>"' in S.TASK_POLICY)
_piv = S._pivot_sync_text(1, "L")
check("the pivot reminder is id-first + REQUIRED",
      '"id":"<node id>"' in _piv and "REQUIRED" in _piv)

# --- the tool card shows the id and the close reason -------------------------
ev = []
sess = {"id": "id9", "title": "id9", "messages": []}
g9 = TG.ensure("id9", session_id="id9")
TG.add_node(g9, "alpha")
TG.add_node(g9, "beta")
TG.update_node(TG.load("id9"), "n1", status="superseded", reason="dropped")
S._apply_chat_todo_updates(sess, {"steps": [{"id": "n2", "status": "doing"}]},
                           lambda kind, **d: ev.append((kind, d)))
outs = [d.get("output", "") for k, d in ev if k == "tool.result"]
o = outs[0] if outs else ""
check("card shows the node ids", "n1" in o and "n2" in o, o[:160])
check("card shows the close reason", "dropped" in o, o[:160])

# --- a rejected close is surfaced to the model (not swallowed) ---------------
ev2 = []
sess2 = {"id": "id8", "title": "id8", "messages": []}
g8 = TG.ensure("id8", session_id="id8")
TG.add_node(g8, "x")
S._apply_chat_todo_updates(sess2, {"steps": [{"id": "n1", "status": "superseded"}]},
                           lambda kind, **d: ev2.append((kind, d)))
res = [d for k, d in ev2 if k == "tool.result"]
check("a rejected close returns ok=False",
      bool(res) and res[0].get("ok") is False, str(res)[:160])
check("the rejection names the missing reason",
      bool(res) and "reason" in str(res[0].get("stderr") or ""), str(res)[:200])

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
