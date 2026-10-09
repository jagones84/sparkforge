"""Optional "Bridge" (formerly Orbit) beta console hooks (JAG-285).

The beta lives OUTSIDE the application, in ``src2/``. It is ENTIRELY detachable:
if ``src2/`` is deleted or fails to import, these hooks become no-ops and the app
is untouched. The beta may only ADD routes; it can never shadow an existing one.

Extracted from ``server.py`` (JAG-370) — the hooks were already isolated; this
module makes the app's only coupling to the beta explicit and one file wide.
"""
import os

from .paths import REPO_ROOT as REPO

_SRC2_DIR = os.path.join(REPO, "src2")
_orbit_cache = {"mod": None, "tried": False}


def _orbit_module():
    """Return the optional `orbit_beta` module, or None. Never raises."""
    if not _orbit_cache["tried"]:
        _orbit_cache["tried"] = True
        try:
            import sys as _sys
            if os.path.isdir(_SRC2_DIR) and _SRC2_DIR not in _sys.path:
                _sys.path.insert(0, _SRC2_DIR)
            import orbit_beta  # type: ignore
            _orbit_cache["mod"] = orbit_beta
        except Exception:  # noqa: BLE001 - the beta must never break the app
            _orbit_cache["mod"] = None
    return _orbit_cache["mod"]


def _orbit_page(handler, path):
    """Serve the beta shell (public), if present. Return True if it answered."""
    mod = _orbit_module()
    try:
        return bool(mod and mod.serve_page(handler, path))
    except Exception:  # noqa: BLE001
        return False


def _orbit_handle(handler, method, path, qs, body):
    """Let the beta answer an API route, if present. Return True if it did."""
    mod = _orbit_module()
    try:
        return bool(mod and mod.handle(handler, method, path, qs, body))
    except Exception:  # noqa: BLE001
        return False
