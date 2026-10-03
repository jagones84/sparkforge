#!/usr/bin/env python3
"""Gate di promozione held-out sigillato (RDD punto 2).

Il verifier del self-improvement deve stare FUORI dallo spazio di lavoro dell'agente:
una suite giudice esterna, ancorata a un manifest di hash, che `selfevolve.promote`
deve superare (fail-closed) prima di archiviare una proposta. Cosi' l'agente non puo'
ne' leggere ne' manomettere il giudice. Modulo puro (nessuna dipendenza dal server).
"""
import hashlib
import json
import os
import shlex
import time

DEFAULT_DIR = "~/.sparkforge/heldout"


def dir():
    """Directory dello store held-out (env SPARKFORGE_HELDOUT_DIR -> default)."""
    return os.path.abspath(os.path.expanduser(
        os.environ.get("SPARKFORGE_HELDOUT_DIR") or DEFAULT_DIR))


def require_enabled():
    """Il gate e' obbligatorio di default; SPARKFORGE_REQUIRE_HELDOUT=0 lo spegne."""
    return os.environ.get("SPARKFORGE_REQUIRE_HELDOUT", "1").strip() not in ("0", "false", "no")


def manifest_path():
    return os.path.join(dir(), "manifest.json")


def load_manifest():
    """Legge il manifest o None se assente/illeggibile/malformato."""
    try:
        with open(manifest_path(), "r", encoding="utf-8") as f:
            m = json.load(f)
        if not isinstance(m, dict) or not isinstance(m.get("files"), dict):
            return None
        return m
    except (OSError, ValueError):
        return None


def _sha256(path):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def integrity(c=None):
    """Verifica che ogni file del manifest esista con l'hash atteso (fail-closed)."""
    m = load_manifest()
    if m is None:
        return {"ok": False, "reason": "no_manifest", "files": []}
    root = dir()
    files = []
    ok = True
    for rel, exp in sorted(m.get("files", {}).items()):
        actual = _sha256(os.path.join(root, rel))
        status = "ok" if (actual is not None and actual == exp) \
            else ("missing" if actual is None else "mismatch")
        if status != "ok":
            ok = False
        files.append({"path": rel, "expected": exp, "actual": actual, "status": status})
    return {"ok": ok, "reason": "ok" if ok else "integrity", "files": files}


def run(candidate=None, c=None, timeout=None, runner=None):
    """Esegue la suite giudice. Ritorna (green, output, duration_ms).

    `runner(suite_dir, command) -> (green, output)` e' iniettabile nei test (puro);
    in produzione esegue nella sandbox. Se il comando del manifest contiene il
    placeholder `{candidate}`, viene sostituito con il path della proposta.
    """
    m = load_manifest()
    if m is None:
        return False, "no manifest", 0
    command = m.get("command") or "python3 check_all.py"
    if candidate and "{candidate}" in command:
        command = command.replace("{candidate}", shlex.quote(str(candidate)))
    suite = os.path.join(dir(), "suite")
    t0 = time.time()
    if runner is not None:
        try:
            green, out = runner(suite, command)
        except Exception as e:  # noqa: BLE001
            green, out = False, "runner error: %s" % e
    else:
        try:
            from . import sandbox
            res = sandbox.run(command, timeout=int(timeout or 120), workspace=suite)
            out = (res.get("stdout") or "") + (res.get("stderr") or "")
            green = res.get("exit_code") == 0
        except Exception as e:  # noqa: BLE001
            green, out = False, "sandbox error: %s" % e
    return bool(green), str(out)[-1200:], int((time.time() - t0) * 1000)


def gate(candidate=None, c=None, runner=None):
    """Verifica sigillata: integrity AND run. Fail-closed su ogni dubbio."""
    rep = integrity(c)
    if not rep.get("ok"):
        return {"green": False, "integrity": rep, "run": None,
                "reason": rep.get("reason", "integrity")}
    green, out, ms = run(candidate=candidate, c=c,
                         timeout=(c or {}).get("heldout_timeout"), runner=runner)
    return {"green": bool(green), "integrity": rep,
            "run": {"green": bool(green), "duration_ms": ms, "output": out},
            "reason": "ok" if green else "run_failed"}


def pin(paths=None):
    """Admin: (ri)scrive il manifest con gli hash attuali. NON e' un'azione agente."""
    root = dir()
    files = {}
    if paths:
        for rel in paths:
            files[rel] = _sha256(os.path.join(root, rel))
    else:
        suite = os.path.join(root, "suite")
        for base, _dirs, names in os.walk(suite):
            for n in names:
                p = os.path.join(base, n)
                files[os.path.relpath(p, root)] = _sha256(p)
    m = {"version": 1, "command": "python3 check_all.py", "files": files}
    os.makedirs(root, exist_ok=True)
    with open(manifest_path(), "w", encoding="utf-8") as f:
        json.dump(m, f, indent=2, sort_keys=True)
    return m
