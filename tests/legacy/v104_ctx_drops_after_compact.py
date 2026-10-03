#!/usr/bin/env python3
"""v0.9.14 acceptance — after the manual compact, the DISPLAYED ctx must drop (JAG-104).

Reported again as "il tasto non va ne nell app ne nella webui". The transcript DID
shrink (model summary), but `/api/context` kept reporting the cached REAL prompt
size from the previous turn (`_REAL_PROMPT_TOKENS`), so the meter did not move and
the button looked dead in BOTH clients (they read the same endpoint).
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="sf-ctxdrop-")
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


# deterministic summarizer so the test never calls the router
server._summarize_with_llm = lambda messages, model=None: "SUMMARY-IN-UN-RIGO"

sid = "drop-test"
sess = server.get_or_create_session(sid)
for i in range(20):
    server.append_message(sess, "user", "domanda %d %s" % (i, "lorem ipsum " * 30))
    server.append_message(sess, "assistant", "risposta %d %s" % (i, "dolor sit amet " * 30))

# simulate the state right after a real turn: the router reported a big prompt size
server._REAL_PROMPT_TOKENS[sid] = 999_999
before = server.context_usage(sid)
check("R1 the meter reports the cached REAL value before compaction (source=model)",
      before["tokens_used"] == 999_999 and before["source"] == "model",
      "used=%s source=%s" % (before["tokens_used"], before["source"]))

res = server.compact_session(sid)
after = server.context_usage(sid)

check("R2 compaction actually shrank the transcript",
      res["tokens_after"] < res["input_tokens"] and res["compacted"] > 0,
      "tokens %s -> %s compacted=%s" % (res["input_tokens"], res["tokens_after"],
                                        res["compacted"]))
check("R3 the stale REAL size is no longer reported (meter falls back to estimate)",
      after["source"] == "estimate" and after["tokens_used"] != 999_999,
      "used=%s source=%s" % (after["tokens_used"], after["source"]))
check("R4 the DISPLAYED tokens drop after the button (what the user sees)",
      after["tokens_used"] < before["tokens_used"],
      "displayed %s -> %s" % (before["tokens_used"], after["tokens_used"]))
check("R5 the estimate matches the shrunken transcript + system prompt",
      after["tokens_used"] == after["estimate_tokens_used"]
      and after["estimate_tokens_used"] < before["estimate_tokens_used"],
      "estimate %s -> %s" % (before["estimate_tokens_used"], after["estimate_tokens_used"]))

print("\n==== %d/%d checks passed ====" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
