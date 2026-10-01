#!/usr/bin/env python3
"""SparkForge v0.8 acceptance — WebUI redesign (structural, offline).

Legge webui/index.html e verifica marker strutturali + assenza di regressioni.
Exit 0 iff ogni check passa. Report: data/v080-webui-acceptance.json
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(REPO, "webui", "index.html")
RESULTS = {"task": "v0.8 webui redesign", "checks": [], "passed": False}

PRESERVED_FUNCS = [
    "api(", "authQS(", "ensureToken(", "send(", "runAgent(", "loadSessions(", "loadHistory(",
    "loadPlan(", "loadCtx(", "loadStatus(", "loadApprovals(", "loadGraph(", "connectFeed(",
    "toolCard(", "openTab(",
]
PRESERVED_IDS = [
    "log", "inp", "sessions", "planSteps", "tasks", "ctxBar", "approvals", "feed", "cotDrawer",
]


def check(name, ok, detail=""):
    RESULTS["checks"].append({"name": name, "ok": bool(ok), "detail": str(detail)[:400]})
    print("%s %s %s" % ("PASS" if ok else "FAIL", name, detail))
    return bool(ok)


def html():
    with open(INDEX, encoding="utf-8") as fh:
        return fh.read()


def main():
    src = html()
    # --- Fase 1: tokens + shell 3 colonne + top bar ---
    check("accent token #8b7bf0", "--accent: #8b7bf0" in src)
    check("shell 3 colonne", all(m in src for m in ('data-col="sessions"', 'data-col="chat"', 'data-col="context"')))
    check("topbar presente", 'id="topbar"' in src)
    check("model chip", 'id="model-chip"' in src)
    check("ctx meter", 'id="ctx-meter"' in src)
    check("server badge", 'id="server-badge"' in src)
    check("responsive 1100", "@media (max-width: 1100px)" in src)
    check("responsive 820", "@media (max-width: 820px)" in src)
    # --- Anti-regressione: logica esistente preservata ---
    for fn in PRESERVED_FUNCS:
        check("kept func %s" % fn, fn in src)
    for eid in PRESERVED_IDS:
        check("kept id %s" % eid, ('id="%s"' % eid) in src)
    RESULTS["passed"] = all(c["ok"] for c in RESULTS["checks"])
    os.makedirs(os.path.join(REPO, "data"), exist_ok=True)
    with open(os.path.join(REPO, "data", "v080-webui-acceptance.json"), "w", encoding="utf-8") as fh:
        json.dump(RESULTS, fh, indent=2)
    print("RESULT:", "PASS" if RESULTS["passed"] else "FAIL")
    return 0 if RESULTS["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
