#!/usr/bin/env python3
"""v225 — compaction must ALWAYS terminate, fast, on adversarial inputs.

Context (JAG-225): an orphaned diagnostic harness (`trash/diag_ctx.py`) was found
spinning one core for >1h. Timeline shows the process started BEFORE the JAG-214
fix landed, i.e. it was running a stale in-memory code snapshot — the spin is NOT
reproducible on the current code. This test LOCKS the guarantee that no input can
make `context_engine.compact` (and the residual shrink loop in particular) run
away, so a future regression fails loudly instead of burning a CPU.

Deterministic, no model. Run:  python3 tests/v225_compact_bounded.py
"""
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.model import context_engine   # noqa: E402

results = []
LIMIT = 3.0   # seconds; a runaway loop would blow this by orders of magnitude


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def msgs(n, size, role="user"):
    return [{"role": role, "content": "x" * size} for _ in range(n)]


def timed(label, messages, budget, **kw):
    t0 = time.perf_counter()
    out, stats = context_engine.compact(messages, budget, **kw)
    dt = time.perf_counter() - t0
    check("%s returns in %d ms (< %ss)" % (label, int(dt * 1000), LIMIT), dt < LIMIT,
          "%.3fs" % dt)
    return out, stats


# A: one giant paste, forced (manual compact) against a tiny budget
out, stats = timed("A single 1M-char message", msgs(1, 1_000_000), 5000, force=True)
check("A2 a summary was produced", stats.get("summary") in ("llm", "extractive"),
      "summary=%r" % stats.get("summary"))
check("A3 output is tiny (not re-expanded)", len(out) <= 2, "out=%d" % len(out))

# B: thousands of tiny messages
out, stats = timed("B 5000 tiny messages", msgs(5000, 4), 5000, force=True)
check("B2 it shrank below the input", stats["output_tokens"] < stats["input_tokens"],
      "%d -> %d" % (stats["input_tokens"], stats["output_tokens"]))

# C: many LARGE messages — stresses any quadratic shrink loop
out, stats = timed("C 300 x 50k-char messages", msgs(300, 50_000), 5000, force=True)
check("C2 output never bigger than input",
      stats["output_tokens"] <= stats["input_tokens"],
      "%d -> %d" % (stats["input_tokens"], stats["output_tokens"]))

# D: absurd budget (1 token) — cannot shrink below one turn, must still return
out, stats = timed("D budget=1", msgs(50, 4000), 1, force=True)
check("D2 a transcript is returned", isinstance(out, list) and len(out) >= 1,
      "out=%d" % len(out))

# E: a summarizer that always fails -> extractive fallback, still bounded
out, stats = timed("E failing summarizer", msgs(100, 20_000), 5000,
                   force=True, summarizer=lambda old: None)
check("E2 extractive fallback used", stats.get("summary") == "extractive",
      "summary=%r" % stats.get("summary"))

# F: empty input is a no-op
out, stats = context_engine.compact([], 5000)
check("F empty input -> empty output", out == [] and stats["input_messages"] == 0,
      "out=%d" % len(out))

# G: keep_recent=0 (summarize everything) stays bounded
out, stats = timed("G keep_recent=0", msgs(200, 10_000), 5000, keep_recent=0)

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

