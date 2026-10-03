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

from .paths import REPO_ROOT as REPO
CONFIG = os.environ.get("SPARKFORGE_PROVIDERS") or os.path.join(REPO, "config", "providers.yaml")
# JAG-112: user additions/overrides live in a gitignored overlay (never the repo).
LOCAL_CONFIG = os.environ.get("SPARKFORGE_PROVIDERS_LOCAL") or \
    os.path.join(REPO, "config", "providers.local.yaml")

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

_PROVIDER_KINDS = ("llamacpp", "openai", "openrouter", "deepseek", "anthropic", "custom")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_ENVNAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _read_yaml(path):
    """Read a small YAML (or JSON) doc; None when missing/invalid (never fatal)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    try:
        import yaml
        data = yaml.safe_load(text)
    except Exception:  # noqa: BLE001 — fall back to JSON
        try:
            data = json.loads(text)
        except Exception:  # noqa: BLE001
            return None
    return data if isinstance(data, dict) else None


def _merge(base, local):
    """Merge the local overlay over the base config (JAG-112).

    Providers match by `id`: local scalars override, model lists are unioned by
    id, and `disabled: true` on a provider or a model is a tombstone (excluded).
    A local `default` wins.
    """
    out = dict(base or {})
    order, by_id = [], {}
    for p in out.get("providers") or []:
        if isinstance(p, dict) and p.get("id"):
            by_id[p["id"]] = dict(p)
            order.append(p["id"])
    for lp in (local or {}).get("providers") or []:
        if not isinstance(lp, dict) or not lp.get("id"):
            continue
        pid = lp["id"]
        if pid not in by_id:
            by_id[pid] = dict(lp)
            order.append(pid)
            continue
        cur = by_id[pid]
        for k, v in lp.items():
            if k != "models":
                cur[k] = v
        if "models" in lp:
            m_by, m_order = {}, []
            for m in cur.get("models") or []:
                spec = m if isinstance(m, dict) else {"id": str(m)}
                m_by[spec.get("id")] = dict(spec)
                m_order.append(spec.get("id"))
            for lm in lp["models"] or []:
                spec = dict(lm) if isinstance(lm, dict) else {"id": str(lm)}
                mid = spec.get("id")
                if mid in m_by:
                    m_by[mid].update(spec)
                else:
                    m_by[mid] = spec
                    m_order.append(mid)
            cur["models"] = [m_by[i] for i in m_order]
    res = dict(out)
    res["providers"] = [by_id[i] for i in order if not by_id[i].get("disabled")]
    if (local or {}).get("default"):
        res["default"] = local["default"]
    return res


def load(reload=False):
    """Cached providers config: base merged with the local overlay (JAG-112)."""
    try:
        mt = os.stat(CONFIG).st_mtime
    except OSError:
        mt = 0
    try:
        lmt = os.stat(LOCAL_CONFIG).st_mtime
    except OSError:
        lmt = 0
    stamp = (mt, lmt)
    if not reload and _cache["ts"] == stamp and _cache["cfg"] is not None:
        return _cache["cfg"]
    base = _read_yaml(CONFIG)
    local = _read_yaml(LOCAL_CONFIG)
    if base is None and local is None:
        cfg = json.loads(os.environ.get("SPARKFORGE_PROVIDERS_JSON", "{}")) or dict(DEFAULTS)
    else:
        cfg = _merge(base or {}, local or {})
    # normalise
    cfg.setdefault("providers", [])
    for p in cfg["providers"]:
        p.setdefault("kind", "openai")
        p.setdefault("local", False)
        p.setdefault("models", [])
        p["models"] = [m if isinstance(m, dict) else {"id": str(m)}
                       for m in p["models"]
                       if not (isinstance(m, dict) and m.get("disabled"))]
    _cache.update(ts=stamp, cfg=cfg)
    return cfg


# ------------------------------------------------------------ user edits -----

def _local_doc():
    return _read_yaml(LOCAL_CONFIG) or {"providers": []}


def _write_local(doc):
    """Atomic write of the overlay (never the versioned base file)."""
    os.makedirs(os.path.dirname(LOCAL_CONFIG), exist_ok=True)
    tmp = LOCAL_CONFIG + ".tmp"
    try:
        import yaml
        text = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)
    except Exception:  # noqa: BLE001
        text = json.dumps(doc, indent=2, ensure_ascii=False)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, LOCAL_CONFIG)
    return LOCAL_CONFIG


def _local_provider(doc, pid):
    for p in doc.setdefault("providers", []):
        if isinstance(p, dict) and p.get("id") == pid:
            return p
    return None


def _validate_provider(spec):
    if not _ID_RE.match((spec.get("id") or "").strip()):
        return "id non valido (usa [a-z0-9._-])"
    kind = spec.get("kind") or "openai"
    if kind not in _PROVIDER_KINDS:
        return "kind non valido: %s" % kind
    url = spec.get("base_url")
    if url and not str(url).startswith(("http://", "https://")):
        return "base_url deve iniziare con http(s)://"
    env = spec.get("api_key_env")
    if env and not _ENVNAME_RE.match(env):
        return "api_key_env deve essere il NOME della variabile (es. OPENROUTER_API_KEY)"
    return None


def upsert_provider(spec):
    """Add or update a provider (only `id` is required). Writes the overlay."""
    spec = dict(spec or {})
    if not spec.get("models"):
        spec.pop("models", None)
    err = _validate_provider(spec)
    if err:
        return {"ok": False, "error": err}
    pid = spec["id"].strip()
    spec["id"] = pid
    doc = _local_doc()
    cur = _local_provider(doc, pid)
    if cur is None:
        cur = {"id": pid}
        doc["providers"].append(cur)
    cur.pop("disabled", None)
    for k, v in spec.items():
        if k == "id":
            continue
        cur[k] = [dict(m) for m in v] if k == "models" else v
    _write_local(doc)
    _cache.update(ts=None, cfg=None)
    return {"ok": True, "id": pid, "config": LOCAL_CONFIG}


def remove_provider(pid):
    """Remove a local-only provider, or disable (tombstone) a base one."""
    doc = _local_doc()
    cur = _local_provider(doc, pid)
    in_base = any(isinstance(p, dict) and p.get("id") == pid
                  for p in ((_read_yaml(CONFIG) or {}).get("providers") or []))
    if in_base:
        if cur is None:
            cur = {"id": pid}
            doc["providers"].append(cur)
        cur["disabled"] = True
    elif cur is not None:
        doc["providers"] = [p for p in doc["providers"] if p is not cur]
    _write_local(doc)
    _cache.update(ts=None, cfg=None)
    return {"ok": True, "id": pid, "disabled": in_base}


def add_model(pid, model_id, context_length=None):
    mid = (model_id or "").strip()
    if not mid:
        return {"ok": False, "error": "model id richiesto"}
    doc = _local_doc()
    cur = _local_provider(doc, pid)
    if cur is None:
        cur = {"id": pid, "models": []}
        doc["providers"].append(cur)
    cur.setdefault("models", [])
    cur["models"] = [m for m in cur["models"]
                     if (m.get("id") if isinstance(m, dict) else m) != mid]
    entry = {"id": mid}
    if context_length:
        entry["context_length"] = int(context_length)
    cur["models"].append(entry)
    _write_local(doc)
    _cache.update(ts=None, cfg=None)
    return {"ok": True, "id": pid, "model": mid}


def remove_model(pid, model_id):
    mid = (model_id or "").strip()
    doc = _local_doc()
    cur = _local_provider(doc, pid)
    base_p = next((p for p in ((_read_yaml(CONFIG) or {}).get("providers") or [])
                   if isinstance(p, dict) and p.get("id") == pid), None)
    in_base = bool(base_p and any((m.get("id") if isinstance(m, dict) else m) == mid
                                  for m in (base_p.get("models") or [])))
    if cur is None:
        cur = {"id": pid, "models": []}
        doc["providers"].append(cur)
    cur.setdefault("models", [])
    cur["models"] = [m for m in cur["models"]
                     if (m.get("id") if isinstance(m, dict) else m) != mid]
    if in_base:
        cur["models"].append({"id": mid, "disabled": True})
    _write_local(doc)
    _cache.update(ts=None, cfg=None)
    return {"ok": True, "id": pid, "model": mid}


def set_default(ref):
    ref = (ref or "").strip()
    if not ref:
        return {"ok": False, "error": "ref richiesto"}
    doc = _local_doc()
    doc["default"] = ref
    _write_local(doc)
    _cache.update(ts=None, cfg=None)
    return {"ok": True, "default": ref}


def reload():
    """Drop caches and re-read providers config + .env (hot reload)."""
    load_env(reload=True)
    _cache.update(ts=None, cfg=None)
    return load(reload=True)


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
