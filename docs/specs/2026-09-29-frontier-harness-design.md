# SparkForge — Spec: da v0.1 a harness di frontiera completa

- **Data**: 2026-09-29
- **Origine**: JAG-32 (richiesta utente: "non è una harness con tutte le caratteristiche di frontiera, anche quelle non ancora rilasciate… veramente una harness spaziale")
- **Repo**: `/home/jagones/Repositories/sparkforge`
- **Contesto**: la org Paperclip (Coordinator → Lead → specialisti) deve portare SparkForge da "harness dimostrativa" a harness di frontiera operativa, con tool reali, sandbox, memoria e interoperabilità.

## 1. Stato attuale (v0.1 "Genesis")

Chat streaming + CoT visibile, store **PLAN**, board **TASKS**, agent-loop `thought→action→observation`
**strutturalmente sandboxed** (nessun tool reale: non tocca shell/FS), feed SSE `/api/feed`,
WebUI, CLI `forge.py`, API mobile. Backend locale: llama.cpp router `:8080`.

Gap: la harness *decide* ma **non agisce** sul mondo; non ha memoria duratura, non si interfaccia
con altri agenti, non è osservabile né sempre-attiva.

## 2. Principi guida

1. **Local-first**: gira sul DGX con i modelli locali; nessuna dipendenza cloud obbligatoria.
2. **Sandbox-first per default** (pattern Codex/Cline): ogni azione che tocca il mondo passa da un gate.
3. **Osservabile**: ogni evento è durevole e riproducibile.
4. **Interoperabile**: parla standard (MCP, ACP, AGENTS.md) invece di essere un monolite.
5. **Nessun "fatto" senza evidenza**: criterio di accettazione = comando eseguito + output letto.

## 3. Fasi

### v0.2 — Esecuzione sicura + interop di base (milestone prioritaria)

- **Tool registry** — tool dichiarativi (`shell`, `fs.read`, `fs.write`, `git`, `http`, `browser`) con schema JSON, abilitabili via allowlist (`config/tools.yaml`).
- **Approval gates** — ogni azione sensibile entra in una **coda di approvazioni** (`/api/approvals`), con auto-approve configurabile per pattern (es. comandi read-only). Risultato del tool → `observation`.
- **Sandbox reale** — esecuzione in `bubblewrap`/`nsjail` (bind-mount selettivo, FS temporaneo, no rete di default) oppure container; il processo agente non vede l'host.
- **HITL** — pausa / riprendi / interrompi a metà run (`/api/agent/control`); l'approvazione arriva dal telefono o dalla WebUI.
- **MCP server mode** — esporre SparkForge come **server MCP** (chat, plan, tasks, agent-run, feed) così che Paperclip (OpenClaw/Hermes) possa pilotarlo.

### v0.3 — Capacità agente + memoria

- **MCP client** (pattern Goose): collegare i server MCP già presenti (Filesystem, Playwright, ecc.) come tool nativi.
- **Subagent delegation** (pattern deepagents): il loop può spawnare run figli con contesto isolato e raccoglierne il risultato.
- **Checkpoint / resume / rollback** dello stato (plan, tasks, transcript) con idempotenza.
- **Memoria persistente** con write-rules (markdown append-only + indice vettoriale opzionale); scrittura solo su eventi significativi.
- **Context engineering**: compaction del transcript, budget di token, retrieval dai documenti.
- **Multi-model routing**: selezione modello per ruolo/abilità dal roster del router `:8080` + fallback (DeepSeek).

### v0.4 — Ops + mobile + valutazione

- **Event store durevole** (SQLite) + replay; il feed SSE si riconnette con `?since=`.
- **Tracing OpenTelemetry** + token/cost accounting per run.
- **systemd user unit** always-on (`sparkforge.service`), con auth token sulla API.
- **WebUI auth flow** (prompt token quando avviato con `--token`).
- **Mobile streaming nativo**: la app SparkPulse usa SSE (`/api/chat/stream`, `/api/feed`) invece del one-shot REST; Command tab con plan/tasks/feed/approvazioni live.
- **Voce**: whisper.cpp (STT) + sherpa-onnx (TTS) per comandi vocali dal telefono.
- **Eval harness**: gold task set + scoring della qualità del loop (pattern Winder.AI).

### Sperimentale (frontiera "non ancora rilasciata")

- **Meta-harness self-improvement** (Lil'Log 2026): un outer-loop propone varianti della harness e le valuta su una frontiera di Pareto (qualità vs costo).
- **ACP (Agent Client Protocol)**: farsi pilotare e guidare altri harness (interoperabilità bidirezionale).
- **Swarm / blackboard**: più agenti che cooperano su uno stato condiviso.

## 4. Contratti API (aggiunte)

| Metodo | Path | Scopo |
|---|---|---|
| GET/POST | `/api/tools` | registry tool abilitati |
| GET/POST | `/api/approvals` | coda approvazioni; `POST /api/approvals/:id {decision}` |
| POST | `/api/agent/control` | `{runId, action: pause\|resume\|abort}` |
| GET/POST | `/api/memory` | store memoria con write-rules |
| GET | `/api/runs/:id/trace` | OTel trace + token/cost |
| (MCP) | `/mcp` | server MCP (tools: chat/plan/tasks/agent_run/feed) |

## 5. Criteri di accettazione

- **v0.2**: un run agente esegue un comando shell reale in sandbox, con approvazione registrata e output come observation; Paperclip apre una sessione MCP verso SparkForge e riceve una risposta.
- **v0.3**: un agente delega a un subagent e ne usa il risultato; il run sopravvive a un restart (resume); una risposta usa la memoria di una sessione precedente.
- **v0.4**: servizio always-on; dal telefono si vede lo stream live e si approva un'azione; una eval run produce un punteggio.
- **Ogni fase**: nessuna dichiarazione "fatto" senza comando + output verificabile; aggiornare `docs/PLAN.md` e `README.md`.

## 6. Non-obiettivi (per ora)

- Nessuna dipendenza da cloud LLM proprietario come percorso primario.
- Nessuna esecuzione di azioni distruttive senza approvazione esplicita.
- Non riscrivere la WebUI da zero: estenderla.
