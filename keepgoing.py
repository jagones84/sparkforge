#!/usr/bin/env python3
"""Loop di completamento (JAG-129A): la logica che decide se l'harness deve
CONTINUARE a lavorare su una TASK LIST con passi aperti o fermarsi.

Pattern: Ralph/Stop-hook + Claude `/goal`. L'agente non decide quando fermarsi:
lo decide la lista, con stop conditions tipizzate
(goal_reached | no_progress | budget | blocked | user_stop).

Modulo PURO: nessuna dipendenza da server/taskgraph -> testabile in isolamento.
"""
import hashlib
import json
import time

DEFAULTS = {
    "keepgoing_max": 8,       # giri di continuazione prima dello stop 'budget'
    "no_progress_rounds": 2,  # giri senza progresso prima dello stop 'no_progress'
    "max_wall_secs": 3600,    # tetto di tempo per run
    "subagent_max_depth": 2,  # profondita' massima della matrioska
    # JAG-171: quando True l'harness insiste da solo (fino a keepgoing_max) prima
    # di fermarsi; quando False, al primo tentativo di stop con passi aperti passa
    # subito il controllo all'umano (HUMAN IN THE LOOP).
    "autocontinue": True,
}


def cfg(override=None):
    """Runtime config: DEFAULTS <- config/tools.yaml -> override esplicito."""
    out = dict(DEFAULTS)
    try:
        import registry
        got = (registry.load_config().get("runtime") or {})
        if isinstance(got, dict):
            out.update({k: v for k, v in got.items() if v is not None})
    except Exception:  # noqa: BLE001
        pass
    if isinstance(override, dict):
        out.update(override)
    return out


def state_hash(nodes):
    """Hash stabile dello stato (id,status) dei nodi: rileva il 'no progress'."""
    items = sorted("%s:%s" % (n.get("id"), n.get("status")) for n in (nodes or []))
    return hashlib.sha1(("|".join(items)).encode("utf-8")).hexdigest()


def tool_hash(tool, args):
    """Hash di una chiamata tool+args: rileva la ripetizione identica."""
    try:
        blob = json.dumps({"t": tool, "a": args}, sort_keys=True, default=str)
    except Exception:  # noqa: BLE001
        blob = "%s:%s" % (tool, args)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def decide(open_nodes, rounds, stale, started, now=None, aborted=False, blocked=False,
           steer=False, override=None):
    """Decide se continuare. Ritorna {"continue": bool, "reason": str|None}.

    Ordine di priorita' (la prima che scatta vince): user_stop, goal_reached,
    blocked, budget (tempo), budget (giri), no_progress. `steer` forza la
    continuazione (reindirizzamento utente) anche con la lista vuota.
    """
    c = cfg(override)
    now = time.time() if now is None else float(now)
    if aborted:
        return {"continue": False, "reason": "user_stop"}
    if open_nodes <= 0:
        if steer:
            return {"continue": True, "reason": None}
        return {"continue": False, "reason": "goal_reached"}
    if blocked:
        return {"continue": False, "reason": "blocked"}
    if now - float(started) >= float(c["max_wall_secs"]):
        return {"continue": False, "reason": "budget"}
    if int(rounds) >= int(c["keepgoing_max"]):
        return {"continue": False, "reason": "budget"}
    if int(stale) >= int(c["no_progress_rounds"]):
        return {"continue": False, "reason": "no_progress"}
    return {"continue": True, "reason": None}