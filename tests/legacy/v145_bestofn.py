#!/usr/bin/env python3
"""v0.9.38 acceptance — best-of-N + rank (JAG-132)."""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


from sparkforge import bestofn  # noqa: E402
from sparkforge import prm  # noqa: E402
from sparkforge import registry  # noqa: E402

check("N1 disabled by default (n=1)", bestofn.n_of({}) == 1, "")
check("N2 enabled n=3", bestofn.n_of({"enabled": True, "n": 3}) == 3, "")
check("N3 n clamps to [1,16]",
      bestofn.n_of({"enabled": True, "n": 0}) == 1
      and bestofn.n_of({"enabled": True, "n": 99}) == 16, "")
check("N4 registry exposes bestofn", "bestofn" in registry.load_config(), "")

action = '{"action":"tool","tool":"fs.read","args":{"path":"x"}}'
prose = ("Ho letto il file x: contiene tre funzioni e nessun errore di sintassi, "
         "quindi la modifica e' coerente con il resto del modulo.")
announce = "Procedo con la ricerca live ora."
malformed = '{"action": "tool", "tool": "fs.read", "args": {'
s_valid = prm.rank_text(action)
s_prose = prm.rank_text(prose)
s_ann = prm.rank_text(announce)
s_bad = prm.rank_text(malformed)
check("N5 valid action ranks highest",
      s_valid > s_prose and s_valid > s_ann and s_valid > s_bad,
      "act=%.2f prose=%.2f ann=%.2f bad=%.2f" % (s_valid, s_prose, s_ann, s_bad))
check("N6 announcement and malformed JSON are penalised",
      s_ann < 0.4 and s_bad < 0.4, "ann=%.2f bad=%.2f" % (s_ann, s_bad))
check("N7 empty text is 0", prm.rank_text("") == 0.0, "")

ordered = prm.rank([malformed, prose, action, announce])
check("N8 prm.rank sorts best-first", ordered[0][0] == action, str([round(s, 2) for _, s in ordered]))

best, scores = bestofn.choose([malformed, prose, action], c={"enabled": True, "n": 3})
check("N9 choose picks the valid action", best == action and len(scores) == 3, "")
none_best, _ = bestofn.choose(["", "   "], c={"min_score": 0.3})
check("N10 min_score floor yields None", none_best is None, "")

srv = open(os.path.join(REPO, "src", "sparkforge", "server.py"), encoding="utf-8", errors="replace").read()
check("N11 chat loop wires best-of-N (guarded, n>1)",
      "import bestofn as _bn" in srv and "bestofn.chosen" in srv and "_bN > 1" in srv, "")

web = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8", errors="replace").read()
api = open(os.path.join(REPO, "api_v02.py"), encoding="utf-8", errors="replace").read()
cfg_yaml = open(os.path.join(REPO, "config", "tools.yaml"), encoding="utf-8").read()
check("N12 webui best-of-N card + api + yaml",
      "saveBestofn" in web and "bnN" in web
      and '"bestofn"' in api and "bestofn:" in cfg_yaml, "")

total = len(results)
print("\n==== %d/%d checks passed ====" % (sum(results), total))
sys.exit(0 if all(results) else 1)