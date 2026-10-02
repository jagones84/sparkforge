#!/usr/bin/env python3
"""v0.9.13 acceptance — compaction is done BY THE MODEL, not by a dumb truncate (JAG-103).

"la compaction chi la fa? la deve fare l'LLM" — the older turns must be summarized
by the model (faithful prose), with the local extractive merge only as a fallback
when the router fails. The policy lives ONCE on the server (app + WebUI share it).
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(prefix="sf-llmcompact-")
os.environ["SPARKFORGE_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["SPARKFORGE_DB"] = os.path.join(tmp, "events.db")
os.environ["SPARKFORGE_GRAPH_DIR"] = os.path.join(tmp, "graphs")
os.makedirs(os.environ["SPARKFORGE_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["SPARKFORGE_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, REPO)

import context_engine  # noqa: E402
import server  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def transcript(n):
    msgs = []
    for i in range(n):
        msgs.append({"role": "user", "content": "domanda %d %s" % (i, "lorem ipsum " * 60)})
        msgs.append({"role": "assistant", "content": "risposta %d %s" % (i, "dolor sit amet " * 60)})
    return msgs


msgs = transcript(20)
budget = 3000  # forces compaction

# --- L1: a summarizer is used and its text becomes the summary ---------------
out, st = context_engine.compact(msgs, budget, summarizer=lambda old: "MY-LLM-SUMMARY")
check("L1a the model's summary is used verbatim",
      st["summary"] == "llm" and out and "MY-LLM-SUMMARY" in out[0]["content"],
      "summary=%s head=%r" % (st["summary"], out[0]["content"][:40] if out else None))
check("L1b newest messages kept verbatim",
      out[-1]["content"] == msgs[-1]["content"],
      "last kept=%r" % (out[-1]["content"][:30] if out else None))

# --- L2: summarizer returns None -> extractive fallback ----------------------
out2, st2 = context_engine.compact(msgs, budget, summarizer=lambda old: None)
check("L2 no summary -> extractive fallback",
      st2["summary"] == "extractive"
      and "Earlier conversation (compacted):" in out2[0]["content"],
      "summary=%s" % st2["summary"])

# --- L3: summarizer raises -> extractive fallback (never stalls) -------------
def boom(old):
    raise RuntimeError("router down")


out3, st3 = context_engine.compact(msgs, budget, summarizer=boom)
check("L3 a raising summarizer falls back to extractive",
      st3["summary"] == "extractive", "summary=%s" % st3["summary"])

# --- L4: the server wires the LLM summarizer into compact_session ------------
server._summarize_with_llm = lambda messages, model=None: "SERVER-LLM-SUMMARY"
sess = server.get_or_create_session("wire")
for m in transcript(20):
    server.append_message(sess, m["role"], m["content"])
res = server.compact_session("wire")
sess2 = server.load_session("wire")
check("L4 compact_session uses the model summarizer (single policy, shared)",
      res["summary"] == "llm" and "SERVER-LLM-SUMMARY" in sess2["messages"][0]["content"],
      "summary=%s" % res.get("summary"))

print("\n==== %d/%d checks passed ====" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
