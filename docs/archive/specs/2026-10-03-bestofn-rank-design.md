# JAG-132 — Best-of-N + rank (design)

Fonte: `docs/research/harness-frontier-2026.md` §2 (Test-Time Compute & allocazione
adattiva), `docs/specs/2026-10-03-harness-evolution-assessment.md` (punto 2 della roadmap).

## Problema

Il chat loop accetta il PRIMO campione del modello. Quando quel campione è un
tool-call JSON malformato, l'unica strategia era ri-promptare (una sola volta).
Non esiste allocazione adattiva del compute: nessuna scelta tra più candidati.

## Soluzione (compute-optimal, off di default)

- `bestofn.py` (nuovo, puro): `cfg()`, `n_of()` (1 se disattivato, clamp [1,16]),
  `choose(candidates, scorer, c)` che ritorna il migliore + i punteggi e rispetta
  `min_score` (sotto soglia → None).
- `prm.rank_text(text)` (deterministico, nessuna chiamata al modello) e `prm.rank(list)`:
  premia un'azione valida/parseable e prosa concreta; penalizza JSON malformato
  (anche troncato) e le risposte di solo annuncio. È il ranker.
- Integrazione in `chat_once`: **solo** quando il primo campione è inutilizzabile
  (`_looks_like_json_action`) e `n>1`, si campionano fino a N candidati — con early-exit
  appena ne compare uno usabile — e `bestofn.choose` sceglie il migliore. Evento
  `bestofn.chosen`.
- Config `bestofn` in `config/tools.yaml` (default `enabled: false`, `n: 1` = zero
  overhead), esposta da `GET/POST /api/tools` e dalla Config WebUI.

## Superfici

`bestofn.py` (nuovo), `prm.py` (rank_text/rank + `_extract_json_obj`), `server.py`
(blocco best-of-N), `registry.py` (`bestofn` in defaults/merge/diff), `config/tools.yaml`,
`api_v02.py` (GET/POST), `webui/index.html` (card + evento), `tests/v145_bestofn.py`.

## Perché è "compute-optimal" e sicuro

- Il compute extra si spende **solo** quando il campione è rotto (task "difficile"),
  con early-exit: sui task facili N=1 e nessuna differenza dal comportamento attuale.
- Il ranker è deterministico: nessun modello in più, nessun costo, testabile a unità.
- Default OFF: si accende da config/WebUI (`bestofn.n`).

## Test

`tests/v145_bestofn.py` — 12 check: default/clamp, registry, ordinamento di `rank_text`
(azione valida > prosa > annuncio > JSON troncato), `choose`, soglia `min_score`,
wiring in server, card WebUI + API + yaml. Più la non-regressione della suite.

## Next

- Verifica dei candidati con il verifier (JAG-131) prima di scegliere → best-of-N
  "green-only" (search contro verifier, Snell §2).
- Budget per difficoltà stimata invece della sola euristica "campione rotto".
