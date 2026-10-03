#!/usr/bin/env python3
"""v0.9.41 acceptance — armonia tra i meccanismi (JAG-136).

I meccanismi (verifier, best-of-N, difficulty, keepgoing, runmetrics, selfevolve)
devono condividere UN solo stimatore di difficolta', UNA superficie di config e
eventi coerenti. Qui si verificano i LINK, non i singoli moduli (gia' coperti).
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


srv = open(os.path.join(REPO, "src", "sparkforge", "server.py"), encoding="utf-8", errors="replace").read()
api = open(os.path.join(REPO, "api_v02.py"), encoding="utf-8", errors="replace").read()
ui = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8", errors="replace").read()
rm = open(os.path.join(REPO, "src", "sparkforge", "runmetrics.py"), encoding="utf-8", errors="replace").read()
bs = open(os.path.join(REPO, "src", "sparkforge", "bestofn.py"), encoding="utf-8", errors="replace").read()
vf = open(os.path.join(REPO, "src", "sparkforge", "verify.py"), encoding="utf-8", errors="replace").read()

# H1: UN solo stimatore di difficolta' alimenta best-of-N e keepgoing.
check("H1 un solo stimatore (_diff_signals) usato da best-of-N e keepgoing",
      all(x in srv for x in ("_diff_signals(", "_bn.n_of(signals=_diff_signals(",
                             "_diff.rounds_for("))
      and srv.count("_diff_signals(") >= 3, "")
check("H1b il budget keepgoing e' ricalcolato a ogni giro",
      "budget di continuazione ricalcolato" in srv, "")

# H2: la difficolta' e' registrata nelle metriche del run.
check("H2 runmetrics.finish accetta e salva difficulty",
      "difficulty=None" in rm and 'rec["difficulty"] = difficulty' in rm
      and "model=model, difficulty=_diff_level" in srv, "")

from sparkforge import runmetrics  # noqa: E402
tmp_runs = tempfile.mkdtemp()
runmetrics.RUNS_DIR = tmp_runs
runmetrics.start("h", model="m")
rec = runmetrics.finish("h", outcome="done", difficulty="hard")
check("H2b difficulty persistita nel record",
      rec.get("difficulty") == "hard"
      and json.load(open(os.path.join(tmp_runs, "h.json"), encoding="utf-8"))["difficulty"] == "hard",
      str(rec.get("difficulty")))

# H3: selfevolve registra una sequenza per TURNO (chiavi distinte), non per sessione.
from sparkforge import selfevolve  # noqa: E402
tmpd = tempfile.mkdtemp()
os.environ["SPARKFORGE_DATA_DIR"] = tmpd
hp = os.path.join(tmpd, "seq.json")
selfevolve.record("sess#1.000", ["fs.read", "shell"], path=hp)
selfevolve.record("sess#2.000", ["fs.read", "shell"], path=hp)
check("H3 sequenze per-turno distinte (2 record, non 1)",
      len(selfevolve.history(hp)) == 2, str(selfevolve.history(hp)))
check("H3b il server usa una chiave per-turno",
      '_se.record("%s#%.3f"' in srv, "")

# H4: superficie di config unica — /api/tools espone tutti i blocchi.
need = ["runtime", "verifier", "bestofn", "difficulty", "selfevolve"]
check("H4 GET /api/tools espone tutti i blocchi di config",
      all(('"%s": registry.load_config()' % k) in api for k in need), "")
check("H4b WebUI carica tutte le card di config",
      all(("load" + k.capitalize() + "()") in ui
          for k in ["runtime", "verifier", "bestofn", "difficulty", "selfevolve"])
      or all(("load%s" % k.title()) in ui for k in need), "")
check("H4c POST /api/tools gestisce tutti i blocchi",
      all(('body.get("%s")' % k) in api for k in need), "")

# H5: i link tra moduli restano quelli giusti.
check("H5 verifier agisce solo su fs.write/fs.edit",
      vf.count('TARGET_TOOLS = ("fs.write", "fs.edit")') == 1, "")
check("H5b best-of-N usa di default il ranker prm",
      "import prm" in bs and "scorer = prm.rank_text" in bs, "")
check("H5c difficulty alimenta best-of-N (adaptive)",
      "difficulty.n_for(signals)" in bs, "")

# H6: l'abort ha precedenza e chiude con esito esplicito.
check("H6 l'abort interrompe prima dei tool e chiude il turno",
      'publish("chat.interrupted"' in srv and 'outcome=("user_abort"' in srv, "")

print("\n==== %d/%d checks passed ====" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
