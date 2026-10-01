#!/usr/bin/env python3
"""SparkForge v0.95 acceptance — governed memory consolidation (memory.py).

Tests score persistence, time decay, dedupe and ranking. Exit 0 iff all pass.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import memory  # noqa: E402


def check(name, ok, detail=""):
    print("%s %s %s" % ("PASS" if ok else "FAIL", name, detail))
    return bool(ok)


def main():
    ok = True
    now = 1_000_000.0
    hl = 7 * 86400.0

    # recency decay: same score, newer wins
    newer = {"content": "x", "ts": now, "score": 1.0}
    older = {"content": "x", "ts": now - 10 * 86400.0, "score": 1.0}
    ok &= check("recency decays effective score",
                memory.effective_score(newer, now=now, halflife=hl) > memory.effective_score(older, now=now, halflife=hl))

    # a much higher score can outrank a fresher low score (but bounded by decay)
    high_old = {"ts": now - 86400.0, "score": 2.0}
    low_new = {"ts": now, "score": 0.1}
    ok &= check("score dominates when materially higher",
                memory.effective_score(high_old, now=now, halflife=hl) > memory.effective_score(low_new, now=now, halflife=hl))

    # dedupe near-identical lessons (context-collapse / inflation guard)
    recs = [
        {"content": "cache grep results before editing"},
        {"content": "cache grep results before editing"},
        {"content": "always run pytest after a fix"},
    ]
    ok &= check("dedupe collapses near-identical", len(memory.dedupe(recs, threshold=0.8)) == 2,
                str(len(memory.dedupe(recs, threshold=0.8))))

    # score is persisted to front-matter (external, harness-set, no self-rating)
    md = memory._render_md({"ts": now, "kind": "agent.note", "content": "x", "score": 1.5})
    ok &= check("score persisted in front-matter", "score: 1.5" in md)

    # rank sorts by effective score desc
    ranked = memory.rank([{"ts": now - 10.0, "score": 1.0}, {"ts": now, "score": 3.0}], now=now, halflife=hl)
    ok &= check("rank by effective score desc", ranked[0]["score"] == 3.0 and ranked[1]["score"] == 1.0)

    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())