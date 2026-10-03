#!/usr/bin/env python3
"""Self-evolving harness — miner di sequenze ripetute (JAG-133).

Primo stadio della sintesi autonoma di skill (Voyager-style, adattata): se
l'harness osserva che l'agente ripete la STESSA sequenza di tool su run diversi,
quella sequenza e' un candidato skill. Qui la si rileva in modo deterministico e
si emette una BOZZA di skill (proposta + `SKILL.md`), senza mai eseguire nulla e
senza auto-archiviare: la promozione resta una decisione umana (o del ciclo di
verifica sandbox, step successivo).

Modulo PURO: nessuna dipendenza dal server, testabile a unita'.
"""
import json
import os
import re
import time

REPO = os.path.dirname(os.path.abspath(__file__))

DEFAULTS = {
    "min_len": 2,      # lunghezza minima della sequenza (numero di tool)
    "min_count": 3,    # quante run diverse devono contenere la sequenza
    "max_len": 6,      # non cercare sequenze piu' lunghe di cosi'
}


def cfg(override=None):
    out = dict(DEFAULTS)
    try:
        import registry
        got = registry.load_config().get("selfevolve") or {}
        if isinstance(got, dict):
            out.update({k: v for k, v in got.items() if v is not None})
    except Exception:  # noqa: BLE001
        pass
    if isinstance(override, dict):
        out.update(override)
    return out


def _ngrams(seq, k):
    return [tuple(seq[i:i + k]) for i in range(len(seq) - k + 1)]


def mine(sequences, c=None):
    """Trova le sequenze contigue di tool ripetute su run diversi.

    Args:
        sequences: lista di run; ogni run e' la lista dei NOMI dei tool usati,
            in ordine di esecuzione.
    Returns:
        lista di {"pattern": [tool,...], "length": k, "support": n, "runs": [idx]}
        ordinata per (length*support) decrescente; i pattern piu' lunghi con lo
        stesso supporto vincono sui loro sotto-pattern.
    """
    c = c or cfg()
    mn = max(1, int(c.get("min_len") or 2))
    mc = max(2, int(c.get("min_count") or 3))
    mx = max(mn, int(c.get("max_len") or 6))
    seqs = [[str(x) for x in (s or [])] for s in (sequences or [])]
    found = {}
    for k in range(mn, mx + 1):
        for idx, s in enumerate(seqs):
            for ng in set(_ngrams(s, k)):
                e = found.setdefault(ng, set())
                e.add(idx)
    cands = [{"pattern": list(ng), "length": len(ng), "support": len(runs),
              "runs": sorted(runs)}
             for ng, runs in found.items() if len(runs) >= mc]
    # preferisci i pattern piu' lunghi: se un pattern estende un altro con lo
    # stesso insieme di run, tieni solo il piu' lungo (piu' specifico).
    cands.sort(key=lambda d: (d["length"], d["support"]), reverse=True)
    out = []
    for d in cands:
        rs = set(d["runs"])
        if any(set(o["runs"]) == rs and o["length"] > d["length"] for o in out):
            continue
        out.append(d)
    out.sort(key=lambda d: (d["length"] * d["support"], d["support"]), reverse=True)
    return out


def slug(pattern):
    """Slug filesystem-safe per un pattern di tool."""
    raw = "-".join(pattern)
    s = re.sub(r"[^a-zA-Z0-9._-]+", "-", raw).strip("-").lower()
    return (s or "skill")[:64]


def draft(pattern, support, out_dir, note=""):
    """Scrive una BOZZA di skill (proposal.json + SKILL.md). Non esegue nulla.

    Ritorna il path della cartella proposta, o None se la scrittura fallisce.
    """
    name = slug(pattern)
    d = os.path.join(out_dir, name)
    try:
        os.makedirs(d, exist_ok=True)
        proposal = {"kind": "skill", "status": "proposed", "name": name,
                    "pattern": list(pattern), "length": len(pattern),
                    "support": int(support), "created": round(time.time(), 3),
                    "note": note,
                    "next": "verify in sandbox, then archive to skills/"}
        with open(os.path.join(d, "proposal.json"), "w", encoding="utf-8") as f:
            json.dump(proposal, f, ensure_ascii=False, indent=2)
        steps = "\n".join("%d. `%s`" % (i + 1, t) for i, t in enumerate(pattern))
        md = ("# Skill proposta: %s\n\n"
              "Rilevata automaticamente su **%d run** (JAG-133). Sequenza di tool:\n\n"
              "%s\n\n"
              "## Stato\n\nBOZZA — non ancora verificata ne' archiviata. Prossimo: generare "
              "lo script, eseguirlo in sandbox sui casi reali e, se verde, promuoverla in "
              "`skills/<categoria>/<nome>/SKILL.md`.\n"
              % (name, support, steps))
        with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(md)
        return d
    except OSError:
        return None


def scan(sequences, out_dir, c=None, note=""):
    """Mina le sequenze e scrive una bozza per ciascun pattern. Ritorna i percorsi."""
    c = c or cfg()
    paths = []
    for cand in mine(sequences, c):
        p = draft(cand["pattern"], cand["support"], out_dir, note=note)
        if p:
            paths.append(p)
    return paths


# ------------------------------------------------------------- history -------

def _history_path():
    base = os.environ.get("SPARKFORGE_DATA_DIR") or os.path.join(REPO, "data")
    return os.path.join(base, "sequences.json")


def record(key, tools, path=None):
    """Registra la sequenza di tool di un run (per il mining successivo).

    Mantiene le ultime 500 run. Mai bloccante: un errore di scrittura e' ignorato.
    """
    seq = [str(t) for t in (tools or []) if str(t).strip()]
    if not seq or not key:
        return False
    p = path or _history_path()
    try:
        data = {}
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                data = json.load(f) or {}
        if not isinstance(data, dict):
            data = {}
        data[str(key)] = {"tools": seq, "ts": round(time.time(), 3)}
        if len(data) > 500:
            for k in sorted(data, key=lambda x: data[x].get("ts", 0))[:len(data) - 500]:
                data.pop(k, None)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
        return True
    except OSError:
        return False


def history(path=None):
    """Le sequenze registrate, come lista di liste di tool-name."""
    p = path or _history_path()
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f) or {}
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    return [e.get("tools", []) for e in data.values() if isinstance(e, dict)]


def mine_history(out_dir, c=None, path=None, note=""):
    """Mina la history registrata e scrive le bozze. Ritorna i percorsi."""
    return scan(history(path), out_dir, c, note=note)
