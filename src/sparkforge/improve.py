#!/usr/bin/env python3
"""Routing del self-improvement (JAG-128B).

Regola d'oro (pattern di frontiera): l'agente scrive LIBERO solo la memoria;
le REGOLE (progetto/globali) le scrive l'umano -> l'agente al massimo PROPONE;
il CODICE dell'harness e' fuori scope.
"""
import time
import os
import json

from .paths import REPO_ROOT as REPO
PROPOSAL_DIR = os.path.join(REPO, "data", "proposals")

# scope -> modalita' di scrittura consentita all'agente
AGENT_WRITE = {
    "memory": "auto",       # data/memory/**  -> scrittura libera (silent)
    "skill": "propose",     # skills/**       -> proposta, soglia
    "project": "propose",   # <ws>/.sparkforge/RULES.md -> SOLO proposta
    "global": "propose",    # ~/.config/sparkforge/RULES.md -> SOLO proposta
    "code": "forbidden",    # sparkforge/*.py -> fuori scope
}

_TOOLCALL_THRESHOLD = 5


def should_nudge(used_tools=0, errored=False, corrected=False):
    """True quando scatta il nudge di self-improvement (pattern Hermes)."""
    if corrected or errored:
        return True
    try:
        return int(used_tools) >= _TOOLCALL_THRESHOLD
    except (TypeError, ValueError):
        return False


def _path(pid):
    return os.path.join(PROPOSAL_DIR, pid + ".json")


def propose(scope, content, reason="", target_path="", ws=None):
    """Registra una PROPOSTA (non scrive nulla di definitivo).

    `ws` e' il workspace in cui la regola andra' scritta in caso di approve:
    viene catturato ORA (il workspace puo' cambiare prima della decisione),
    cosi' `decide` scrive nel progetto giusto e non in quello "corrente".
    """
    if ws is None:
        try:
            from . import rules
            ws = rules.get_workspace()
        except Exception:  # noqa: BLE001 — il ws non deve mai rompere la proposta
            ws = ""
    os.makedirs(PROPOSAL_DIR, exist_ok=True)
    pid = "%d-%s" % (int(time.time() * 1000), scope)
    rec = {"id": pid, "ts": time.time(), "scope": scope,
           "content": str(content)[:8000], "reason": str(reason)[:500],
           "target_path": target_path, "status": "pending", "ws": ws}
    with open(_path(pid), "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)
    return rec


def get_proposal(pid):
    try:
        with open(_path(pid), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def list_proposals():
    out = []
    try:
        for fn in sorted(os.listdir(PROPOSAL_DIR)):
            if fn.endswith(".json"):
                p = get_proposal(fn[:-5])
                if p:
                    out.append(p)
    except OSError:
        pass
    return out


def _save(rec):
    with open(_path(rec["id"]), "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)
    return rec


def decide(pid, decision):
    """approve|deny. Solo 'approve' su project/global scrive (append) le regole."""
    rec = get_proposal(pid)
    if not rec or rec.get("status") != "pending":
        return {"ok": False, "error": "proposal not found or not pending"}
    if decision == "deny":
        rec["status"] = "denied"
        return {"ok": True, **_save(rec)}
    if decision != "approve":
        return {"ok": False, "error": "decision must be approve|deny"}
    if rec.get("scope") == "skill":
        # JAG-128B deferred: l'apply di una skill non e' implementato. NON si
        # marca 'approved' in silenzio: lo status resta 'pending' e si dice il vero.
        return {"ok": False, "error": "skill apply not implemented (JAG-128B deferred)"}
    if rec["scope"] in ("project", "global"):
        from . import rules
        rules.append(rec["scope"], rec["content"], ws=rec.get("ws"))
    rec["status"] = "approved"
    return {"ok": True, **_save(rec)}
