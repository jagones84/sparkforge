#!/usr/bin/env python3
"""v207 — ABUSE / crash-resistance (RDD+TDD, hard & tricky).

Adversarial, deterministic, no model. Hammers the harness with degenerate,
malicious and pathological inputs and asserts it DEGRADES GRACEFULLY — designed
errors (ValueError/KeyError) are fine, UNEXPECTED exceptions or HANGS are bugs.

  G) taskgraph: bad status/label, unknown ids, cycles, 100k labels, emoji,
     observed-completion, concurrency;
  M) memory: 50k content, emoji round-trip, catastrophic regex, corrupt store;
  H) held-out gate: non-JSON / wrong-type manifest, dir-is-a-file, pin;
  P) path resolution: traversal, null byte, absolute-outside-roots;
  T) tools: malformed args never raise;
  S) skills: empty / regex-junk / 100k query.

Run:  python3 tests/v207_abuse_hard.py
"""
import atexit
import os
import shutil
import signal
import sys
import tempfile
import threading

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_tmp = tempfile.mkdtemp(prefix="sf-207-")
atexit.register(lambda: shutil.rmtree(_tmp, ignore_errors=True))
os.environ["SPARKFORGE_GRAPH_DIR"] = os.path.join(_tmp, "graphs")
os.environ["SPARKFORGE_HELDOUT_DIR"] = os.path.join(_tmp, "heldout")
os.environ["SPARKFORGE_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.environ["SPARKFORGE_SESSIONS_DIR"] = os.path.join(_tmp, "sessions")
os.environ["SPARKFORGE_DB"] = os.path.join(_tmp, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


class _TO(Exception):
    pass


signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(_TO()))


def bounded(secs, fn, *a, **k):
    """Run fn with a wall-clock bound. Returns ('ok', val) | ('timeout', None) | ('exc', err)."""
    signal.setitimer(signal.ITIMER_REAL, secs)
    try:
        return "ok", fn(*a, **k)
    except _TO:
        return "timeout", None
    except Exception as e:  # noqa: BLE001
        return "exc", e
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


from sparkforge import taskgraph, memory as mem, heldout, registry, tools, skills  # noqa: E402

# ---- G: taskgraph abuse ----
g = taskgraph.ensure("run_abuse", session_id="run_abuse", goal="abuse")
k, v = bounded(2, taskgraph.add_node, g, "x", status="bogus")
check("G1 invalid status -> ValueError (no crash)", k == "exc" and isinstance(v, ValueError))
k, v = bounded(2, taskgraph.add_node, g, "")
check("G2 empty label -> ValueError", k == "exc" and isinstance(v, ValueError))
k, v = bounded(2, taskgraph.update_node, g, "nope", status="doing")
check("G3 unknown node -> KeyError", k == "exc" and isinstance(v, KeyError))

a = taskgraph.add_node(g, "cycle a")
b = taskgraph.add_node(g, "cycle b")
taskgraph.update_node(g, a["id"], deps=[b["id"]])
taskgraph.update_node(g, b["id"], deps=[a["id"]])
k, v = bounded(2, taskgraph.render_todos, g)
check("G4 cyclic deps render without hang", k == "ok", "all_done=%s" % taskgraph.all_done(g))

biglabel = "L" * 100000
n = taskgraph.add_node(g, biglabel)
check("G5 100k label capped to 200", len(n["label"]) <= 200, "len=%d" % len(n["label"]))

emo = taskgraph.add_node(g, "✅ caffè 🚀 你好")
check("G6 emoji/unicode label preserved", "caffè" in emo["label"] and "🚀" in emo["label"])

k, v = bounded(2, taskgraph.audit_node, g, "nope")
check("G7 audit unknown fails safe", k == "ok" and v.get("ok") is False)

k, v = bounded(2, taskgraph.complete_node, g, None, "brand-new-by-label", "did it", None, True)
check("G8 complete a never-seen label (observed) doesn't crash", k == "ok")

ids = []
lock = threading.Lock()


def _burst():
    n2 = taskgraph.add_node(g, "burst")
    with lock:
        ids.append(n2["id"])


ths = [threading.Thread(target=_burst) for _ in range(40)]
[t.start() for t in ths]
[t.join() for t in ths]
check("G9 40 concurrent add_node -> unique ids", len(set(ids)) == 40, "unique=%d" % len(set(ids)))

# ---- M: memory abuse ----
mem.DATA_DIR = os.path.join(_tmp, "mem")
mem.CORE_PATH = os.path.join(mem.DATA_DIR, "core.md")
mem._vector_db = {}
mem._writes_since_index = 0
os.makedirs(mem.DATA_DIR, exist_ok=True)
rec = mem.store("memory.store", "Z" * 50000)
check("M1 50k content capped at 8000", len(rec["content"]) == 8000, "len=%d" % len(rec["content"]))
rec2 = mem.store("memory.store", "emoji ✅ 你好 🚀 null\x00inside")
back = [r for r in mem.query(None, "memory.store", 100) if r.get("mid") == rec2["mid"]]
check("M2 unicode/null round-trip", back and "🚀" in back[0]["content"], str(back)[:60])

k, v = bounded(2, mem._match, "a" * 4000 + "b", "(a+)+$")
check("M3 catastrophic regex does NOT hang", k != "timeout", str(k))

k, v = bounded(2, mem.invalidate, "nonexistent-mid", "abuse")
check("M4 invalidate unknown target safe", k == "ok")

with open(os.path.join(mem.DATA_DIR, "user_memories.md"), "ab") as f:
    f.write(b"\xff\xfe not utf8 \x80\x81\n")
k, v = bounded(3, mem.health)
check("M5 health on a CORRUPT (non-UTF8) store doesn't crash", k == "ok", str(v)[:60])

k, v = bounded(3, tools.execute, "memory", {})
check("M6 memory with no args -> ok False", k == "ok" and v.get("ok") is False)
k, v = bounded(3, tools.execute, "memory", {"action": "recall"})
check("M7 memory recall without query -> ok False", k == "ok" and v.get("ok") is False)

# ---- H: held-out gate abuse ----
os.makedirs(heldout.dir(), exist_ok=True)
with open(heldout.manifest_path(), "w") as f:
    f.write("{ this is not json ")
check("H1 non-JSON manifest -> None/red", heldout.load_manifest() is None
      and heldout.gate()["green"] is False)
with open(heldout.manifest_path(), "w") as f:
    f.write("[1,2,3]")
check("H2 wrong-type manifest -> None", heldout.load_manifest() is None)

filepath = os.path.join(_tmp, "heldout_is_a_file")
with open(filepath, "w") as f:
    f.write("x")
os.environ["SPARKFORGE_HELDOUT_DIR"] = filepath
k, v = bounded(2, heldout.integrity)
check("H3 dir-is-a-file -> graceful, no crash", k == "ok" and v["ok"] is False, str(v)[:50])
os.environ["SPARKFORGE_HELDOUT_DIR"] = os.path.join(_tmp, "heldout2")
k, v = bounded(2, heldout.pin)
check("H4 pin() on a fresh dir succeeds", k == "ok" and os.path.isfile(heldout.manifest_path()))

# ---- P: path resolution abuse ----
k, v = bounded(2, registry.resolve_path, "../../etc/passwd")
check("P1 traversal blocked", k == "ok" and v[1] is not None, str(v[1])[:40])
k, v = bounded(2, registry.resolve_path, "/etc/passwd", ["."])
check("P2 absolute outside roots blocked", k == "ok" and v[1] is not None, str(v[1])[:40])
k, v = bounded(2, registry.resolve_path, "a\x00b")
check("P3 null byte handled (no crash)", k != "exc" and k != "timeout", "%s %s" % (k, v))

# ---- T: tools never raise on malformed args ----
k, v = bounded(3, tools.execute, "does_not_exist", {})
check("T1 unknown tool -> graceful", k == "ok" and isinstance(v, dict), str(v)[:50])
k, v = bounded(3, tools.execute, "diff", {"action": "files"})
check("T2 diff missing paths -> ok False", k == "ok" and v.get("ok") is False, str(v)[:50])

# ---- S: skills abuse ----
k, v = bounded(3, skills.search_skills, "")
check("S1 empty query -> list (no crash)", k == "ok" and isinstance(v, list))
k, v = bounded(3, skills.search_skills, "((((")
check("S2 regex-junk query -> no crash", k == "ok")
k, v = bounded(3, skills.search_skills, "a" * 100000)
check("S3 100k query does NOT hang", k != "timeout", str(k))

shutil.rmtree(_tmp, ignore_errors=True)
ok = sum(results)
print("\nv207: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
