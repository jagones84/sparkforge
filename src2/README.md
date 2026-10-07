# src2 — Orbit beta (detachable)

`src2/` holds **Orbit**, a beta command deck for SparkForge. It lives *outside* the
application (`src/`) on purpose: the app only reaches it through two guarded hooks in
`sparkforge.server`, so the whole folder can be **deleted at any time without touching
the app**.

## Layout (object-oriented, one concern per class)

```
src2/orbit_beta/
  __init__.py      exports serve_page() + handle()
  bay.py           ModelBay         — the FULL provider/model catalogue
  registry.py      SessionRegistry  — roster + pre-provisioning ("hire ahead")
  orchestrator.py  Orchestrator     — dispatch a goal to many sessions, background
  attention.py     AttentionFeed    — "what needs me" inbox (Paperclip-style)
  api.py           HTTP surface (/api/orbit/*)
  web/orbit.html   the single-file UI (vanilla JS classes)
```

## Why it exists

The stock `/console` deck had limits the user hit:

* its **Model Bay** was fed from `/api/status.models` = the DGX router roster only,
  so every cloud/other-local provider was invisible;
* it was **single-session** and could not orchestrate several sessions;
* it could not **create sessions ahead of time**.

Orbit fixes all three, and stays out of the app's way.

## Routes

| Method | Path | Purpose |
|---|---|---|
| GET  | `/orbit` | the UI shell (public, like `/console`) |
| GET  | `/api/orbit/models` | every provider + model, with context window |
| GET  | `/api/orbit/sessions` | roster with a live `running` flag |
| POST | `/api/orbit/sessions` | pre-create a session (title / model / workspace) |
| POST | `/api/orbit/dispatch` | run a goal on one or many sessions, in the background |
| GET  | `/api/orbit/jobs` | dispatched jobs + their state |
| GET  | `/api/orbit/attention` | "what needs me" inbox + the board grouping |

The Tactical Task Graph / Org chart / Jobs board also read the NATIVE orchestration
API (`GET /api/agents/tree`, `GET /api/jobs`, and `GET /api/sessions/<id>/graph`);
see `.agent/design-agents-jobs.md` for the Agents & Jobs model.

## Inspired by Paperclip

The board + attention surfaces mirror [Paperclip](https://paperclip.ing) (the
open-source "company of agents" app): work is grouped into a board, and everything
that needs a human is funnelled into one ranked inbox. Paperclip types its inbox by
*source* and ranks by *severity*; Orbit does the same with the primitives SparkForge
already has — `approval` (HITL gate), `failed_run`, `blocked_session` (open steps)
and `budget_alert` (context window nearly full). Approvals are resolved inline via
the existing `POST /api/approvals/:id`.

## How to detach

Delete the folder (or just `git rm -r src2`) and restart the service. The two hooks in
`server.py` (`_orbit_page`, `_orbit_handle`) call `_orbit_module()`, which returns `None`
when `src2/` or `orbit_beta` is missing, wrapped in a swallowing `try/except`. Nothing
else in the app references Orbit.
