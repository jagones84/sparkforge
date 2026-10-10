#!/usr/bin/env python3
"""v271 — precise open-todo nudge + cache-safe prompt ordering (JAG-271).

Two fixes:
  * the harness nudge NAMES the exact open steps (id + label) instead of a generic
    "mark the next step 'doing'" (`_open_todo_brief` / `_nudge_open_todos`);
  * the system prompt is ordered static-first / dynamic-last so the provider's
    prefix (KV) cache survives across turns: EVERY static section (task-policy
    included) precedes every dynamic one, and JAG-276 moved the volatile live
    task list OUT of the system prompt (into the current user turn), so the
    system prompt is now 100% cache-stable.

Deterministic, no live server, no network. Run: python3 tests/v271_prompt_alignment.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v271-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR", "DB"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR"):
    os.makedirs(os.environ["LONGRUN_" + _k], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun import prompt as P  # noqa: E402
from longrun import server as S  # noqa: E402
from longrun import taskgraph as TG  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# --- precise nudge -----------------------------------------------------------
sess = {"id": "p1", "title": "p1", "messages": []}
g = TG.ensure("p1", session_id="p1")
a = TG.add_node(g, "alpha done step")
b = TG.add_node(g, "beta doing step")
c = TG.add_node(g, "gamma todo step")
TG.update_node(TG.load("p1"), a["id"], status="done", evidence="did it")
TG.update_node(TG.load("p1"), b["id"], status="doing")

n, brief = S._open_todo_brief(sess)
check("brief counts only the OPEN steps", n == 2, "n=%s" % n)
check("brief names the open ids", b["id"] in brief and c["id"] in brief, brief)
check("brief excludes the done step", a["id"] not in brief, brief)

nudge = S._nudge_open_todos(sess)
check("nudge states the exact open count", "STILL OPEN (2)" in nudge, nudge[:120])
check("nudge names the exact open steps", b["id"] in nudge and c["id"] in nudge, nudge[:200])
check("nudge no longer uses the vague wording", "mark the next step" not in nudge)

# all closed -> the nudge says so
TG.update_node(TG.load("p1"), b["id"], status="done", evidence="ok")
TG.update_node(TG.load("p1"), c["id"], status="done", evidence="ok")
check("nudge says the list is fully closed",
      "every step is now closed" in S._nudge_open_todos(sess))

# empty plan -> (0, "(none …)")
check("empty plan -> zero + '(none …)'",
      S._open_todo_brief({"id": "p-empty"})[0] == 0
      and "none" in S._open_todo_brief({"id": "p-empty"})[1])

# --- cache-safe prompt ordering (JAG-271/273/276) ----------------------------
by_id = {s["id"]: s for s in P.SECTIONS}
static_orders = [s["order"] for s in P.SECTIONS if s["kind"] == "static"]
dyn_orders = [s["order"] for s in P.SECTIONS if s["kind"] == "dynamic"]
check("EVERY static section precedes EVERY dynamic one (cache-safe)",
      max(static_orders) < min(dyn_orders),
      "static_max=%s dyn_min=%s" % (max(static_orders), min(dyn_orders)))
check("the prompt FRONT (order<50) is all static (cache-safe)",
      all(s["kind"] == "static" for s in P.SECTIONS if s["order"] < 50),
      str([(s["id"], s["kind"]) for s in P.SECTIONS if s["order"] < 50]))
# JAG-276: the live task list is NOT a system section anymore — it rides in the
# current USER turn, so the system prompt is 100% cache-stable.
check("the live task list is no longer a SYSTEM section", "state" not in by_id)

# proof: put a marker in the graph; it must NOT appear in the system prompt, but
# MUST appear in the current user turn of the assembled list.
S.save_session({"id": "p-ord", "title": "p-ord", "messages": []})
g_ord = TG.ensure("p-ord", session_id="p-ord")
TG.add_node(g_ord, "UNIQUE_LIVE_STEP_MARKER")
TG.save(g_ord)
txt = P.render_sections(sess={"id": "p-ord"}, ws=None, tool_ctx="TOOLS")
check("the system prompt carries the task rule but NO live task list",
      "Your task list" in txt and "UNIQUE_LIVE_STEP_MARKER" not in txt
      and "Harness state (your persistent task list):" not in txt)
msgs, _ = S.assemble_turn(S.load_session("p-ord"), "hello", tool_ctx="TOOLS")
check("the assembled turn injects the live list in the USER turn",
      msgs[-1]["role"] == "user" and "UNIQUE_LIVE_STEP_MARKER" in msgs[-1]["content"],
      msgs[-1]["content"][-160:])
check("the system message stays free of the live list",
      "UNIQUE_LIVE_STEP_MARKER" not in msgs[0]["content"])

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
