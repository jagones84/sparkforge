#!/usr/bin/env python3
"""v0.9.38 acceptance — metriche per run (JAG-129E)."""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))
os.environ["SPARKFORGE_RUNS_DIR"] = tempfile.mkdtemp()
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


from sparkforge import runmetrics  # noqa: E402

runmetrics.start("k1", model="m1")
rec = runmetrics.finish("k1", outcome="done", stop_reason="goal_reached",
                        iterations=3, steps=5, tokens=1234)
check("E1 duration recorded", rec.get("duration_s") is not None and rec["duration_s"] >= 0, "")
check("E2 fields recorded",
      rec["outcome"] == "done" and rec["stop_reason"] == "goal_reached"
      and rec["iterations"] == 3 and rec["steps"] == 5 and rec["tokens"] == 1234, str(rec))
check("E3 persisted to disk", runmetrics.get("k1")["outcome"] == "done", "")
check("E4 human readable line", "goal_reached" in runmetrics.human("k1"), "")

from sparkforge import registry  # noqa: E402
_cfg = registry.load_config()
check("E5 runtime default present for metrics",
      isinstance(_cfg.get("runtime"), dict)
      and _cfg["runtime"].get("keepgoing_max") == 8, str(_cfg.get("runtime")))

rec2 = runmetrics.finish("k2", outcome="error", stop_reason="error", model="m2",
                        prompt_tokens=100, completion_tokens=200)
check("E6 prompt/completion tokens split",
      rec2["prompt_tokens"] == 100 and rec2["completion_tokens"] == 200, str(rec2))
check("E7 model recorded on finish", rec2.get("model") == "m2", str(rec2.get("model")))
check("E8 error outcome recorded", rec2.get("outcome") == "error", "")
srv = open(os.path.join(REPO, "src", "sparkforge", "server.py"), encoding="utf-8", errors="replace").read()
check("E9 error run recorded in stream catch",
      'outcome="error"' in srv and "chat.error" in srv, "")

total = len(results)
print("\n==== %d/%d checks passed ====" % (sum(results), total))
sys.exit(0 if all(results) else 1)