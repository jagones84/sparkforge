#!/usr/bin/env python3
"""v0.7.4 acceptance — context indicator + auto-compaction (JAG-70).

Proves two things the old indicator got wrong:
  * `tokens_used` is the EFFECTIVE prompt size (system prompt + transcript), not
    just the stored transcript (which under-reported by ~18x);
  * a turn over the threshold (default 75%) auto-compacts the stored transcript.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(prefix="sf-ctx-")
os.environ["SPARKFORGE_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["SPARKFORGE_DB"] = os.path.join(tmp, "events.db")
os.environ["SPARKFORGE_GRAPH_DIR"] = os.path.join(tmp, "graphs")
os.environ["SPARKFORGE_CONTEXT_BUDGET"] = "800"   # tiny: 75% == 600 tokens
os.makedirs(os.environ["SPARKFORGE_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["SPARKFORGE_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, REPO)

import context_engine  # noqa: E402
import server  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


sess = server.get_or_create_session("ctx-test")
for i in range(12):
    server.append_message(sess, "user", "domanda %d: %s" % (i, "lorem ipsum dolor sit amet " * 8))
    server.append_message(sess, "assistant", "risposta %d: %s" % (i, "consectetur adipiscing elit " * 8))
sess = server.load_session("ctx-test")

transcript_only = sum(context_engine.count_tokens(m.get("content", ""))
                      for m in sess["messages"])
usage = server.context_usage("ctx-test")

check("C1 available + budget from the env override",
      usage["available"] is True and usage["budget_tokens"] == 800,
      "available=%s budget=%s" % (usage["available"], usage["budget_tokens"]))
check("C2 tokens_used counts the SYSTEM prompt too (real, not transcript-only)",
      usage["tokens_used"] > transcript_only and usage["system_tokens"] > 0,
      "used=%s transcript_only=%s system=%s" % (
          usage["tokens_used"], transcript_only, usage["system_tokens"]))
check("C3 pct is computed against the real budget",
      abs(usage["pct"] - usage["tokens_used"] / 800 * 100) < 0.2,
      "pct=%s used=%s" % (usage["pct"], usage["tokens_used"]))
check("C4 over_threshold flags the auto-compaction trigger (75%)",
      usage["over_threshold"] is True and usage["auto_compact_pct"] == 75.0,
      "pct=%s threshold=%s" % (usage["pct"], usage["auto_compact_pct"]))

last = server.events_since(0)[-1]["id"] if server.events_since(0) else 0
before = len(sess["messages"])
sess2 = server.prepare_session_for_turn(sess)
after = len(sess2["messages"])
kinds = [e["kind"] for e in server.events_since(last)]
check("C5 over threshold → the transcript is auto-compacted",
      after < before and "context.auto_compact" in kinds,
      "messages %d -> %d kinds=%s" % (before, after, kinds))

usage2 = server.context_usage("ctx-test")
check("C6 after compaction the transcript part shrinks (system prompt unchanged)",
      usage2["transcript_tokens"] < usage["transcript_tokens"]
      and usage2["system_tokens"] == usage["system_tokens"],
      "transcript %s -> %s" % (usage["transcript_tokens"], usage2["transcript_tokens"]))

print("\n==== %d/%d checks passed ====" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
