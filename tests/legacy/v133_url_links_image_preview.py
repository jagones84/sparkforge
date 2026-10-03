#!/usr/bin/env python3
"""v0.9.34 acceptance — external URL links + in-app image preview (JAG-127e).

 L  a reply's http(s) URLs are linkified: sites open in a new tab
    (target=_blank rel=noopener), images open an in-app preview overlay.
 U  the overlay #imgView/#imgBackdrop exists, showImage/closeImage wired, and Esc
    closes it; linkifyAll covers every message bubble.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
html = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8", errors="replace").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


check("L1 URL regex defined", "const URL_RE = /https?:\\/\\/" in html, "")
check("L2 URLs are matched alongside local paths",
      "new RegExp(\"(\" + URL_RE.source + \")|(\" + READABLE_RE.source + \")\"" in html, "")
check("L3 sites open in a new tab (safe rel)",
      'target="_blank" rel="noopener noreferrer" class="weblink"' in html, "")
check("L4 image URLs become imglink",
      'class="imglink" data-u="' in html and "function _isImage" in html, "")
check("L5 trailing sentence punctuation trimmed from the URL",
      'const trail = u.match(/[.,;:!?]+$/)' in html, "")
check("L6 image extension detection",
      "\\.(png|jpe?g|gif|svg|webp|bmp|avif|ico)(\\?|#|$)" in html, "")

check("U1 overlay markup present", 'id="imgView"' in html and 'id="imgBackdrop"' in html, "")
check("U2 showImage wires the img + caption + external link",
      "function showImage(url)" in html and '$("imgEl").src = url' in html and '$("imgOpen").href = url' in html, "")
check("U3 closeImage hides + clears", "function closeImage()" in html and '$("imgView").hidden = true' in html, "")
check("U4 imglink click opens the preview",
      'querySelectorAll("a.imglink").forEach' in html and "showImage(a.dataset.u)" in html, "")
check("U5 Esc closes the preview", "closeSkillView(); closeImage();" in html, "")
check("U6 linkify covers every bubble",
      'document.querySelectorAll("#log .msg .bubble").forEach(linkifyFiles)' in html, "")
check("U7 overlay styled", "#imgView {" in html and "#imgView img {" in html, "")

total = len(results)
passed = sum(results)
print("\n==== %d/%d checks passed ====" % (passed, total))
sys.exit(0 if passed == total else 1)
