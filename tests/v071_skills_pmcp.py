#!/usr/bin/env python3
"""SparkForge v0.7.1 acceptance — JAG-56: skills nel harness + pmcp end-to-end.

Evidence, not claims. Checks:

  A. skills/ tree (symlinks into skills-autodist-skill) is scanned by the
     loader: every category found, >50 skills, each with a SKILL.md.
  B. the `skills` tool works through the registry: list shows all categories,
     read returns a real SKILL.md body; `self` reports skills + install recipe.
  C. agent loop (POST /api/agent/run, live router LLM): at least one real
     pmcp tools/call with backend mcp(pmcp) and the MCP output recorded as an
     observation in the transcript. Full transcript saved to
     data/v071-transcript.json.

Usage: python3 tests/v071_skills_pmcp.py
Exit code 0 iff every check passed. Report: data/v071-acceptance.json
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

RESULTS = {"task": "JAG-56 v0.7.1 skills + pmcp end-to-end", "checks": [], "passed": False}


def check(name, ok, detail=""):
    RESULTS["checks"].append({"name": name, "ok": bool(ok), "detail": str(detail)[:400]})
    print("%s %s %s" % ("PASS" if ok else "FAIL", name, detail))
    return bool(ok)


def main():
    ok = True
    import skills as skills_mod
    import tools as toolmod
    import registry

    # ---- A: loader sees the symlinked skill distribution --------------------
    sk = skills_mod.list_skills(reload=True)
    cats = sorted({s["category"] for s in sk})
    ok &= check("A1 skills discovered", len(sk) > 50, "%d skills" % len(sk))
    ok &= check("A2 all categories present",
                set(cats) >= {"android", "data", "dev", "meta", "ops", "research", "tg"},
                cats)
    ok &= check("A3 each skill has a SKILL.md",
                all(os.path.isfile(os.path.join(REPO, s["path"])) for s in sk[:20]),
                "sampled 20 paths")
    ok &= check("A4 symlinks live", os.path.islink(os.path.join(REPO, "skills", "ops")),
                "skills/ops -> %s" % os.readlink(os.path.join(REPO, "skills", "ops")))

    # ---- B: skills tool + self report ---------------------------------------
    r = toolmod.execute("skills", {"action": "list"})
    ok &= check("B1 skills list ok", r.get("ok") and r.get("count", 0) > 50,
                r.get("stdout", "")[:160])
    r = toolmod.execute("skills", {"action": "read", "name": "paperclip"})
    ok &= check("B2 skills read ok", r.get("ok") and "Paperclip" in r.get("stdout", ""),
                "bytes=%d" % len(r.get("stdout", "")))
    ok &= check("B3 skills read unknown -> clean error",
                not toolmod.execute("skills", {"action": "read", "name": "no-such"}).get("ok"))
    spec = registry.tool_spec("skills")
    ok &= check("B4 skills in registry, auto-approved",
                spec and spec["enabled"] and spec["approval"] == "auto", spec["approval"])
    slf = toolmod.execute("self", {})
    ok &= check("B5 self reports skills", slf.get("skills", {}).get("count", 0) > 50,
                slf.get("skills"))
    ok &= check("B6 self has install recipe", "SKILL.md" in slf.get("install_skill", ""),
                "install_skill present")

    # ---- C: end-to-end agent run with a real pmcp tools/call ----------------
    base = "http://127.0.0.1:%d" % int(os.environ.get("SPARKFORGE_TEST_PORT", 8797))
    env = dict(os.environ)
    env.setdefault("SPARKFORGE_ROUTER", "http://127.0.0.1:8080")
    inst = subprocess.Popen([sys.executable, os.path.join(REPO, "server.py"),
                             "--host", "127.0.0.1", "--port", base.rsplit(":", 1)[1]],
                            cwd=REPO, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    transcript = None
    try:
        for _ in range(30):
            try:
                urllib.request.urlopen(base + "/api/tools", timeout=2)
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.5)

        def post(path, body, timeout=300):
            req = urllib.request.Request(base + path, data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
            return json.load(urllib.request.urlopen(req, timeout=timeout))

        run = post("/api/agent/run", {
            "goal": "Call the tool pmcp__gateway.health with empty args, report "
                    "what it returned in the observation, then finish.",
            "max_steps": 5})
        transcript = run
        steps = run.get("trace", [])
        mcp_steps = [e for e in steps if e.get("action") == "tool" and
                     (e.get("tool") or "").startswith("pmcp__")]
        ok &= check("C1 agent run executed a pmcp tools/call", len(mcp_steps) >= 1,
                    json.dumps(mcp_steps[0])[:300] if mcp_steps else
                    json.dumps(steps)[:300])
        if mcp_steps:
            obs = mcp_steps[0].get("observation") or ""
            ok &= check("C2 observation non-empty (MCP output as observation)",
                        bool(obs.strip()) and "ERROR" not in obs.splitlines()[0],
                        obs[:200])
        ok &= check("C3 run finished", any(e.get("action") == "finish" for e in steps),
                    [e.get("action") for e in steps])
    except Exception as e:  # noqa: BLE001
        ok &= check("C1 agent run executed a pmcp tools/call", False, "skipped: %s" % e)
    finally:
        inst.terminate()
        try:
            inst.wait(timeout=5)
        except Exception:  # noqa: BLE001
            inst.kill()

    RESULTS["passed"] = bool(ok)
    os.makedirs(os.path.join(REPO, "data"), exist_ok=True)
    with open(os.path.join(REPO, "data", "v071-acceptance.json"), "w",
              encoding="utf-8") as f:
        json.dump(RESULTS, f, indent=2)
    if transcript:
        with open(os.path.join(REPO, "data", "v071-transcript.json"), "w",
                  encoding="utf-8") as f:
            json.dump(transcript, f, indent=2, ensure_ascii=False)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())