#!/usr/bin/env python3
"""JAG-98 — the LIVE ctx meter must use the model's REAL prompt_tokens.

Regression: `context.built` carried only the chars/4 estimate (`final_tokens`),
which for Italian under-reports ~10% and does not grow as tool observations are
appended. The live FORGE/PULSE meter must reflect the model's real count.

Mirrors the v087 stubbing style: the model is faked, the loop is real.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("SPARKFORGE_DB", os.path.join(REPO, "data", "events.db"))

import server  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ((" — " + detail) if detail else ""))


REAL = 12345  # deliberately far from any chars/4 estimate


def fake_stream(msgs, model, kind, on_delta, timeout=300, usage=None):
    # emulate the router reporting the REAL prompt size on this turn
    if usage is not None:
        usage["prompt_tokens"] = REAL
    return ("Ecco la risposta finale.", "", model)


server.stream_with_fallback = fake_stream

sid = "jag98-ctx-real"
sess = server.get_or_create_session(sid)
events = []


def on_event(t, **kw):
    events.append((t, kw))


server.chat_once(sess, "domanda corta", None, on_event=on_event)

built = [kw for (t, kw) in events if t == "context.built"]
check("A1 a context.built event is emitted", len(built) >= 1, "n=%d" % len(built))
check("A2 the live ctx carries the model's REAL prompt_tokens",
      any(kw.get("final_tokens") == REAL for kw in built),
      "final_tokens=%s" % [kw.get("final_tokens") for kw in built])
check("A3 the LAST context.built reflects the real count",
      bool(built) and built[-1].get("final_tokens") == REAL,
      "last=%s" % (built[-1].get("final_tokens") if built else None))
check("A4 budget is carried too", any(kw.get("budget_tokens") for kw in built),
      "budget=%s" % [kw.get("budget_tokens") for kw in built])

fails = [r for r in results if not r]
print("\n=== %d/%d checks passed ===" % (len(results) - len(fails), len(results)))
sys.exit(1 if fails else 0)
