#!/usr/bin/env python3
"""v0.9.12 acceptance — the MANUAL "compact now" must actually shrink (JAG-102).

Reported as "Non compatta col tasto". `/api/context/compact` called
`compact_session(session)` with no budget, so it used the FULL model budget and
`compact()` returned unchanged for any session under 100% -> the button did
nothing. The policy now lives ONCE in the server (so app + WebUI share it).
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="sf-compact-")
os.environ["SPARKFORGE_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["SPARKFORGE_DB"] = os.path.join(tmp, "events.db")
os.environ["SPARKFORGE_GRAPH_DIR"] = os.path.join(tmp, "graphs")
os.environ["SPARKFORGE_CONTEXT_BUDGET"] = "262144"
os.makedirs(os.environ["SPARKFORGE_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["SPARKFORGE_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from sparkforge import context_engine  # noqa: E402
from sparkforge import server  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def mktx(sid, n):
    sess = server.get_or_create_session(sid)
    for i in range(n):
        server.append_message(sess, "user",
                              "domanda %d: %s" % (i, "lorem ipsum dolor sit amet " * 30))
        server.append_message(sess, "assistant",
                              "risposta %d: %s" % (i, "consectetur adipiscing elit " * 30))
    s = server.load_session(sid)
    return s, [m["content"] for m in s["messages"]]


# --- manual compact (no budget) must reduce ---------------------------------
sess, contents = mktx("manual", 20)
before_msgs = len(sess["messages"])
before_tok = sum(context_engine.count_tokens(c) for c in contents)
res = server.compact_session("manual")
sess2 = server.load_session("manual")
after_msgs = len(sess2["messages"])
after_contents = [m["content"] for m in sess2["messages"]]
after_tok = sum(context_engine.count_tokens(c) for c in after_contents)

check("K1 manual compact returns no error", "error" not in res, str(res.get("error")))
check("K2 the transcript really SHRINKS (was a no-op before)",
      res["tokens_after"] < res["input_tokens"],
      "tokens %d -> %d" % (res["input_tokens"], res["tokens_after"]))
check("K3 older messages were merged into a summary",
      res["compacted"] > 0 and after_msgs < before_msgs,
      "compacted=%d messages %d -> %d" % (res["compacted"], before_msgs, after_msgs))
check("K4 the NEWEST messages are kept verbatim",
      after_contents and after_contents[-1] == contents[-1],
      "last kept=%r" % (after_contents[-1][:40] if after_contents else None))

# --- explicit budget (autocompact path) still honoured ----------------------
sess3, contents3 = mktx("budgeted", 20)
before3 = sum(context_engine.count_tokens(c) for c in contents3)
res3 = server.compact_session("budgeted", 10_000_000)  # absurdly roomy -> no-op
check("K5 with an explicit roomy budget it is a no-op (autocompact unchanged)",
      res3["compacted"] == 0 and res3["tokens_after"] == before3,
      "compacted=%d tokens %d -> %d" % (res3["compacted"], res3["input_tokens"],
                                        res3["tokens_after"]))

print("\n==== %d/%d checks passed ====" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
