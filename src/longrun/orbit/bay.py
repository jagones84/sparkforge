"""Model Bay — the complete provider/model catalogue shown by the Orbit console.

The stock deck fed its Model Bay from `/api/status.models`, which is only the DGX
router roster (`router_models()`), so every remote provider (OpenRouter, DeepSeek,
OpenAI, Anthropic, Google) and the other local ones were invisible. This class
instead reads the real catalogue (`providers.catalog`) that already powers
`/api/models`.
"""
import time

TTL = 20.0
_CACHE = {"at": 0.0, "data": None}


def _providers():
    from longrun import providers
    return providers


def _loaded_aliases():
    """Model refs the local router reports as warm (best effort)."""
    try:
        from longrun import server
        return {m.get("alias") for m in server.router_models() if m.get("loaded")}
    except Exception:  # noqa: BLE001 - a cold router must never break the catalogue
        return set()


class ModelBay:
    """Read-only, short-cached view over every configured provider and its models."""

    def __init__(self, ttl=TTL):
        self.ttl = ttl

    def snapshot(self, force=False):
        now = time.time()
        if not force and _CACHE["data"] and (now - _CACHE["at"]) < self.ttl:
            return _CACHE["data"]
        try:
            cat = _providers().catalog(loaded_aliases=_loaded_aliases())
        except Exception:  # noqa: BLE001 - a missing/bad catalogue must not 500 the deck
            cat = {"providers": [], "default": None, "count": 0}
        data = {
            "ts": round(now, 3),
            "default": cat.get("default"),
            "count": cat.get("count", 0),
            "providers": [self._provider(p) for p in cat.get("providers", [])],
        }
        _CACHE["at"] = now
        _CACHE["data"] = data
        return data

    @staticmethod
    def _provider(p):
        models = [{
            "id": m.get("id"),
            "ref": m.get("ref"),
            "context_length": m.get("context_length") or 0,
            "loaded": m.get("loaded"),
        } for m in p.get("models", [])]
        return {
            "id": p.get("id"),
            "name": p.get("name") or p.get("id"),
            "kind": p.get("kind"),
            "local": bool(p.get("local")),
            "available": bool(p.get("available")),
            "base_url": p.get("base_url"),
            "key_env": p.get("key_env"),
            "models": models,
        }
