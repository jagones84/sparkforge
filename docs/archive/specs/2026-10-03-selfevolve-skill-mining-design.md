# JAG-133 — Self-evolving: miner di sequenze → bozza di skill (design)

Fonte: `docs/research/harness-frontier-2026.md` §3 (self-evolving / meta-apprendimento),
`docs/specs/2026-10-03-harness-evolution-assessment.md` (punto 4 della roadmap).

## Problema

L'utente di frontiera citato: "se l'harness rileva che l'agente esegue spesso una
sequenza ripetitiva di N comandi, l'harness stesso la impacchetta come skill". Oggi
sparkforge non osserva le proprie sequenze: `improve` accetta solo proposte scritte
dal modello, non quelle rilevate dai dati.

## Soluzione (stadio 1: detect + draft, mai auto-archivia)

- `selfevolve.py` (nuovo, puro):
  - `mine(sequences, c)`: trova le sequenze contigue (n-gram) di tool ripetute in
    ≥ `min_count` run; preferisce il pattern più lungo/specifico; filtro di dedup per
    lo stesso insieme di run.
  - `draft(pattern, support, out_dir)`: scrive `proposal.json` (`status: proposed`)
    + `SKILL.md` bozza. **Non esegue codice, non archivia.**
  - `record(key, tools)` / `history()` / `mine_history(out)`: history persistente
    (`data/sequences.json`, ultime 500 run) così il mining usa dati reali.
- Config `selfevolve` (`min_len`, `min_count`, `max_len`).
- Wiring: a fine turno l'harness registra la sequenza dei tool usati (`used_tools`);
  il tool `improve` accetta `scope: "mine"` e mina la history, depositando una bozza
  per ogni pattern ricorrente (evento `improve.proposal`).

## Superfici

`selfevolve.py` (nuovo), `tools.py` (`_improve` scope=mine), `registry.py`
(schema `improve` accetta `mine`; `content` non più required), `server.py`
(record della sequenza a fine turno), `tests/v146_selfevolve.py`.

## Perché è sicuro

La miniera è **deterministica e sola lettura**; l'output è una **bozza**
(`status: proposed`) in `data/proposals/skills/`. Nessuna scrittura in `skills/`,
nessuna esecuzione. La promozione (codegen + verify in sandbox + archive) è lo
stadio 2, non incluso.

## Test

`tests/v146_selfevolve.py` — 12 check: defaults, mining con supporto, un one-off non
proposto, dedup del pattern più lungo, soglia min_count, slug safe, scan → bozza,
proposal `proposed`, `SKILL.md`, round-trip history, `mine_history`, wiring
(improve scope=mine + record nel loop). Più la non-regressione della suite.

## Stadio 2 (FATTO — JAG-135)

`selfevolve.py` estende il miner con il ciclo Voyager **synthesize → verify → archive**:

- `synth(pattern, out_dir)`: codegen deterministico di `skill.json` (pipeline
  dichiarativa), `runner.py` (primitivo invocabile `run(invoke)`) e `check.py`
  (verifica **self-contained**: nessuna import dal repo, gira in qualunque sandbox).
- `verify(proposal_dir, runner=None)`: esegue `check.py` in sandbox via
  `sandbox.run` (host backend: cwd = cartella proposta); aggiorna `proposal.json`
  a `verified`/`rejected`. `runner` iniettabile per i test puri.
- `promote(proposal_dir, skills_dir=None)`: **write-gate** — archivia in
  `skills/<category>/<name>/` SOLO se `status == "verified"`; non sovrascrive;
  marca `archived` + `archived_to`.
- `pipeline(pattern, ...)`: ciclo completo (draft → synth → verify → promote se verde).
- Tool `improve` (`scope=mine`) con `action`: `mine` (bozza), `evolve` (stadio 2 su
  tutta la history), `verify`/`promote` (su una proposta via `path`).
- Config `selfevolve` (`category`, `verify_timeout`).

Test: `tests/v148_selfevolve2.py` — 15 check (synth/verify/promote/pipeline, write-gate,
no-overwrite, verify reale in sandbox host per pattern valido e tool sconosciuto, wiring).
