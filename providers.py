#!/usr/bin/env python3
"""SparkForge providers — one catalogue of every LLM the harness can reach (JAG-71).

`config/providers.yaml` declares providers (llama.cpp DGX, llama.cpp Windows,
vLLM, OpenRouter, DeepSeek) and the models each exposes. This module:

  * loads API keys from gitignored .env files (never from the repo),
  * resolves a model reference `<provider>:<model>` (or a bare id, local first)
    to the endpoint + auth headers the request must use,
  * exposes a UI-friendly catalogue (which provider/model is usable right now).

No secret is ever written to the repository: a provider only names its
`api_key_env`, and the value is read from the environment / .env file.
"""

import json
import os
import re
import threading
import time

REPO = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.environ.get("SPARKFORGE_PROVIDERS") or os.path.join(REPO, "config", "providers.yaml")

DEFAULTS = {"version": "1", "env_files": [".env", "~/.hermes/.env"],
            "providers": [], "default": None}

_cache = {"ts": None, "cfg": None}
_env_loaded = False


# ------------------------------------------------------------------- env -----

def load_env(reload=False):
    """Populate os.environ from the configured .env files (never overwrite).

    Keys live in a gitignored .env (or ~/.hermes/.env); the repository only ever
    references them by name. Missing files are silently skipped.
    """
    global _env_loaded
    if _env_loaded and not reload:
        return
    cfg = load(reload=True)
    for rel in (cfg.get("env_files") or []):
        path = os.path.expanduser(rel)
        if not os.path.isabs(path):
            path = os.path.join(REPO, path)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip("'\"")
                    if k and k not in os.environ:
                        os.environ[k] = v
        except OSError:
            continue
    _env_loaded = True


# ----------------------------------------------------------------- config -----

