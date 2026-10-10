#!/usr/bin/env python3
"""Import every module under src/longrun to surface import-time crashes.

A module that fails to import at first touch is a latent runtime bug (missing
import used only inside a branch, syntax error from a bad patch, ...). This is a
cheap, broad smoke test: it does not start the server or touch live data.
"""
import importlib
import os
import pkgutil
import sys
import traceback

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))

import longrun  # noqa: E402

pkg_dir = os.path.dirname(longrun.__file__)
ok, bad = 0, []
for mod in sorted(m.name for m in pkgutil.iter_modules([pkg_dir])):
    name = "longrun." + mod
    try:
        importlib.import_module(name)
        ok += 1
    except Exception:
        bad.append((name, traceback.format_exc().strip().splitlines()[-1]))

print("imported_ok=%d failed=%d" % (ok, len(bad)))
for name, err in bad:
    print("IMPORT_FAIL %s :: %s" % (name, err))
sys.exit(1 if bad else 0)
