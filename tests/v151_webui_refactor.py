#!/usr/bin/env python3
"""SparkForge v0.15.1 acceptance — WebUI refactor (inspector + movable settings).

Static checks over webui/index.html (exit 0 = all passed):
  S  the floating Settings window exists (shell + 8 categories + drag/resize)
  I  the rail is an inspector with 5 collapsible sections
  T  the API token is masked by default (password + reveal + copy)
  C  the compaction-model control exists and targets /api/routing (summarizer)
  N  the old rail tabs (config/settings/mcp/skills/rules) are gone from #rail-tabs
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOTAL = 0
PASSED = 0


def check(name, cond, detail=""):
    global TOTAL, PASSED
    TOTAL += 1
    PASSED += 1 if cond else 0
    print(("PASS " if cond else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def main():
    with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
        html = f.read()

    # S — settings window
    check("S1 window shell present", 'id="settingsWin"' in html and "function openSettings" in html)
    check("S2 drag + resize + persist wired",
          "sf_settings_pos" in html and "function dragify" in html and "function resizify" in html)
    # JAG-160: "general" -> "info" (moved last), "providers" merged into "models",
    # "harness" split out of "tools".
    for cat in ["models", "keys", "mcp", "skills", "rules", "tools", "harness", "info"]:
        check("S3 category %r" % cat, ('data-cat="%s"' % cat) in html)

    # I — inspector
    check("I1 inspector container", 'id="inspector"' in html)
    for sec in ["plan", "context", "approvals", "files", "feed"]:
        check("I2 section %r" % sec, ('data-insp="%s"' % sec) in html)
    check("I3 collapsible + persisted", "sf_insp_" in html and "function toggleInsp" in html)

    # T — token masking
    check("T1 token masked by default",
          'id="token-input"' in html and 'type="password"' in html)
    check("T2 reveal toggle", "function revealToken" in html)
    check("T3 copy button", "function copyToken" in html and "navigator.clipboard" in html)

    # C — compaction model
    check("C1 control present", 'id="compactionModel"' in html)
    check("C2 targets /api/routing summarizer",
          "/api/routing" in html and "summarizer" in html)

    # N — old rail tabs removed
    rail = ""
    if 'id="rail-tabs"' in html:
        rail = html.split('id="rail-tabs"', 1)[1].split("</nav>", 1)[0]
    for gone in ['data-panel="config"', 'data-panel="settings"', 'data-panel="mcp"',
                 'data-panel="skills"', 'data-panel="rules"']:
        check("N gone %s" % gone, gone not in rail)

    print("\n==== %d/%d checks passed ====" % (PASSED, TOTAL))
    return 0 if PASSED == TOTAL else 1


if __name__ == "__main__":
    sys.exit(main())
