#!/usr/bin/env python3
"""JAG-355: live cost ledger for model calls.

The harness already captures the provider's REAL `usage` on every LLM call
(prompt / completion / cached tokens). This module prices each call and keeps a
per-session ledger, so the UI can show the session total AND the cost of every
single API call while you work.

Prices (USD per 1M tokens, `[input, output]`) are resolved, in order, from:
  1. the `SPARKFORGE_PRICES` env var (JSON: ``{"model": [in, out]}``),
  2. ``config/prices.yaml`` (or ``config/prices.json``),
  3. ``data/prices.json`` — the cache written by :func:`refresh_openrouter`, which
     pulls OpenRouter's PUBLIC models endpoint (no API key required).

A model with no known price is reported with ``usd: null`` (UNKNOWN) — never a
fake zero. A local model priced explicitly ``0`` is genuinely free.

Ledger: ``data/costs/<session>.json`` (override dir with SPARKFORGE_COSTS_DIR).
Stdlib only.
"""
import json
import os
import threading
import time

from .paths import REPO_ROOT as REPO, DATA_DIR

COSTS_DIR = os.environ.get("SPARKFORGE_COSTS_DIR", os.path.join(DATA_DIR, "costs"))
_PRICES_YAML = os.path.join(REPO, "config", "prices.yaml")
_PRICES_JSON = os.path.join(REPO, "config", "prices.json")
_CACHE_JSON = os.environ.get("SPARKFORGE_PRICES_FILE", os.path.join(DATA_DIR, "prices.json"))
OPENROUTER_MODELS = "https://openrouter.ai/api/v1/models"
MAX_CALLS = 2000

_lock = threading.RLock()
_prices = None


