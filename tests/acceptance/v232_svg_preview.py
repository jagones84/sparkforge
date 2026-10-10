#!/usr/bin/env python3
"""v232 — /api/fs/raw must never serve a script container inline (JAG-232).

PROVEN stored XSS: `/api/fs/raw` allowed any `image/*` — including
`image/svg+xml`. Opened as a top-level document at the harness origin, an SVG's
embedded JS runs (verified in a real browser: an `<svg onload>` set a global and
`document.contentType` was `image/svg+xml`). The workspace is agent-writable, so
a planted `.svg` was a token-theft vector. `_fs_raw` now uses an allow-list of
INERT types (raster images + PDF) and every response carries `nosniff`.

Deterministic, no browser. Run:  python3 tests/v232_svg_preview.py
"""
import atexit
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-232-")
atexit.register(lambda: shutil.rmtree(_tmp, ignore_errors=True))
# /api/fs/raw resolves paths against the browse roots — point them at our temp dir
os.environ["LONGRUN_BROWSE_ROOTS"] = _tmp
sys.path.insert(0, os.path.join(REPO, "src"))
from longrun import api_v02  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


class Stub:
    def __init__(self):
        self.codes = []

    def _send(self, code, obj, ctype="application/json"):
        self.codes.append(code)


def write(name, data):
    p = os.path.join(_tmp, name)
    with open(p, "wb") as f:
        f.write(data)
    return p


svg = write("x.svg", b'<svg xmlns="http://www.w3.org/2000/svg" onload="x=1"/>')
png = write("x.png", b"\x89PNG\r\n\x1a\n" + b"0" * 16)
pdf = write("x.pdf", b"%PDF-1.4\n%%EOF")
html = write("x.html", b"<script>alert(1)</script>")

h = Stub()
api_v02._fs_raw(h, {"path": svg})
check("svg preview refused (415)", h.codes == [415], "codes=%s" % h.codes)

h = Stub()
api_v02._fs_raw(h, {"path": html})
check("html preview refused (415)", h.codes == [415], "codes=%s" % h.codes)

h = Stub()
api_v02._fs_raw(h, {"path": png})
check("png preview allowed (200)", h.codes == [200], "codes=%s" % h.codes)

h = Stub()
api_v02._fs_raw(h, {"path": pdf})
check("pdf preview allowed (200)", h.codes == [200], "codes=%s" % h.codes)

h = Stub()
api_v02._fs_raw(h, {"path": "/etc/passwd"})
check("outside-roots path still 404", h.codes == [404], "codes=%s" % h.codes)

# static guards
with open(os.path.join(REPO, "src", "longrun", "api_v02.py"), encoding="utf-8") as f:
    av = f.read()
with open(os.path.join(REPO, "src", "longrun", "server.py"), encoding="utf-8") as f:
    sv = f.read()
with open(os.path.join(REPO, "src", "longrun", "httpapi.py"), encoding="utf-8") as f:
    sv += f.read()
check("_fs_raw uses an allow-list (_SAFE_PREVIEW)", "_SAFE_PREVIEW" in av)
check("_fs_raw no longer blanket-allows image/*",
      'ctype.startswith("image/")' not in av)
check("responses carry X-Content-Type-Options: nosniff",
      '"X-Content-Type-Options", "nosniff"' in sv)

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
