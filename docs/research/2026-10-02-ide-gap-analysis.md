# SparkForge — Gap Analysis vs IDE agentici di riferimento (2025-2026)

Data: 2026-10-02 · Metodo: confronto con 4 fonti primarie (Cursor 2.0/2.1 changelog, Claude
Code 2.x, Windsurf/Devin Desktop docs, GitHub Copilot docs/blog).
Scope: harness (`server.py` + moduli `.py`) vs `webui/index.html`.
Legenda: ✅ presente · ◐ parziale · ✖ assente · n/a non applicabile.

## (a) Matrice feature

| Funzione | Standard IDE (riferimento) | Harness/server SF | WebUI SF |
|---|---|---|---|
| Chat streaming SSE | tutti | ✅ `/api/chat/stream` | ✅ |
| Agent loop + task graph | tutti | ✅ `agent_run_v2`, `taskgraph.py` | ✅ tab tasks |
| Context compaction + meter | Claude Code (auto/`/compact`) | ✅ `context_engine.py` | ◐ |
| Providers/models CRUD + routing | Cursor, Copilot (model switcher) | ✅ `providers.py`, `routing.py` | ✅ tab |
| Skills / ruoli riusabili | Claude Code Skills; Copilot custom agents | ✅ `skills.py` | ◐ |
| MCP client+server | tutti | ✅ `mcp.py`, `mcp_client.py`, `mcp_server.py` | ◐ |
| Approvals HITL / permessi | tutti | ✅ `approvals.py` | ✅ |
| Sandbox shell | Cursor sandboxed terminal; Copilot CLI | ✅ `sandbox.py` | ◐ |
| fs.read/write/edit | tutti | ✅ `tools.py` | ◐ |
| Git | Copilot, Claude Code | ◐ no branch/PR/issue-to-PR | ✖ |
| Web search + fetch | Windsurf web search; Claude | ✅ (fetch HTML→testo) | ◐ |
| Memory persistente | Windsurf Memories; Claude memory | ✅ `memory.py` | ◐ |
| Rules globali/progetto | tutti | ✅ `rules.py` | ✅ tab |
| Sessioni | tutti | ✅ | ✅ tab |
| Command palette | VS Code/Cursor | — | ✅ |
| Hooks (lifecycle) | Claude Code hooks | ✅ `hooks.py` | ✖ |
| Checkpoints / rewind | Claude Code, Windsurf, Cursor | ✅ `checkpoints.py` (`rollback`) | ✖ nessuna tab |
| Subagents / parallel agents | Cursor 8 agent; Claude subagents; Windsurf Multi-Cascade | ◐ `subagent.py`,`swarm.py` senza worktree | ✖ |
| Plan mode read-only | Cursor/Windsurf/Claude | ◐ planner JSON | ◐ |
| Browser automation (headless, DOM) | Cursor Browser GA; Windsurf; Antigravity | ✖ solo fetch, disabilitato | ✖ |
| Diff review multi-file inline | tutti | ◐ | ◐ |
| LSP / code intelligence | Cursor, Windsurf, Claude (LSP) | ✖ | ✖ |
| Voice input | Cursor, Windsurf | ✖ | ✖ |
| Inline completion / Tab | Cursor Tab; Windsurf Supercomplete; Copilot | ✖ non è un editor | n/a |
| Background/cloud agent | Copilot coding agent; Devin | ◐ `swarm.py` | ✖ |
| Team-shared rules/commands | Cursor team; Copilot org-level | ✖ single-user | ✖ |
| Cost/usage metering | Claude `/usage`; Copilot | ◐ solo meter contesto | ◐ |
| OTel tracing | (enterprise) | ✅ `otel_tracing.py` | ✖ |
| App mobile | Copilot mobile | ✅ Android | ✅ |

## (b) Top 10 gap prioritizzati (impatto 1-5 · sforzo S/M/L)

| # | Gap | Impatto | Sforzo | Nota |
|---|---|---|---|---|
| 1 | Checkpoints/rewind esposti in WebUI | 5 | S | logica già in `checkpoints.py`, manca bottone |
| 2 | Subagent/parallel visibili + isolamento worktree | 5 | L | `swarm.py` esiste; serve separazione file |
| 3 | Browser automation headless (screenshot/DOM) | 4 | L | oggi solo fetch HTML disabilitato |
| 4 | Diff review multi-file inline nel chat | 4 | M | Cursor/Copilot lo danno per default |
| 5 | Plan mode read-only con approvazione piano | 4 | S | planner esiste, manca modalità lettura |
| 6 | LSP/diagnostica post-edit (auto lint/test) | 3 | L | nessuna code intelligence |
| 7 | Git avanzato: branch + PR + issue-to-PR | 3 | M | tool git c'è, manca workflow |
| 8 | Cost/usage per sessione (token, $) | 3 | S | estende il context meter |
| 9 | Voice I/O (STT/TTS) | 2 | M | feature Cursor/Windsurf |
| 10 | Team-shared rules/commands | 2 | M | oggi single-user |

## (c) Quick wins vs Big rocks

- **Quick wins (sforzo S, alto ROI):** #1 tab Checkpoints, #5 Plan mode read-only, #8 usage/costo,
  esporre `hooks.py` in UI, rifinire tool git e pannello diff. Release piccole, impatto percepito subito.
- **Big rocks (sforzo L):** #2 orchestrazione multi-agent con git-worktree, #3 browser headless,
  #6 LSP/diagnostica. Richiedono nuova infrastruttura ma sono i veri differenziatori 2026.
- **Fuori scope reale:** inline completion/Tab (SparkForge non è un editor) e team/governance enterprise.

## Fonti (primarie)

1. Cursor — Changelog 2.0 (multi-agent, Browser GA, sandboxed terminal): https://cursor.com/changelog/2-0
2. Claude Code 2.x — checkpoints/subagents/hooks: https://www.anthropic.com/news/enabling-claude-code-to-work-more-autonomously
3. Windsurf/Devin Desktop — Cascade, Memories, Workflows, Multi-Cascade: https://docs.windsurf.com/windsurf/cascade/cascade
4. GitHub Copilot — coding agent, custom agents, MCP, custom instructions: https://docs.github.com/en/copilot/using-github-copilot/coding-agent/about-assigning-tasks-to-copilot
