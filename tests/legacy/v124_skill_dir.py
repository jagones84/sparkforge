#!/usr/bin/env python3
"""SparkForge v0.12.4 acceptance — JAG-122: skill activation carries SKILL_DIR.

Root cause fixed: `/skill` injected only the SKILL.md text (which uses the
Claude-Code-only ${CLAUDE_SKILL_DIR}), so the model guessed the script path,
ran an unbounded `find /home/jagones`, and timed out (shell exit 124).

Checks:
  S. _apply_skill_slash injects the skill's ABSOLUTE directory + a substitution
     hint; unknown skills and /goal are left untouched.

Usage: python3 tests/v124_skill_dir.py
Exit code 0 iff every check passed.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

RESULTS = {"task": "JAG-122 skill dir injection", "checks": [], "passed": False}


def check(name, ok, detail=""):
    RESULTS["checks"].append({"name": name, "ok": bool(ok), "detail": str(detail)[:400]})
    print("%s %s %s" % ("PASS" if ok else "FAIL", name, detail))
    return bool(ok)


def main():
    ok = True
    from sparkforge import server

    out = server._apply_skill_slash("/pdf-monster leggi il pdf")
    ok &= check("S1 SKILL ACTIVATION header", "SKILL ACTIVATION" in out)
    ok &= check("S2 SKILL_DIR line present", "SKILL_DIR:" in out)
    ok &= check("S3 absolute skill dir injected",
                os.path.join("skills", "ops", "pdf-monster") in out, "")
    ok &= check("S4 substitutions hint (CLAUDE_SKILL_DIR)",
                "CLAUDE_SKILL_DIR" in out)
    ok &= check("S5 SKILL.md body injected", "PDF Monster" in out)
    ok &= check("S6 user text kept", "leggi il pdf" in out)
    ok &= check("S7 the dir really exists",
                os.path.isdir(os.path.join(REPO, "skills", "ops", "pdf-monster")))

    # untouched cases
    ok &= check("S8 unknown skill unchanged",
                server._apply_skill_slash("/no-such-skill hi") == "/no-such-skill hi")
    ok &= check("S9 /goal untouched",
                server._apply_skill_slash("/goal do the thing") == "/goal do the thing")
    ok &= check("S10 plain message unchanged",
                server._apply_skill_slash("ciao") == "ciao")

    RESULTS["passed"] = bool(ok)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
