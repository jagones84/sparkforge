# Longrun documentation

Two kinds of documents live here: **canonical** (kept current — read these) and the
**historical record** (dated design notes and session evidence — kept for provenance,
under `archive/`, and not maintained).

## Canonical

| Doc | Read it for |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | how the harness is wired (components, data stores, the object model, the turn/job lifecycle). |
| [CLI.md](CLI.md) | every CLI command and HTTP endpoint. |
| [TESTING-PLAYBOOK.md](TESTING-PLAYBOOK.md) | how to hunt real bugs in the running system (the live seams to probe). |
| [RESEARCH-frontier-harnesses-2026.md](RESEARCH-frontier-harnesses-2026.md) | the research base and where Longrun sits vs. the 2026 frontier. |
| [diagrams/](diagrams/) | the generated architecture diagram (HTML + JSON source). |

Also at the repo root: [README.md](../README.md) (the pitch), [AGENTS.md](../AGENTS.md)
(orientation for an AI agent landing here), [CONTRIBUTING.md](../CONTRIBUTING.md),
[CHANGELOG.md](../CHANGELOG.md).

## Historical record — `archive/` (do not treat as current)

Dated, append-only records. They captured the design and evidence *at the time* and are
**not** updated when the code moves on — the code is the source of truth.

| Path | What |
|---|---|
| [archive/specs/](archive/specs/) | dated design specs (`YYYY-MM-DD-<topic>-design.md`). |
| [archive/plans/](archive/plans/) | dated implementation plans / checklists. |
| [archive/research/](archive/research/) | dated research notes and surveys. |
| [archive/evidence/](archive/evidence/) | raw command + output evidence for past acceptance runs (`V0x-EVIDENCE.md`). |
| [archive/PLAN.md](archive/PLAN.md) | the roadmap as of v0.7.x. |
| [archive/WAYFORWARD_minor.md](archive/WAYFORWARD_minor.md) | dated forward-looking notes. |

> The maintainer's session working notes (what was just done, dead paths to avoid, the
> debugging manual) live in a **local, untracked** `.agent/` folder — they are not part of
> a clone. Read [AGENTS.md](../AGENTS.md) first for the read order.
