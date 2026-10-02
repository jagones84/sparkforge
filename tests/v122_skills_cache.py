#!/usr/bin/env python3
"""SparkForge v0.12.2 acceptance — skills cache invalidation + Plan/Esecuzione labels.

Evidence, not claims. Checks:

  A. list_skills() cache is invalidated when a skill is added to a CATEGORY dir
     (the real case: category dirs are symlinks into the autodist store, so the
     top-level mtime does NOT change — the old cache stayed stale until restart).
  B. the real store now contains the adopted `pdf-monster` skill (ops category).
  C. the WebUI Graph panel labels Plan/Esecuzione distinctly (no ambiguous
     "Plan" / "Tasks" pair).

Usage: python3 tests/v122_skills_cache.py
Exit code 0 iff every check passed.
"""
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

RESULTS = {"task": "JAG-121b skills cache + UI labels", "checks": [], "passed": False}


def check(name, ok, detail=""):
    RESULTS["checks"].append({"name": name, "ok": bool(ok), "detail": str(detail)[:400]})
    print("%s %s %s" % ("PASS" if ok else "FAIL", name, detail))
    return bool(ok)


def _mk(base, cat, name):
    d = os.path.join(base, cat, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write("---\nname: %s\ndescription: test skill\n---\n# %s\n" % (name, name))


def main():
    ok = True
    import skills as S

    real_dir = S.SKILLS_DIR
    tmp = tempfile.mkdtemp(prefix="sf_skills_")
    for cat in ("ops", "dev"):
        os.makedirs(os.path.join(tmp, cat), exist_ok=True)

    try:
        S.SKILLS_DIR = tmp
        S._cache.update(sig=None, skills=[])
        _mk(tmp, "ops", "alpha")
        n1 = len(S.list_skills())
        ok &= check("A1 first scan sees 1 skill", n1 == 1, n1)

        # add a skill to an EXISTING category WITHOUT reload=True.
        time.sleep(0.02)
        _mk(tmp, "ops", "beta")
        n2 = len(S.list_skills())
        ok &= check("A2 cache invalidated on category change (no restart)",
                    n2 == 2, "was %d, now %d" % (n1, n2))

        time.sleep(0.02)
        _mk(tmp, "dev", "gamma")
        n3 = len(S.list_skills())
        ok &= check("A3 another category change seen too", n3 == 3, n3)

        S.SKILLS_DIR = os.path.join(tmp, "does-not-exist")
        ok &= check("A4 missing dir -> sig None, empty list",
                    S._skills_sig() is None and S.list_skills() == [],
                    S._skills_sig())
    finally:
        S.SKILLS_DIR = real_dir
        S._cache.update(sig=None, skills=[])

    # ---- B: the real store now carries pdf-monster --------------------------
    live = S.list_skills(reload=True)
    names = {s["name"]: s for s in live}
    ok &= check("B1 pdf-monster present in the store", "pdf-monster" in names,
                sorted(n for n in names if "pdf" in n.lower()) or "%d skills" % len(live))
    if "pdf-monster" in names:
        ok &= check("B2 pdf-monster in ops category",
                    names["pdf-monster"]["category"] == "ops",
                    names["pdf-monster"]["category"])

    # ---- C: UI labels are distinct ------------------------------------------
    with open(os.path.join(REPO, "webui", "index.html"), "r", encoding="utf-8") as f:
        html = f.read()
    ok &= check("C1 heading 'Plan · session task list'",
                "Plan <span" in html and "session task list" in html)
    ok &= check("C2 heading 'Execution · run graph'",
                "Execution <span" in html and "run graph (current run)" in html)

    RESULTS["passed"] = bool(ok)
    if not ok:
        for c in RESULTS["checks"]:
            if not c["ok"]:
                print("  ->", c["name"], c["detail"])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
