# RDD agenda — maxing the harness (ricerca + mercato)

Data: 2026-10-04. Fonti: "Harness Engineering" (Addy Osmani, apr 2026), Google Cloud
"Agent Factory", Anthropic "Effective harnesses", 20.574-session developer–agent
misalignment study, Survey 149 pagine "Towards Long-Horizon Agents", LongHorizon-Harness
(Alibaba DreamX), BAVAR (strategic verification), MCP 2026 roadmap, G2/StackOverflow
surveys, "Self-Evolving Agentic Harnesses".

## 1. Di cosa soffrono gli utenti (mercato)

- **Instruction-following failure = 36.5%** dei fallimenti (l'agente "capisce ma non fa"),
  contro solo **15.4%** di "istruzione poco chiara". → il fix NON è scrivere prompt
  migliori: sono i **gate** (enforcement deterministico). *(20.574 session study)*
- **3 fallimenti enterprise** (Microsoft/VentureBeat): context friabile (perde il filo
  dopo N file), refactor che rompono il **blast radius** (non chiede "chi chiama
  questo?"), **zero consapevolezza operativa** (Replit: l'agente ha cancellato il DB di
  produzione pur avendo istruzioni read-only).
- **Distrust**: 84% usa AI ogni giorno, solo **29% si fida** (in calo). Friction
  ricorrente: accuratezza/regressioni e "si blocca".
- Codex: ondate di lamentele "lento / lazy / dimentica le istruzioni".

## 2. Dove va la ricerca (2026)

- **Harness > modello**: cambiando solo l'harness, lo stesso modello guadagna decine di
  punti (Terminal-Bench 69.7%→77%). "È un problema di configurazione, non di modello".
- **4 pilastri**: contesto a tier (progressive disclosure), specializzazione (prompt
  scoped + tool ristretti), **memoria persistente su filesystem** (non nello storico),
  esecuzione strutturata **research→plan→execute→verify**.
- **Sweet spot del contesto ~40%**: oltre, le prestazioni degradano. Overload di tool/
  documenti PEGGIORA.
- **Long-horizon = gestione di stato**: lo stato vive FUORI dal contesto, aggiornato solo
  con fatti **verificati dall'ambiente**; loop **Manage–Execute–Audit** con un
  **auditor read-only**; +29pp su WeaveBench.
- **Verification adattiva (BAVAR)**: verificare solo dove conta, con budget; verificare
  anche memoria e skill riutilizzabili; il **verifier onesto è il tetto** di ogni
  self-improvement (tenerlo fuori dallo spazio modificabile).
- **Self-evoluzione**: reale ma instabile (34/64 modifiche generalizzano); servono gate
  held-out.
- **MCP**: la scala dei tool è un problema di protocollo → **progressive discovery**.
- **Budget-aware**: l'agente deve "sentire" difficoltà, token, tempo, costo per decidere
  quanto pensare.

## 3. Cosa la nostra harness HA già (e le altre spesso no)

Verifier gate (apply-only-if-green); PRM/best-of-N deterministico + stimatore difficoltà
compute-optimal; task graph LLM persistente con `done` gated dall'evidenza; anti-loop
(ri-run verbatim bloccato); act-not-announce; tool-output offload + budget reale
`n_ctx`; regole **rilette ogni turno** (live); feed SSE; MCP client+server; subagent;
memoria con CORE governato; skill search (L1/L2).

## 4. Backlog RDD prioritizzato (con criterio di accettazione)

**P1 — Step Auditor read-only (LongHorizon MEA).**
Dopo un passo `done` "rischioso" (scrive file/DB, deploy), un **auditor in contesto
fresco** certifica il cambiamento d'ambiente. *Accettazione:* un test deterministico che
un `done` senza prova d'ambiente NON chiude il nodo + un live test su un task multi-step.

**P2 — Verifica della memoria persistente (BAVAR-lite).**
Le scritture in memoria ottengono provenienza + scadenza; una memoria contraddetta è
screditata. *Accettazione:* `memory{store}` registra provenance; `recall` penalizza le
voci scadute; test.

**P3 — Budget-aware reasoning.**
Oltre alla difficoltà, stimare **token/step residui** e ridurre N / compattare prima.
*Accettazione:* metrica in runmetrics; soglie configurabili; nessuna regressione battery.

**P4 — MCP progressive discovery.**
Sopra ~50 tool abilitati, deferire gli schemi MCP dietro un `tools{action:"search"}`.
*Accettazione:* test che l'indice dei tool resta bounded; ricerca tool funzionante.

**P5 — Curare la libreria skill** (179 con doppioni). Rilevamento FATTO (JAG-203:
`skills{action:"audit"}` read-only: 1 gruppo con descrizione identica, 20 coppie di
nomi near-dup, 20 SKILL.md oversized). Resta la cura vera (dedup / "core set").
*Accettazione:* conteggio duplicati = 0; v198 verde.

**P6 — Self-evoluzione con verifier held-out onesto.**
Tenere il verifier fuori dallo spazio di ricerca; gate held-out. *Accettazione:* una
proposta di self-improve NON può modificare il verifier; test.

## 5. Ordine di esecuzione consigliato
P5 (igiene, basso rischio) → P4 (contesto) → P1 (auditor, alto impatto) → P3 → P2 → P6.
