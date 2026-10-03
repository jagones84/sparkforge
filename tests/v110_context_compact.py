#!/usr/bin/env python3
"""v0.9.16 acceptance — manual compaction always shrinks and is LLM-visible (JAG-110).

Root cause fixed here: `context_engine.compact` kept `keep_recent=8`
unconditionally, so a manual "compact now" on a session with <=8 messages
compacted NOTHING (old=[]), never called the summarizer (no GPU) and reported
"0 msgs compacted". Also `context.compact` never said WHICH model summarized
(llm vs the local extractive fallback).
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(prefix="sf-compact110-")
os.environ["SPARKFORGE_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["SPARKFORGE_DB"] = os.path.join(tmp, "events.db")
os.environ["SPARKFORGE_GRAPH_DIR"] = os.path.join(tmp, "graphs")
os.makedirs(os.environ["SPARKFORGE_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["SPARKFORGE_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from sparkforge import context_engine  # noqa: E402
from sparkforge import server  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def fills(n, size=60):
    msgs = []
    for i in range(n):
        msgs.append({"role": "user", "content": "domanda %d %s" % (i, "lorem ipsum " * size)})
        msgs.append({"role": "assistant", "content": "risposta %d %s" % (i, "dolor sit amet " * size)})
    return msgs


def make_session(sid, n):
    sess = server.get_or_create_session(sid)
    for m in fills(n):
        server.append_message(sess, m["role"], m["content"])


# ---- E1: force bypasses the under-budget early return -----------------------
small = fills(1)  # 2 messages
outf, stf = context_engine.compact(small, 10 ** 9, keep_recent=1,
                                   summarizer=lambda old: "S", force=True)
check("E1 force compacts even far below budget",
      stf["compacted"] > 0, "compacted=%s" % stf["compacted"])
outn, stn = context_engine.compact(small, 10 ** 9, keep_recent=1,
                                   summarizer=lambda old: "S", force=False)
check("E1b without force an under-budget transcript is untouched",
      stn["compacted"] == 0 and outn == small, "compacted=%s" % stn["compacted"])

# ---- E2: keep_recent is honoured -------------------------------------------
m6 = fills(3)  # 6 messages
_, st2 = context_engine.compact(m6, 10 ** 9, keep_recent=2,
                                summarizer=lambda old: "S", force=True)
check("E2 keep_recent=2 compacts len-2 messages",
      st2["compacted"] == 4, "compacted=%s" % st2["compacted"])


# ---- server-side -----------------------------------------------------------
def fake_llm(messages, model=None, meta=None):
    if meta is not None:
        meta["model"] = "glm-test-alias"
    return "SUMMARY BY MODEL"


server._summarize_with_llm = fake_llm
make_session("s1", 3)  # 6 messages
before = len(server.load_session("s1")["messages"])
res = server.compact_session("s1")
after = len(server.load_session("s1")["messages"])
check("S1 manual compact shrinks a small session", after < before, "%d -> %d" % (before, after))
check("S1b summary marked llm", res.get("summary") == "llm", str(res.get("summary")))
check("S1c compact event names the summarizer model",
      res.get("summarizer") == "glm-test-alias", str(res.get("summarizer")))

server._summarize_with_llm = lambda messages, model=None, meta=None: None
make_session("s2", 3)
res2 = server.compact_session("s2")
check("S2 extractive fallback reported", res2.get("summary") == "extractive", str(res2.get("summary")))
check("S2b no summarizer alias on fallback", res2.get("summarizer") is None, str(res2.get("summarizer")))

server._summarize_with_llm = fake_llm
make_session("s3", 10)  # 20 messages
res3 = server.compact_session("s3", 3000)  # auto path -> keep_recent engine default 8
check("S3 auto compact keeps 8 recent (compacted=12)",
      res3.get("compacted") == 12, str(res3.get("compacted")))

events = []
orig_pub = server.publish
server.publish = lambda kind, **d: events.append((kind, d))
make_session("s4", 3)
server.compact_session("s4")
server.publish = orig_pub
carried = [d for k, d in events if k == "context.compact"]
check("S4 context.compact event present", bool(carried), str(len(carried)))
check("S4b event carries summary + summarizer",
      bool(carried) and "summary" in carried[-1] and "summarizer" in carried[-1],
      str(sorted(carried[-1].keys())) if carried else "none")

# ---- D1: display regression -------------------------------------------------
d = server.context_display(5000, 258048, 9)
check("D1 display exposes pct/bar_pct/state",
      d["pct"] == 2 and d["bar_pct"] == 2 and d["state"] == "normal",
      "%s/%s/%s" % (d["pct"], d["bar_pct"], d["state"]))

total = len(results)
passed = sum(results)
print("\n==== %d/%d checks passed ====" % (passed, total))
sys.exit(0 if passed == total else 1)
