#!/usr/bin/env python3
"""JAG-99 — auto-compaction must fire at the threshold AND leave headroom.

Bug found while verifying (user: "verifica se autocompact funziona"): the
transcript was compacted against the FULL budget, ignoring that the system prompt
(~3k tokens) already consumes it. So between 75% and ~100% of the budget
auto-compact fired uselessly and the prompt grew past the budget (observed 136%).

Expected AFTER the fix: once over the 75% threshold, auto-compact shrinks the
transcript so the total prompt lands back under the threshold and within budget.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))
os.environ["SPARKFORGE_CONTEXT_BUDGET"] = "8000"
os.environ.setdefault("SPARKFORGE_DB", os.path.join(REPO, "data", "events.db"))

from sparkforge import server  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ((" — " + detail) if detail else ""))


sid = "jag99-autocompact-accept"
sess = server.get_or_create_session(sid)
sess["messages"] = []
server.save_session(sess)

BLOCK = "RIGA NOTA: il coniglio saltella nel prato verde. " * 15

fired = False
after = None
msgs_before = 0
for i in range(1, 46):
    s = server.load_session(sid)
    server.append_message(s, "user", "domanda %d: %s" % (i, BLOCK))
    server.append_message(s, "assistant", "risposta %d: %s" % (i, BLOCK))
    u = server.context_usage(sid)
    if u["over_threshold"]:
        fired = True
        msgs_before = u["messages"]
        server.prepare_session_for_turn(server.load_session(sid))
        after = server.context_usage(sid)
        break

check("A1 auto-compact triggers when over threshold", fired,
      "threshold=%s%%" % server.AUTOCOMPACT_PCT)
check("A2 after compaction the prompt is back UNDER the threshold",
      bool(after) and after["pct"] < server.AUTOCOMPACT_PCT,
      "pct=%s (before %s msgs)" % (after and after["pct"], msgs_before))
check("A3 after compaction the prompt is WITHIN budget",
      bool(after) and after["tokens_used"] <= after["budget_tokens"],
      "used=%s budget=%s" % (after and after["tokens_used"], after and after["budget_tokens"]))
check("A4 the newest messages are kept (transcript shrunk, not wiped)",
      bool(after) and 2 <= after["messages"] < msgs_before,
      "msgs %d -> %s" % (msgs_before, after and after["messages"]))

fails = [r for r in results if not r]
print("\n=== %d/%d checks passed ===" % (len(results) - len(fails), len(results)))
sys.exit(1 if fails else 0)
