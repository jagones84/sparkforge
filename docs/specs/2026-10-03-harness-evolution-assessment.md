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

1. **Verifier loop "apply-only-if-green"** — il primo passo, il più alto ROI (quote SWE-bench:
   +20-30pt dal harness, non dal modello). Per ogni `fs.write`/`fs.edit`/patch: eseguire nel
   sandbox i test/analisi statica PRIMA di accettare; se fallisce, rigettare e re-indirizzare.
2. **Best-of-N + rank PRM** — per step non banale campionare N candidati e rankarli col
   verifier già esistente (prima della MCTS completa).
3. **Budget per difficoltà** — task banale = zero-shot; complesso = N rami paralleli.
4. **Skill synthesis autonoma** — `improve` da "propose" a "synthesize→verify→archive":
   sequenze ripetitive di N tool → script ottimizzato → sandbox-verify → registra skill nativa.

Primo SPEC raccomandato (da scrivere in `docs/plans/`): il **point 1** — usa già
sandbox+approvals+hooks, è a rischio contenuto e dà il guadagno più misurabile.