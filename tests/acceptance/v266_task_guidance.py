#!/usr/bin/env python3
"""v266 — standing task-list rule + tagged harness turns + pivot sync + superseded.

JAG-266 changes:
  * TASK_POLICY is a standing prompt section (order 89) right ABOVE the live list.
  * harness-injected turns are tagged `[harness] ` (harness_wrap).
  * a "pivot" turn (opens with open todos) gets ONE bounded sync round reminding the
    model of open todos instead of silently stopping, and the model may close a step
    as 'superseded' WITH a reason instead of being forced to finish it.

Deterministic, no live server, no network. Run: python3 tests/v266_task_guidance.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v266-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR", "DB"):
    os.environ["SPARKFORGE_" + _k] = os.path.join(TMP, _k)
sys.path.insert(0, os.path.join(REPO, "src"))

from sparkforge import prompt as P  # noqa: E402
from sparkforge import server as S  # noqa: E402
from sparkforge import taskgraph as TG  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# --- Task 1: standing rule --------------------------------------------------
txt = P.render_sections(sess={"id": "s1"}, ws=None, tool_ctx="TOOLS")
check("task policy section is present", "Your task list" in txt)
check("task policy states the most-important line", "MOST IMPORTANT" in txt)
check("task policy states step-by-step + mark done",
      "ONE step at a time" in txt and "mark it 'done'" in txt)
check("task policy forbids reporting done with open steps",
      "NEVER report the job finished while steps are still open" in txt)
check("the live task list is OUT of the system prompt (JAG-276 cache)",
      "Harness state (your persistent task list):" not in txt)
check("task policy states the user priority rule",
      "outranks" in txt and "[harness]" in txt)
check("task policy offers the superseded escape hatch", "'superseded'" in txt)
check("task-policy is registered in prompt.SECTIONS",
      any(sec["id"] == "task-policy" for sec in P.SECTIONS))

# --- Task 2: tagged harness turns -------------------------------------------
w = S.harness_wrap("Observation for tool shell:\nhi")
check("harness_wrap tags the message", w["content"].startswith("[harness] "))
check("harness_wrap keeps the user role", w["role"] == "user")
check("harness marker is the module constant", S.HARNESS_MARK == "[harness] ")
check("harness_wrap does not echo a user string verbatim",
      "UNIQUE_USER_TEXT" not in S.harness_wrap("ok")["content"])

# --- Task 3: pivot sync (one bounded round, no forced work) ------------------
st = {"synced": False}
d1 = S._pivot_decide(True, {"continue": True, "reason": None}, 3, st)
check("pivot grants ONE sync round", d1 == {"continue": True, "reason": "pivot_sync"}, str(d1))
d2 = S._pivot_decide(True, {"continue": True, "reason": None}, 3, st)
check("after the sync round it stops as user_pivot",
      d2 == {"continue": False, "reason": "user_pivot"}, str(d2))
check("no pivot leaves the decision unchanged",
      S._pivot_decide(False, {"continue": True, "reason": None}, 3, {"synced": False})
      == {"continue": True, "reason": None})
check("no open todos leaves the decision unchanged",
      S._pivot_decide(True, {"continue": True, "reason": None}, 0, {"synced": False})
      == {"continue": True, "reason": None})
sync = S._pivot_sync_text(2, "TASK LIST ...")
check("sync text tells the model it may supersede with a reason",
      "superseded" in sync and "reason" in sync and "do NOT have to finish" in sync)

# --- superseded status (closed, with a reason) ------------------------------
check("superseded is a valid status", "superseded" in TG.STATUSES)
check("superseded is NOT open", "superseded" not in TG.OPEN_STATUSES)

g = TG.ensure("s1", session_id="s1")
TG.add_node(g, "alpha")
TG.add_node(g, "beta")
g = TG.load("s1")
n0 = TG.plan_nodes(g)[0]
TG.update_node(g, n0["id"], status="superseded", reason="no longer needed")
g = TG.load("s1")
check("superseded closes the node", TG.plan_nodes(g)[0]["status"] == "superseded")
check("superseded stores the reason", TG.plan_nodes(g)[0].get("reason") == "no longer needed")
check("render_todos marks superseded [~] and shows the reason",
      "[~]" in TG.render_todos(g) and "no longer needed" in TG.render_todos(g))
TG.update_node(g, TG.plan_nodes(g)[1]["id"], status="superseded", reason="also dropped")
check("all_done counts superseded as closed", TG.all_done(TG.load("s1")) is True)

# --- JAG-268: no_progress only on a truly idle round -------------------------
check("idle round with an unchanged list grows stale",
      S._next_stale(0, "h", "h", False) == 1 and S._next_stale(1, "h", "h", False) == 2)
check("a round that ran a tool resets stale", S._next_stale(5, "h", "h", True) == 0)
check("a changed list resets stale", S._next_stale(5, "h", "h2", False) == 0)
check("the first round is never stale", S._next_stale(0, None, "h", False) == 0)

# --- JAG-268: update_todos card shows the WHOLE list, not just changed lines --
ev = []
_sess2 = {"id": "s9", "title": "s9", "messages": []}
g9 = TG.ensure("s9", session_id="s9")
TG.add_node(g9, "alpha")
TG.add_node(g9, "beta")
S._apply_chat_todo_updates(_sess2, {"steps": [{"index": 0, "status": "doing"}]},
                           lambda kind, **d: ev.append((kind, d)))
outs = [d.get("output", "") for k, d in ev if k == "tool.result"]
check("update_todos output lists every step, not only the changed one",
      bool(outs) and "alpha" in outs[0] and "beta" in outs[0], str(outs)[:160])

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
