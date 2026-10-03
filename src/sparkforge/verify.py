#!/usr/bin/env python3
"""Verifier "apply-only-if-green" (JAG-131).

Dopo ogni scrittura/modifica di file (fs.write / fs.edit), quando il verifier e'
attivo, l'harness esegue un comando di verifica (es. i test del progetto) nella
sandbox: se il comando NON passa, la modifica viene ANNULLATA (rollback al
pre-image) e il modello riceve l'errore come osservazione.

E' il pattern "edit -> test -> rollback": la correttezza viene dimostrata
sull'ambiente prima di accettare l'azione, indipendentemente dal modello
(verifier / test-time verification). Modulo PURO e disattivato di default: si
accende da `config/tools.yaml`:

    verifier:
      enabled: true
      command: "python3 -m pytest -q"
      timeout_secs: 120
      paths: ["sparkforge/src"]      # opzionale: solo path che contengono questi
"""
import os
import time

DEFAULTS = {
    "enabled": False,
    "command": "",
    "timeout_secs": 120,
    "paths": [],
}

TARGET_TOOLS = ("fs.write", "fs.edit")


def cfg(override=None):
    """Config effettiva: DEFAULTS <- config/tools.yaml (verifier) -> override."""
    out = dict(DEFAULTS)
    try:
        from . import registry
        got = registry.load_config().get("verifier") or {}
        if isinstance(got, dict):
            out.update({k: v for k, v in got.items() if v is not None})
    except Exception:  # noqa: BLE001
        pass
    if isinstance(override, dict):
        out.update(override)
    return out


def is_active(c=None):
    """True solo se abilitato E con un comando configurato."""
    c = c or cfg()
    return bool(c.get("enabled")) and bool(str(c.get("command") or "").strip())


def in_scope(path, c=None):
    """True se il path rientra nello scope (paths vuoto = tutto)."""
    c = c or cfg()
    pats = [p for p in (c.get("paths") or []) if p]
    if not pats:
        return True
    p = str(path or "")
    return any(str(x) in p for x in pats)


def should_verify(tool, path, c=None):
    """True se questa (tool, path) va verificata."""
    c = c or cfg()
    return tool in TARGET_TOOLS and is_active(c) and in_scope(path, c)


def snapshot(path):
    """Pre-image del file: {"exists": bool, "content": str} (None se illeggibile)."""
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return {"exists": True, "content": f.read()}
        return {"exists": False, "content": ""}
    except OSError:
        return None


def restore(path, snap):
    """Ripristina il pre-image (o elimina il file se prima non esisteva)."""
    if not snap:
        return False
    try:
        if snap.get("exists"):
            with open(path, "w", encoding="utf-8") as f:
                f.write(snap.get("content") or "")
        elif os.path.exists(path):
            os.remove(path)
        return True
    except OSError:
        return False


def run_check(workspace=None, c=None, run_id=None):
    """Esegue il comando di verifica nella sandbox. Ritorna (green, output)."""
    c = c or cfg()
    cmd = str(c.get("command") or "").strip()
    if not cmd:
        return True, ""
    try:
        from . import sandbox
        res = sandbox.run(cmd, run_id=run_id, timeout=c.get("timeout_secs"),
                          workspace=workspace)
    except Exception as e:  # noqa: BLE001
        return False, "verifier error: %s" % e
    green = res.get("exit_code") == 0
    out = (res.get("stdout") or "") + (res.get("stderr") or "")
    return green, out


def verify(tool, path, snap, res, workspace=None, run_id=None, c=None):
    """Applica "apply-only-if-green" a un risultato di scrittura.

    Ritorna (res, report): se il check e' verde `res` e' invariato; se rosso la
    modifica viene annullata e `res` diventa un fallimento con l'errore del check.
    """
    c = c or cfg()
    if not should_verify(tool, path, c):
        return res, {"ran": False}
    t0 = time.time()
    green, out = run_check(workspace=workspace, c=c, run_id=run_id)
    report = {"ran": True, "green": bool(green), "command": c.get("command"),
              "duration_ms": int((time.time() - t0) * 1000)}
    if green:
        return res, report
    rolled = restore(path, snap)
    report["rolled_back"] = rolled
    failed = dict(res)
    failed["ok"] = False
    failed["exit_code"] = 1
    failed["verifier_failed"] = True
    failed["error"] = ("verifier: il comando di verifica NON passa; la modifica a %s "
                       "e' stata annullata%s.\n%s"
                       % (path, "" if rolled else " (ROLLBACK FALLITO)",
                          str(out)[-1200:]))
    report["output"] = str(out)[-1200:]
    return failed, report
