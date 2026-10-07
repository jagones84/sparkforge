# Assessment — sparkforge vs gli harness di frontiera (indipendenti dal modello)

Seed: `docs/research/harness-evolution.md` (4 fonti primarie). Giudizio sul **harness**, non sul modello:
è qui che secondo SWE-bench/TTC/Self-evolving si guadagnano i punti, a parità di pesi.

## Asse 1 — Verifica prima di applicare l'azione (verifier loop / PRM)

**Cosa ha già sparkforge (PARZIALE):**
- Sandbox reale (`docker`/`bubblewrap`/`nsjail`, `--network none`, rootfs read-only) — vedi README.
- Approval gate su ogni azione world-touching + hooks `PreToolUse`/`PostToolUse`/`Stop`.
- `api_v02.verify` → `prm_report` + evento `prm.feedback` (score) = un PRM leggero già nel loop agent.

**Gap:** il verifier NON rigetta la patch in automatico. L'azione `fs.write`/`fs.edit` viene
applicata e solo DOPO il modello vede l'esito. Manca il pattern di SWE-RM: giudicare la
traiettoria/patch **prima** di validarla (test automatici + analisi statica/AST nel sandbox).

## Asse 2 — Test-Time Compute e allocazione dinamica

**Cosa ha (ASSENTE):** il loop agent è **lineare** (sense→think→act), `max_steps`,
auto-continue `keepgoing`, subagent con depth cap (matrioska). Nessuna diramazione MCTS,
nessun best-of-N, nessun budget per-difficoltà.

**Gap:** per refactoring complesso non esiste calcolo speculativo né esplorazione parallela.
DeepMind (Snell 2408.03314): allocazione compute-optimal (>4× su best-of-N). AlphaCode:
N campioni → filtro per esecuzione su test → cluster → top candidati.

## Asse 3 — Self-evolving harness / sintesi autonoma di skill

**Cosa ha (PARZIALE, propose-only):** tool `improve` (proposte `memory|skill|project|global`,
`code:forbidden`), `memory` tool, registry `skills/`. Ma le proposte restano **proposte**
(attesa approvazione umana).

**Gap (Voyager 2305.16291):** manca il ciclo che **verifica in sandbox** la nuova skill
finché non passa e poi la **archivia** come nativa riusabile (self-verification + skill library).

## Roadmap prioritaria (per ROI)

1. **Verifier loop "apply-only-if-green"** — ✅ FATTO (JAG-131, commit `8a901aa`):
   `verify.py` + `tools._verify_edit` su `fs.write`/`fs.edit`; edit → check in sandbox →
   rollback se rosso; config `verifier` (default off) + card WebUI. Test `v144` 10/10.
2. **Best-of-N + rank PRM** — ✅ FATTO (JAG-132, commit `97f0bc3`): `bestofn.py` +
   `prm.rank_text/rank`; campiona N solo quando il primo campione è inutilizzabile
   (early-exit); config `bestofn` + card WebUI. Test `v145` 12/12.
3. **Budget per difficoltà** — ✅ FATTO (JAG-134, commit `9672af0`): `difficulty.py`
   (stima deterministica dai segnali) → scala N (best-of-N adattivo) e i giri
   `keepgoing_max`; config `difficulty` + card WebUI. Test `v147` 17/17.
4. **Skill synthesis autonoma** — ✅ FATTO (JAG-133/135): `selfevolve.py` miner
   (stadio 1) + stadio 2 synth → verify in sandbox → archive write-gated
   (`synth`/`verify`/`promote`/`pipeline`, tool `improve` action `evolve`).
   Test `v146` 12/12 + `v148` 15/15.

Aggiornamento 2026-10-03: 1–4 implementati, testati e pushati. Resta l'**armonia**
dei link tra i meccanismi (config unica + eventi coerenti) e la suite end-to-end.