#!/usr/bin/env python3
"""Stima della difficolta' del task (JAG-134).

Test-time compute "compute-optimal" (Snell et al., arXiv:2408.03314): l'efficacia
dello scaling dipende dalla difficolta' del prompt, quindi l'harness deve stimarla
e allocare di conseguenza (quanti candidati campionare, quanti giri di
continuazione concedere) invece di usare un budget fisso.

Stima DETERMINISTICA e spiegabile: nessuna chiamata al modello, solo segnali che
l'harness gia' possiede (nodi aperti del task graph, lunghezza del messaggio,
esito dei turni precedenti, quanti tool sono serviti). Modulo PURO.
"""
DEFAULTS = {
    "enabled": True,
    "easy_n": 1,        # candidati best-of-N per un task facile
    "medium_n": 2,
    "hard_n": 3,
    "medium_at": 0.35,  # soglia di punteggio -> "medium"
    "hard_at": 0.65,    # soglia di punteggio -> "hard"
}


def cfg(override=None):
    """Config effettiva: DEFAULTS <- config/tools.yaml (difficulty) -> override."""
    out = dict(DEFAULTS)
    try:
        from . import registry
        got = registry.load_config().get("difficulty") or {}
        if isinstance(got, dict):
            out.update({k: v for k, v in got.items() if v is not None})
    except Exception:  # noqa: BLE001
        pass
    if isinstance(override, dict):
        out.update(override)
    return out


def score(signals, c=None):
    """Punteggio di difficolta' in [0,1] dai segnali disponibili (0 = banale)."""
    s = signals or {}
    total = 0.0
    open_nodes = int(s.get("open_nodes") or 0)
    total += min(open_nodes * 0.15, 0.45)
    if int(s.get("msg_words") or 0) >= 120:
        total += 0.15
    if s.get("prev_error"):
        total += 0.20
    if s.get("prev_no_progress"):
        total += 0.20
    if int(s.get("tool_count") or 0) >= 6:
        total += 0.10
    if int(s.get("history_fail") or 0) >= 2:
        total += 0.15
    return round(max(0.0, min(1.0, total)), 3)


def estimate(signals, c=None):
    """Ritorna {"level","score","n","rounds"} — la policy di allocazione."""
    c = c or cfg()
    sc = score(signals, c)
    if not c.get("enabled"):
        level = "easy"
    elif sc >= float(c.get("hard_at") or 0.65):
        level = "hard"
    elif sc >= float(c.get("medium_at") or 0.35):
        level = "medium"
    else:
        level = "easy"
    n = {"easy": c.get("easy_n"), "medium": c.get("medium_n"),
         "hard": c.get("hard_n")}.get(level, 1)
    try:
        n = max(1, int(n))
    except (TypeError, ValueError):
        n = 1
    # i giri di continuazione scalano con la difficolta' (2x su hard rispetto a easy)
    rounds_mult = {"easy": 1.0, "medium": 1.5, "hard": 2.0}.get(level, 1.0)
    return {"level": level, "score": sc, "n": n, "rounds_mult": rounds_mult}


def n_for(signals, c=None):
    """Numero di candidati best-of-N suggerito dalla difficolta'."""
    return estimate(signals, c)["n"]


def rounds_for(base_rounds, signals, c=None):
    """`base_rounds` (keepgoing_max) scalato per la difficolta', con tetto 4x."""
    mult = estimate(signals, c)["rounds_mult"]
    try:
        out = int(round(float(base_rounds) * mult))
    except (TypeError, ValueError):
        out = int(base_rounds or 0)
    cap = int(base_rounds or 0) * 4
    return max(1, min(out, cap)) if cap else out
