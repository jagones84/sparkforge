#!/usr/bin/env python3
"""Metriche per run (JAG-129E): quanto ha lavorato un run.

Scrive data/runs/<key>.json con: started, ended, duration_s, iterations, steps,
tokens, model, outcome, stop_reason. `human()` produce la riga in chiaro.
"""
import json
import os
import time

from .paths import REPO_ROOT as REPO
RUNS_DIR = os.environ.get("SPARKFORGE_RUNS_DIR", os.path.join(REPO, "data", "runs"))
_START = {}


def _path(key):
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in str(key))[:96]
    return os.path.join(RUNS_DIR, safe + ".json")


def start(key, model=None):
    rec = {"key": key, "model": model, "started": round(time.time(), 3),
           "ended": None, "duration_s": None, "iterations": 0, "steps": 0,
           "tokens": 0, "outcome": "running", "stop_reason": None,
           "difficulty": None}
    _START[key] = rec["started"]
    _write(key, rec)
    return rec


def finish(key, outcome="done", stop_reason=None, iterations=0, steps=0, tokens=0,
           prompt_tokens=0, completion_tokens=0, model=None, difficulty=None):
    rec = get(key)
    if not rec:
        rec = start(key)
    now = round(time.time(), 3)
    rec.update({"ended": now, "iterations": int(iterations), "steps": int(steps),
                "tokens": int(tokens),
                "prompt_tokens": int(prompt_tokens),
                "completion_tokens": int(completion_tokens),
                "outcome": outcome, "stop_reason": stop_reason})
    if model:
        rec["model"] = model
    if difficulty is not None:
        rec["difficulty"] = difficulty
    started = _START.get(key) or rec.get("started") or now
    rec["duration_s"] = round(now - float(started), 1)
    _write(key, rec)
    return rec


def _write(key, rec):
    os.makedirs(RUNS_DIR, exist_ok=True)
    tmp = _path(key) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _path(key))


def get(key):
    try:
        with open(_path(key), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def human(key):
    r = get(key) or {}
    return ("run %s · %s · %s giri · %s step · %s tok · %ss"
            % (key, r.get("stop_reason") or r.get("outcome"),
               r.get("iterations"), r.get("steps"), r.get("tokens"),
               r.get("duration_s")))