# TEAMS — a new top-level object (design)

Status: approved (decisions locked with the operator, 2026-10-06).
Issues: JAG-338 (master autonomy, item 1), JAG-339 (TEAMS level, items 4+5).

## Goal

Add one more level above Agent. Today the object model is
Job → Subjob → Agent → Todo. A **Team** (`T1`, `T2`, …) is a real, named group of
agents with a symbol, a colour and an organigram. Teams are first-class code — not a
display label — because the roadmap runs several teams in parallel.

## Decisions (locked)

- Team id format: `T1`, `T2`, `T3` (short, real ids).
- Membership: **multiple teams now** — `agent.teams = ["T1", "T2"]`. An agent can sit
  in several teams at once.
- Chat todo naming: rename the DISPLAYED todo id from `AX.TY` to `AX.nY`
  (e.g. `A8.T2` → `A8.n2`). The letter `T` is now the TEAM namespace; node ids were
  already `n1`, `n2` (`taskgraph._next_id`), so this is a display + docs fix only.
- Master autonomy (item 1): the coordinator MAY use tools and skills and author its
  own plan (todos). It is still forbidden to spawn subagents.

## Object model (five levels)

| Object | id | Meaning | Store |
|--------|----|---------|-------|
| **Team** | `TN` | a named group of agents, with symbol + colour + organigram | `data/teams.json` |
| **Job** | `JN` | a goal that orchestrates several agents | `data/jobs.json` |
| **Subjob** | `JN.j[.x…]` | one tracked piece bound to ONE agent | inside the job |
| **Agent** | `AX` | a session with harness powers; `agent.teams` = many `TN` | `data/agents.json` |
| **Todo** | `AX.nY` | a plan step (graph node `nY`) | session graph |

An agent with no team is an ad-hoc session (shown with no team chip).

## Data model

`data/teams.json` = `{"teams": {id: {...}}, "seq": N}`.

Team record:
```
{ "id": "T1", "n": 1, "name": "Startup MVP",
  "symbol": "🚀", "color": "#3B82F6", "description": "…",
  "members": ["A3", "A4", "A5"], "created": 1234.5 }
```

`members` is the single source of truth (agent ids). `agents.py` reads it to expose
`agent["teams"]` — it never writes membership itself, so the two stores cannot drift.

## API (orchestration.py)

- `GET  /api/teams`            → `{teams:[…], count}`; each team enriched with its
                                 members' `{id,name,session}`.
- `POST /api/teams`            → create `{name, symbol, color, description}`.
- `GET  /api/teams/<id>`       → team detail + member agent records.
- `POST /api/teams/<id>`       → update `{name, symbol, color, description}`.
- `DELETE /api/teams/<id>`     → delete (members are untouched, just drop the link).
- `POST /api/teams/<id>/members` → `{session|agent, action:"add"|"remove"}`.
- `GET  /api/agents` and `/api/agents/tree` gain each agent's `teams` list.

## UI

### Orbit (`src2/orbit_beta/web/orbit.html`)
- A **team selector** in the header: `ALL` + one option per team (symbol + name).
- The selected team **scopes everything**: the Agents table, the Org chart, the
  Constellation and the Job list show only that team's agents/jobs. `ALL` = today's
  behaviour.
- `/api/orbit/constellation?team=TN` filters server-side.

### Main app (`webui/index.html`)
- Every session row shows its team chip(s) (`symbol`) when the session is an agent
  that belongs to a team. Ad-hoc sessions show nothing new.
- The chat todo id renders `AX.nY` (was `AX.TY`).

## Seeding from agency-agents

`scripts/seed_teams.py` reads the local clone of **agency-agents**
(`strategy/runbooks.json` + each agent `.md` frontmatter: `name`, `description`,
`emoji`, `color`) and creates 3 diversified teams, each with a real organigram:

```
orchestrator (root)
├── group lead 1 ── specialists…
├── group lead 2 ── specialists…
└── group lead 3 ── specialists…
```

Groups come from the runbook's `roster[].group`; `reports_to` builds the organigram.
The script is idempotent (re-running updates the same teams/agents) and takes the
agency path from `SPARKFORGE_AGENCY_DIR` (default `~/Repositories/agency-agents`).
Teams seeded: `startup-mvp`, `marketing-campaign`, `incident-response`.

## Testing

- `v338_master_autonomy.py` — the coordinator prompt allows tools/skills + own plan,
  still forbids subagents; the harness plan seed remains a fallback.
- `v339_teams.py` — TeamRegistry CRUD, multi-team membership, `teams_of`,
  `/api/teams` routing, agent `teams` enrichment.
- `v340_team_scope.py` — constellation/agent filtering by team + the `AX.nY` todo id.
- `v341_team_seed.py` — the seeder produces 3 teams with an organigram, deterministic
  and idempotent (synthetic agency fixture, no network).

## Non-goals

- No nested-team hierarchy (teams are flat).
- No team-level budgets/scheduling in this pass.
- No removal of the existing single-agent/multi-agent job paths.
