#!/usr/bin/env python3
"""v0.9.37 acceptance — architettura prompt a registro (JAG-128A)."""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def read(p):
    try:
        return open(p, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""


import prompt  # noqa: E402

check("A1 module has render_sections + SECTIONS",
      hasattr(prompt, "render_sections") and hasattr(prompt, "SECTIONS"), "")
ids = [s["id"] for s in prompt.SECTIONS]
check("A2 core sections present",
      {"identity", "tools", "memory", "capability", "prompt-map"}.issubset(set(ids)),
      str(ids))
check("A3 every section kind is static|dynamic",
      all(s.get("kind") in ("static", "dynamic") for s in prompt.SECTIONS), "")

out = prompt.render_sections(None)
check("A4 render non-empty", bool(out.strip()), str(len(out)))
check("A5 identity text present", "SparkForge" in out, "")
check("A6 tool registry block present", "Tool registry" in out, "")

total = len(results)
print("\n==== %d/%d checks passed ====" % (sum(results), total))
sys.exit(0 if all(results) else 1)
