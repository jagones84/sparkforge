"""Optional "Orbit" command-deck hooks (JAG-285).

The deck lives INSIDE the package (``sparkforge/orbit/``). It is still optional:
imported lazily and defensively, so if it is missing or fails to import, these
hooks become no-ops and the app is untouched. The deck may only ADD routes; it can
never shadow an existing one.

Extracted from ``server.py`` (JAG-370) — this module keeps the app's coupling to
the deck explicit and one file wide.
"""
_orbit_cache = {"mod": None, "tried": False}


def _orbit_module():
    """Return the optional `orbit` deck module, or None. Never raises."""
    if not _orbit_cache["tried"]:
        _orbit_cache["tried"] = True
        try:
            from . import orbit  # type: ignore
            _orbit_cache["mod"] = orbit
        except Exception:  # noqa: BLE001 - the deck must never break the app
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
