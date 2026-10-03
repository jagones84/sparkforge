#!/usr/bin/env python3
"""SparkForge v0.95 acceptance — process reward / verification engine (prm.py).

Offline unit test of the deterministic PRM core (no model call). Exit 0 iff all pass.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from sparkforge import prm  # noqa: E402


def check(name, ok, detail=""):
    print("%s %s %s" % ("PASS" if ok else "FAIL", name, detail))
    return bool(ok)


def main():
    ok = True
    # clean trajectory -> full score, no issues
    r = prm.evaluate([{"action": "tool", "tool": "shell", "args": {"command": "ls -la"}}], open_nodes=0)
    ok &= check("clean scores 1.0", r["score"] == 1.0 and not r["issues"], str(r))

    # step repetition flagged + lowers score
    r = prm.evaluate([
        {"action": "tool", "tool": "shell", "args": {"command": "grep foo ."}},
        {"action": "tool", "tool": "shell", "args": {"command": "grep foo ."}},
    ], open_nodes=0)
    ok &= check("repetition flagged", any(i["code"] == "step_repetition" for i in r["issues"]), str(r["issues"]))
    ok &= check("repetition lowers score", r["score"] < 1.0, str(r["score"]))

    # different args are NOT repetition
    r = prm.evaluate([
        {"action": "tool", "tool": "shell", "args": {"command": "grep a ."}},
        {"action": "tool", "tool": "shell", "args": {"command": "grep b ."}},
    ], open_nodes=0)
    ok &= check("different args not repetition", not any(i["code"] == "step_repetition" for i in r["issues"]))

    # verification skipped: finish while open_nodes remain
    r = prm.evaluate([{"action": "finish", "summary": "done"}], open_nodes=3)
    ok &= check("verification skipped flagged", any(i["code"] == "verification_skipped" for i in r["issues"]))

    # feedback text non-empty with issues, empty when clean
    ok &= check("feedback text present", bool(r["feedback"]))
    r2 = prm.evaluate([{"action": "tool", "tool": "fs.read", "args": {"path": "x"}}], open_nodes=0)
    ok &= check("clean feedback empty", r2["feedback"] == "" and not r2["issues"])

    # score clamps at 0
    many = [{"action": "tool", "tool": "t", "args": {"a": "same"}}] * 8
    r = prm.evaluate(many, open_nodes=0)
    ok &= check("score never negative", r["score"] >= 0.0, str(r["score"]))

    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())