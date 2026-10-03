# JAG-131 — Verifier "apply-only-if-green" (design)

Fonte: `docs/research/harness-frontier-2026.md` §1 (verifier / test-time verification),
`docs/specs/2026-10-03-harness-evolution-assessment.md` (punto 1 della roadmap).

## Problema

Oggi l'agente applica `fs.write`/`fs.edit` e **solo dopo** vede l'esito: la correttezza non
è dimostrata prima di accettare l'azione. Il gap rispetto agli harness di frontiera è il
pattern **edit → test → rollback**.

## Soluzione

Nuovo modulo puro `verify.py` + integrazione in `tools.py`:

- `verify.cfg()` legge il blocco `verifier` da `config/tools.yaml` (DEFAULTS <- config -> override).
- Config: `enabled` (default **false**), `command` (default vuoto), `timeout_secs`, `paths` (scope opzionale).
- `verify.should_verify(tool, path)`: solo per `fs.write`/`fs.edit`, con verifier attivo e path in scope.
- `verify.verify(tool, path, snap, res, workspace)`: esegue il comando **nella sandbox**
  (`sandbox.run`); se **verde** lascia la modifica; se **rosso** ripristina il pre-image
  (o elimina il file nuovo) e trasforma `res` in un fallimento con l'errore del check.
- `tools._verify_edit(...)` cabla la cosa dopo la scrittura/journal di `fs.write`/`fs.edit`
  e pubblica l'evento `verify.run`.

## Superfici

- `verify.py` (nuovo), `tools.py` (`_verify_edit` + call-site), `registry.py`
  (`verifier` in DEFAULT_CONFIG / `_merge_into` / `_diff_overlay`), `config/tools.yaml`
  (blocco `verifier`, default off), `api_v02.py` (`GET /api/tools` espone `verifier`;
  `POST /api/tools` accetta `{verifier:{...}}`), `webui/index.html` (card Verifier + evento
  `verify.run`), `tests/v144_verifier_green.py`.

## Perché default OFF

Un verifier attivo su ogni scrittura sorprenderebbe: serve un comando di progetto che
l'operatore configura. Con `command: ""` il modulo è inerte (zero overhead).

## Test

`tests/v144_verifier_green.py` — 10 check: defaults, attivazione, scope, `run_check`,
green preserva la modifica, red fa rollback, red cancella il file nuovo, wiring in tools,
card webui + api + yaml. Più la non-regressione della suite.

## Limiti / next

- Il check gira **dopo** la scrittura sul filesystem reale (non su una copia): il rollback
  è deterministico ma il file è temporaneamente "sporco".
- Non ancora: verifica su copia staging (`best-of-N`), costo/latenza adattivi, ranking PRM
  del candidato (punto 2 roadmap).