def _read_doc(path):
    """Read a small YAML/JSON doc into a dict, or None. Never fatal."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    try:
        import yaml
        d = yaml.safe_load(text)
    except Exception:  # noqa: BLE001 — fall back to JSON
        try:
            d = json.loads(text)
        except Exception:  # noqa: BLE001
            return None
    return d if isinstance(d, dict) else None


def _pair(v):
    """Normalise one price entry to (input_per_1m, output_per_1m) floats."""
    try:
        if isinstance(v, (list, tuple)) and len(v) >= 2:
            return (float(v[0]), float(v[1]))
        if isinstance(v, dict):
            i = v.get("in", v.get("input", v.get("prompt")))
            o = v.get("out", v.get("output", v.get("completion")))
            if i is not None and o is not None:
                return (float(i), float(o))
    except (TypeError, ValueError):
        return None
    return None


def _prices_table():
    global _prices
    with _lock:
        if _prices is not None:
            return _prices
        table = {}
        for p in (_CACHE_JSON, _PRICES_JSON, _PRICES_YAML):
            d = _read_doc(p)
            if d:
                table.update(d)
        env = os.environ.get("SPARKFORGE_PRICES")
        if env:
            try:
                e = json.loads(env)
                if isinstance(e, dict):
                    table.update(e)
            except ValueError:
                pass
        _prices = table
        return table


def _lookup(table, model):
    """Match a model ref against the price table, both directions (ci).

    Both the table key and the query are indexed by their full form AND their
    last ``/``- or ``:``-segment, so ``deepseek/deepseek-chat``, ``openrouter:deepseek-chat``
    and a bare ``deepseek-chat`` all resolve to the same price.
    """
    if not model:
        return None
    idx = {}
    for k, v in table.items():
        s = str(k)
        for key in (s, s.split("/")[-1], s.split(":")[-1]):
            idx.setdefault(key.lower(), v)
    m = str(model)
    for key in (m, m.split("/")[-1], m.split(":")[-1]):
        v = idx.get(key.lower())
        if v is not None:
            return _pair(v)
    return None


def price_for(model):
    """(input, output) USD per 1M tokens, or None when the price is unknown."""
    return _lookup(_prices_table(), model)


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _usage_tokens(usage):
    """(prompt, completion, cached) from a provider `usage` dict."""
    u = usage or {}
    pt = _int(u.get("prompt_tokens"))
    ct = _int(u.get("completion_tokens"))
    det = u.get("prompt_tokens_details") or {}
    cached = _int(det.get("cached_tokens"))
    if cached is None:
        cached = _int((u.get("timings") or {}).get("cache_n"))
    return pt, ct, cached


def _path(session):
    safe = "".join(c if c.isalnum() or c in "._-" else "_"
                   for c in str(session or "unknown"))[:96]
    return os.path.join(COSTS_DIR, safe + ".json")


def _load(session):
    try:
        with open(_path(session), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def _save(session, led):
    os.makedirs(COSTS_DIR, exist_ok=True)
    p = _path(session)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(led[-MAX_CALLS:], f, ensure_ascii=False)
    os.replace(tmp, p)


def _summarise(led):
    tot = 0.0
    priced = unknown = 0
    tin = tout = tcached = 0
    by_model = {}
    for c in led:
        tin += c.get("prompt") or 0
        tout += c.get("completion") or 0
        tcached += c.get("cached") or 0
        if c.get("usd") is None:
            unknown += 1
        else:
            priced += 1
            tot += float(c["usd"])
        m = c.get("model") or "?"
        b = by_model.setdefault(m, {"calls": 0, "usd": 0.0, "unknown": 0})
        b["calls"] += 1
        if c.get("usd") is None:
            b["unknown"] += 1
        else:
            b["usd"] = round(b["usd"] + float(c["usd"]), 6)
    return {"calls": len(led), "tokens_in": tin, "tokens_out": tout,
            "cached": tcached, "total_usd": round(tot, 6),
            "priced_calls": priced, "unknown_calls": unknown, "by_model": by_model}


def record(session, model, usage):
    """Price ONE LLM call from its real `usage` and append it to the ledger.

    Returns the call record (with the running session total) or None when the
    usage carried no token counts. An unknown price yields ``usd: null``.
    """
    pt, ct, cached = _usage_tokens(usage)
    if not pt and not ct:
        return None
    pair = price_for(model)
    usd = None
    if pair is not None and pt is not None and ct is not None:
        usd = round(pt / 1e6 * pair[0] + ct / 1e6 * pair[1], 6)
    rec = {"ts": round(time.time(), 3), "model": str(model or ""),
           "prompt": pt or 0, "completion": ct or 0, "cached": cached or 0, "usd": usd}
    with _lock:
        led = _load(session)
        led.append(rec)
        _save(session, led)
        s = _summarise(led)
    rec["total_usd"] = s["total_usd"]
    rec["calls"] = s["calls"]
    return rec


def summary(session, tail=60):
    """Session totals + the most recent calls (newest first)."""
    led = _load(session)
    s = _summarise(led)
    s["session"] = session
    s["recent"] = list(reversed(led[-max(1, int(tail or 60)):]))
    s["priced"] = bool(_prices_table())
    return s


def reset(session):
    """Drop the ledger for one session (the UI 'clear' action)."""
    with _lock:
        try:
            os.remove(_path(session))
        except OSError:
            pass
    return {"ok": True}


def refresh_openrouter(url=None, timeout=12):
    """Fetch OpenRouter's PUBLIC model list and cache USD-per-1M prices.

    No API key needed. Writes ``data/prices.json`` as ``{"model_id": [in, out]}``.
    Returns ``{"ok", "count", "error"}``. Never raises.
    """
    global _prices
    import urllib.request
    if url is None:
        url = os.environ.get("SPARKFORGE_PRICES_URL") or OPENROUTER_MODELS
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "sparkforge/costs"})
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — fixed https URL
            data = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "fetch failed: %s" % e}
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return {"ok": False, "error": "unexpected models payload"}

    def _per_1m(x):
        try:
            return round(float(x) * 1e6, 6)
        except (TypeError, ValueError):
            return None

    table = {}
    for m in rows:
        if not isinstance(m, dict):
            continue
        mid = m.get("id")
        pr = m.get("pricing") or {}
        if not mid:
            continue
        i, o = _per_1m(pr.get("prompt")), _per_1m(pr.get("completion"))
        if i is not None and o is not None:
            table[str(mid)] = [i, o]
    try:
        os.makedirs(os.path.dirname(_CACHE_JSON), exist_ok=True)
        tmp = _CACHE_JSON + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(table, f, ensure_ascii=False, sort_keys=True)
        os.replace(tmp, _CACHE_JSON)
    except OSError as e:
        return {"ok": False, "error": "cache write failed: %s" % e}
    with _lock:
        _prices = None  # force a reload on the next lookup
    return {"ok": True, "count": len(table)}
