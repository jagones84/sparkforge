# Design — Orbit simplified (JAG-293)

Status: approved (user: "togli tutto, tabella agenti + organigramma + job").
Supersedes the **UI** section of `design-agents-jobs.md`.

## Goal

The Orbit deck had 11 panels (Board, Tactical graph, New job, Command, Team models,
Jobs, Org chart, Routines, Decision queue, Model Bay, Feed). Too dispersive. Reduce
it to the essentials: **the agents, who reports to whom, and the jobs**.

## Page (single column, dense)

1. **Agents** — a table. `＋ new agent` creates a session + designates it.
   Columns: `ID (Ax)` · `Name` · `Role` · **`Model`** (dropdown from all providers) ·
   **`Reports to`** (dropdown of agents) · `Brief` (✎ opens an inline editor) · `×`.
   A dot marks a running agent. Model + org relations live ONLY here.
2. **Org chart** — a graphical tree of boxes + connector lines generated from
   `reports_to` (root on top, reports below). Clicking a box highlights the agent.
3. **Job** — `goal` + `assign to` (dropdown; usually the coordinator). The **team is
   the assignee plus its direct reports** in the org chart (no manual roster).
   List shows `Jn` · status · `coordinator ⇢ team` · ▶ run.
4. **Routines** (kept) and **Feed** (kept, bottom).

**Removed:** Board, Tactical Task Graph, Command, Team models, Model Bay, Decision queue.

## Per-agent brief (system prompt + formal rules)

Each agent carries `prompt` (system prompt) and `rules` (formal info-exchange rules),
edited inline in the table. `AgentRegistry.brief(rec)` combines `role` + `prompt` +
`rules`; `JobRegistry._run_agent` **prepends it** to every turn, so in a job the
coordinator and the workers exchange info the same way. Routines share that path.

## API deltas (additive)

- `POST /api/agents` now accepts `prompt`, `rules`.
- `POST /api/jobs` accepts `assignee`: `agents = team_of(assignee)`,
  `coordinator = assignee` (org-chart-derived team).
- `AgentRegistry.team_of(ref)` = the agent + its direct reports.

## Testing

`tests/v291_orbit_simple.py`: prompt/rules stored + `brief()`; `team_of`; API
`assignee` derivation; the brief prepended to a stubbed turn; the simplified UI
markup; every `$("id")` used by the JS exists in the markup. Battery stays green.