def load(reload=False):
    """Cached providers config (dict). Falls back to built-in defaults."""
    try:
        mt = os.stat(CONFIG).st_mtime
    except OSError:
        return dict(DEFAULTS)
    if not reload and _cache["ts"] == mt and _cache["cfg"] is not None:
        return _cache["cfg"]
    cfg = None
    try:
        import yaml
        with open(CONFIG, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if isinstance(data, dict):
            cfg = data
    except Exception:  # noqa: BLE001 — a bad file must not break the harness
        cfg = None
    if cfg is None:
        cfg = json.loads(os.environ.get("SPARKFORGE_PROVIDERS_JSON", "{}")) or dict(DEFAULTS)
    # normalise
    cfg.setdefault("providers", [])
    for p in cfg["providers"]:
        p.setdefault("kind", "openai")
        p.setdefault("local", False)
        p.setdefault("models", [])
        p["models"] = [m if isinstance(m, dict) else {"id": str(m)} for m in p["models"]]
    _cache.update(ts=mt, cfg=cfg)
    return cfg


def providers():
    return load().get("providers", [])


def get(provider_id):
    for p in providers():
        if p.get("id") == provider_id:
            return p
    return None


def default_ref():
    """The configured default model reference (or the first available model)."""
    load_env()
    d = load().get("default")
    if d:
        return d
    for p in providers():
        if p["models"] and api_key(p):
            return "%s:%s" % (p["id"], p["models"][0]["id"])
    return None


# -------------------------------------------------------------------- auth ----

def api_key(provider):
    """The key for a provider (from env / .env); None for a local server."""
    env = (provider or {}).get("api_key_env")
    if not env:
        return None
    load_env()
    return os.environ.get(env) or None


def available(provider):
    """True when the provider can be called: local, or its key is present."""
    if provider.get("local"):
        return True
    env = provider.get("api_key_env")
    if not env:
        return True
    return bool(api_key(provider))


def headers(provider):
    h = {"Content-Type": "application/json"}
    key = api_key(provider)
    if key:
        h["Authorization"] = "Bearer " + key
    return h


# ---------------------------------------------------------------- resolving ---

def resolve(ref):
    """Resolve `ref` to (provider, model_id). None when nothing matches.

    Grammar: `<provider_id>:<model_id>` when the prefix names a provider (so
    OpenRouter ids that contain ':' — e.g. `deepseek/deepseek-v4.1-flash:batch`
    — are not mis-split); otherwise a bare model id, searched across every
    provider with the local ones first.
    """
    if not ref:
        ref = default_ref()
    if not ref:
        return None
    if ":" in ref:
        pid, mid = ref.split(":", 1)
        p = get(pid)
        if p is not None:
            return p, mid
    ordered = sorted(providers(), key=lambda p: (not p.get("local"), p.get("id") or ""))
    for p in ordered:
        for m in p["models"]:
            if m.get("id") == ref:
                return p, ref
    return None


def endpoint(ref):
    """(url, headers, model_id) for a chat completion on `ref`."""
    hit = resolve(ref)
    if not hit:
        return None
    p, mid = hit
    base = (p.get("base_url") or "").rstrip("/")
    return base + "/chat/completions", headers(p), mid


def is_local(ref):
    hit = resolve(ref)
    return bool(hit and hit[0].get("local"))


def ref_of(provider, model_id):
    return "%s:%s" % (provider.get("id"), model_id)


# ------------------------------------------------- remote model metadata ------

_OPENROUTER_CTX = {"ts": None, "map": None, "lock": threading.Lock()}
_CTX_TTL = 6 * 3600


def _fetch_openrouter_contexts():
    """One bounded fetch of OpenRouter's live model list → {id: context_length}."""
    m = {}
    try:
        import urllib.request
        req = urllib.request.Request("https://openrouter.ai/api/v1/models",
                                     headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode())
        for d in data.get("data", []):
            cid, cl = d.get("id"), d.get("context_length")
            if cid and cl:
                m[cid] = int(cl)
    except Exception:  # noqa: BLE001 — metadata is best-effort, never fatal
        m = _OPENROUTER_CTX["map"] or {}
    _OPENROUTER_CTX.update(ts=time.time(), map=m)
    return m


def openrouter_contexts(block=True):
    """{model_id: context_length} from OpenRouter, cached for 6h.

    Used to report the REAL max context of a remote model (a guess would make the
    "x / max" indicator wrong, which is exactly the bug this fixes).
    """
    m = _OPENROUTER_CTX["map"]
    fresh = m is not None and _OPENROUTER_CTX["ts"] and time.time() - _OPENROUTER_CTX["ts"] < _CTX_TTL
    if fresh:
        return m
    if m is None and block:
        with _OPENROUTER_CTX["lock"]:
            if _OPENROUTER_CTX["map"] is None:
                return _fetch_openrouter_contexts()
    return _OPENROUTER_CTX["map"] or {}


def warm():
    """Warm remote metadata in the background so no request ever waits on it."""
    def _run():
        try:
            with _OPENROUTER_CTX["lock"]:
                if _OPENROUTER_CTX["map"] is None:
                    _fetch_openrouter_contexts()
        except Exception:  # noqa: BLE001
            pass
    threading.Thread(target=_run, daemon=True).start()


def context_length(ref):
    """Declared context window for `ref` (0 when unknown).

    Local models declare it in providers.yaml; OpenRouter models fall back to the
    live vendor metadata (never a hardcoded guess).
    """
    hit = resolve(ref)
    if not hit:
        return 0
    p, mid = hit
    for m in p["models"]:
        if m.get("id") == mid:
            declared = int(m.get("context_length") or 0)
            if declared:
                return declared
            break
    if p.get("kind") == "openrouter":
        return int(openrouter_contexts().get(mid) or 0)
    return 0


def catalog(loaded_aliases=None):
    """UI-friendly catalogue: providers, their models and what is usable now.

    `loaded_aliases` (optional) is the set of model ids the local router reports
    as loaded, so a mobile picker can show which local model is warm.
    """
    loaded = set(loaded_aliases or [])
    out = []
    for p in providers():
        avail = available(p)
        models = []
        for m in p["models"]:
            cl = int(m.get("context_length") or 0)
            if not cl and p.get("kind") == "openrouter":
                cl = int(openrouter_contexts().get(m.get("id")) or 0)
            models.append({
                "id": m.get("id"),
                "ref": ref_of(p, m.get("id")),
                "context_length": cl,
                "loaded": m.get("id") in loaded if p.get("local") else None,
            })
        out.append({
            "id": p.get("id"), "name": p.get("name") or p.get("id"),
            "kind": p.get("kind"), "base_url": p.get("base_url"),
            "local": bool(p.get("local")),
            "available": avail,
            "key_env": p.get("api_key_env"),
            "models": models,
        })
    return {"providers": out, "default": default_ref(),
            "count": sum(len(p["models"]) for p in out)}
