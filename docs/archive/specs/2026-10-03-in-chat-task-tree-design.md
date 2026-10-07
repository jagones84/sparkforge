# In-chat task tree + visible harness→LLM injections — design

Date: 2026-10-03 · Status: approved · Depends on: keepgoing (JAG-129A/164), taskgraph

## Problem
1. The chat hides the harness's own work: the system prompt and every synthetic
   `user` message injected between model calls (todo nudges, tool observations,
   "CONTINUA…", retries, forced-final) are invisible (see `server.py` `chat_once`).
2. The persistent todo graph lives only in the side panel (`taskTree`), not in the
   chat: you cannot see, per todo node, what happened under it.

## Research
`docs/research/2026-10-03-in-chat-task-tree-ux.md` (4 primary sources). Common
pattern: live task list updated in place + progressive disclosure (collapsible
per-step blocks). No primary source documents showing injected/system messages →
that is our deliberate differentiator.

## Design (v1)
### A. Backend — emit what we inject (`server.py` `chat_once`)
- New helper `_inject(role, text, kind)` = `msgs.append({role,content})` **plus**
  `on_event("harness.inject", session=…, kind=…, text=…)`.
- Replace every synthetic `msgs.append({"role":"user", …})` with `_inject("user",
  text, kind)`; kinds: `nudge | observation | continue | retry | final | steer`.
- Emit the assembled system prompt once per turn: `kind="system"`.
- Assistant echoes of the model's own answer stay silent (already shown).
- Event is additive; the WebUI that ignores it is unaffected.

### B. Frontend — the tree in chat (`webui/index.html`)
- `activeScope`: when a todo node is `doing`, its activity container becomes the
  append target; `_logAppend(el)` appends to `activeScope` else `#log`.
- On `graph.node.added`: create `<details class="tctree" data-id>` (header =
  status + label), indented by parent depth; store its `.tc-kids` container.
- On `graph.node.updated`: refresh the header status; on `doing` → auto-open +
  set active; on `done` → collapse and clear active.
- `who` / `toolCard` / `ensureThink` / `improveCard` append via `_logAppend`, so
  tool cards, thoughts and injections nest under the active node.
- `harness.inject`: render a collapsible `harness → LLM` block (`kind` badge,
  monospace body) inside the active node (or top-level if none). The `system`
  kind renders once, collapsed, at the top of the turn.
- Reset `activeScope=null` in `send()` / `endStream()`.

## Non-goals (v1)
- No new persistence; the tree is rebuilt from the same events already emitted.
- No change to the side-panel `taskTree`.

## Acceptance
- In a scripted turn, the injected nudge/observation/`CONTINUA` texts appear in
  chat as `harness → LLM` blocks nested under the running todo.
- Todo nodes render in chat, auto-expand while `doing`, collapse when `done`.
- No regressions in v151/v157/v158; `harness.inject` observed in the SSE stream.
