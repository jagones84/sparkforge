# Idee raccolte dagli harness su GitHub (OpenHands / Goose / SDK)

Sorgenti: OpenHands Software Agent SDK (arXiv:2511.03690, github.com/OpenHands/software-agent-sdk);
All-Hands-AI/OpenHands; block/goose (Apache-2.0). Annotato con "ha già / gap" rispetto a sparkforge.

## 1. Event-sourced state (EventLog append-only = single source of truth)
OpenHands V1 separa l'**Agent** (stateless event processor) dalla **Conversation** che tiene un
EventLog append-only: lo stato si ricostruisce **replayando** gli eventi.
- sparkforge ha già: SSE (feed) + `taskgraph` persistente + `RunTrace` span.
- **gap/idea**: rendere l'EventLog la fonte di verità (replay→rebuild), non solo telemetria.

## 2. Workspace/execution come boundary remoto (Action Execution Server)
`LocalWorkspace` (no-op, diretto) / `DockerWorkspace` / `RemoteWorkspace` (HTTP → Agent Server):
l'esecuzione vive in un container che espone una mini-API, l'agent resta separato.
- sparkforge ha già: `sandbox.py` (docker/nsjail/bwrap, `--network none`).
- **idea**: fattorizzare l'esecuzione dietro la stessa interfaccia (locale vs remoto) → run su
  una seconda macchina (DGX/Windows) senza riscrivere l'agent loop.

## 3. Micro-agents / skill che si caricano da sole
OpenHands tiene `microagents/` e inietta automaticamente la knowledge rilevante (trigger per
keyword/embedding), non solo su chiamata esplicita.
- sparkforge ha già: `skills/` registry + tool `skills` (list/read) on-demand.
- **idea**: auto-inject della skill pertinente nel system prompt quando il task la richiama.

## 4. Stuck detection ("l'agente ha perso il filo")
Allarme dedicato che rileva ripetizione/stallo e forza un re-plan o l'intervento umano.
- sparkforge ha già: `keepgoing.no_progress` + `prm.step_repetition`.
- **idea**: unificare in un unico segnale `stuck` con azione (replan / notify / stop).

## 5. Secret registry + auto-masking
OpenHands registra i secret e li **maschera automaticamente** dall'output/transcript.
- sparkforge ha già: `.env`/`~/.hermes/.env` (mai nel repo).
- **gap/idea**: auto-mask dei secret nelle observation e nel transcript (non solo fuori dal repo).

## 6. Security: policy di conferma + risk analyzer
OpenHands combina policy deterministiche di conferma con un **analyzer di rischio** sull'azione.
- sparkforge ha già: `approvals` deterministiche + hooks `PreToolUse/PostToolUse`.
- **idea**: classifier opzionale "rischioso?" (modello veloce) prima dell'approval, default off.

## 7. Goose — extensibility via MCP first-class + Recipes
Goose: ogni estensione è un **MCP server**; le **Recipes** sono macro YAML di workflow riusabili;
modello lead-worker con sub-agent paralleli.
- sparkforge ha già: `mcp_clients.yaml` (pmcp, etc.) + subagent matrioska.
- **idea**: "recipe" dichiarativa (sequenza di tool) invocabile come UN passo, condivisibile.

## Sintesi (priorità nuove, in aggiunta alla roadmap verifier/TTC/self-evolving)
1. Secret auto-masking (basso costo, alto valore sicurezza).
2. Auto-inject delle skill rilevanti (micro-agents).
3. Event-sourced replay per lo stato (strutturale, piano piano).
4. Workspace remoto come boundary (per scalare su più macchine).
5. `stuck` detector unificato.