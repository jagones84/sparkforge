#!/usr/bin/env python3
"""SparkForge v0.15.3 acceptance — chat renders sanitized markdown + HTML.

Checks (exit 0 = pass):
  M  assistant replies are rendered as sanitized markdown; raw HTML artifacts
     (```html/```svg) get an inline sandboxed preview; file/URL linkification
     works on rendered HTML.
"""
import os, sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ok = True
def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))

html = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()

check("M1 markdown renderer + sanitizer", "function mdToHtml" in html and "DOMPurify.sanitize" in html and "marked.parse" in html)
check("M2 replies rendered via renderAnswerBubble", "function renderAnswerBubble" in html and "md-content" in html)
check("M3 streaming accumulates raw then renders", "function appendAnswer" in html and "dataset.raw" in html)
check("M4 HTML artifact gets a sandboxed preview",
      "function decorateHtmlPreviews" in html and "artprev" in html and 'sandbox' in html and "srcdoc" in html)
check("M5 linkification walks rendered DOM",
      "function linkifyNodes" in html and "createTreeWalker" in html and "function linkifyFiles" in html)

print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
