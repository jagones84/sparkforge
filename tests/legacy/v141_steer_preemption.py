#!/usr/bin/env python3
"""v0.9.38 acceptance — steer preemption (JAG-129D)."""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


srv = open(os.path.join(REPO, "src", "sparkforge", "server.py"), encoding="utf-8", errors="replace").read()
check("D1 has has_steer helper", "def has_steer" in srv, "")
check("D2 steer drained before the model call", "drain_steer" in srv and
      srv.count("drain_steer") >= 2, "")
check("D3 steer drained at the close point too", "steer=has_steer" in srv, "")
check("D4 chat.steer carries applied flag", "applied=True" in srv, "")

total = len(results)
print("\n==== %d/%d checks passed ====" % (sum(results), total))
sys.exit(0 if all(results) else 1)