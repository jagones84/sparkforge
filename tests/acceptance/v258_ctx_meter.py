#!/usr/bin/env python3
"""v258 — the context meter must measure with the SAME model as the turn (JAG-258).

The WebUI's meter (`loadCtx` -> GET /api/context without `model`) used to fall
back to whatever model the router happened to have loaded (n_ctx 32768), so a
healthy 131k-window session read as 99% full — while the auto-compaction trigger,
which uses the session's own model, correctly saw 22% and never fired. The single
rule `resolve_ctx_model` (explicit > session model > default) is what /api/context
now uses, so meter and trigger can no longer disagree.

Deterministic, no live server, no network. Run: python3 tests/v258_ctx_meter.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v258-")
os.environ["SPARKFORGE_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["SPARKFORGE_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["SPARKFORGE_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["SPARKFORGE_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["SPARKFORGE_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from sparkforge import server as s  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


WIN = "win:nex-n2.5-mini-uncensored-iq4xs"

# the resolution rule
check("explicit model wins", s.resolve_ctx_model({"model": "a"}, "b") == "b")
check("session model is used when none explicit",
      s.resolve_ctx_model({"model": WIN}, None) == WIN)
check("default fallback when neither", s.resolve_ctx_model({"model": ""}, None) == s.default_model())
check("None session is safe", s.resolve_ctx_model(None, None) == s.default_model())

# the fix's observable effect: the meter's budget follows the resolved (session)
# model, never the arbitrary router-loaded model.
sess = {"id": "x", "model": WIN, "messages": []}
resolved = s.resolve_ctx_model(sess, None)
check("meter budget follows the resolved model",
      s.context_budget(resolved) == s.context_budget(WIN),
      "resolved=%s" % s.context_budget(resolved))

# static guard: the /api/context handler routes through the resolver
with open(os.path.join(REPO, "src", "sparkforge", "server.py"), encoding="utf-8") as f:
    sv = f.read()
with open(os.path.join(REPO, "src", "sparkforge", "httpapi.py"), encoding="utf-8") as f:
    sv += f.read()
check("JAG-258 /api/context uses resolve_ctx_model",
      "resolve_ctx_model(load_session(_sid)" in sv)
check("JAG-258 resolver is the single source (explicit > session > default)",
      "return (sess.get(\"model\") if sess else None) or default_model()" in sv)

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
