#!/usr/bin/env python3
"""Best-of-N con ranker (JAG-132).

Test-time compute "compute-optimal": per uno step NON banale l'harness campiona
N candidati dal modello e sceglie il migliore con un ranker deterministico
(`prm.rank_text`), invece di accettare il primo. Per i task facili (N=1) il
comportamento resta identico: nessun overhead.

Modulo PURO: la logica di scelta non dipende dal server. La generazione dei
candidati (N chiamate al modello) e' responsabilita' del chiamante; qui vive solo
`choose()` + i default di config.

Config (blocco `bestofn` in config/tools.yaml):

    bestofn:
      enabled: false
      n: 1            # 1 = disattivato (comportamento attuale)
      min_score: 0.0  # se il migliore resta sotto questa soglia -> None
"""
import os

DEFAULTS = {
    "enabled": False,
    "n": 1,
    "min_score": 0.0,
}


def cfg(override=None):
    """Config effettiva: DEFAULTS <- config/tools.yaml (bestofn) -> override."""
    out = dict(DEFAULTS)
    try:
        import registry
        got = registry.load_config().get("bestofn") or {}
        if isinstance(got, dict):
            out.update({k: v for k, v in got.items() if v is not None})
    except Exception:  # noqa: BLE001
        pass
    if isinstance(override, dict):
        out.update(override)
    return out


def n_of(c=None):
    """Numero di candidati da campionare (>=1). 1 = disattivato."""
    c = c or cfg()
    if not c.get("enabled"):
        return 1
    try:
        n = int(c.get("n") or 1)
    except (TypeError, ValueError):
        n = 1
    return max(1, min(n, 16))


def choose(candidates, scorer=None, c=None):
    """Sceglie il candidato migliore secondo `scorer` (default prm.rank_text).

    Ritorna (best, scores): `best` e' None se nessun candidato raggiunge
    `min_score` (o la lista e' vuota). `scores` e' la lista (candidato, punteggio).
    """
    c = c or cfg()
    if scorer is None:
        try:
            import prm
            scorer = prm.rank_text
        except Exception:  # noqa: BLE001
            scorer = lambda _t: 0.0  # noqa: E731
    items = [(x, _score(scorer, x)) for x in (candidates or [])]
    if not items:
        return None, []
    best, best_score = max(items, key=lambda kv: kv[1])
    try:
        floor = float(c.get("min_score") or 0.0)
    except (TypeError, ValueError):
        floor = 0.0
    if best_score < floor:
        return None, items
    return best, items


def _score(scorer, text):
    try:
        return float(scorer(text))
    except Exception:  # noqa: BLE001
        return 0.0
