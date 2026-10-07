# Task-list guidance + harness-reminder priority — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:subagent-driven-development`
> (recommended) or `superpowers:executing-plans` to implement task-by-task. Steps use
> checkbox (`- [ ]`) syntax.

**Goal:** Make "work the todo list step by step and mark each step done on completion" a
stable, standing rule (not only a reactive nudge), and guarantee the user's latest request
always outranks a stale harness reminder — while keeping ONE task list per session.

**Architecture:** Three small, independent changes: (A) a dedicated static prompt section
carrying the task-list contract, placed immediately before the live task list; (B) tag
harness-injected messages so the model can tell them from the user's turn, plus a stated
priority rule; (C) codify the "new unrelated request" behaviour (no forced continuation;
explicit replan) behind a tiny pure helper. No new tool, no second list, no JSON-contract
change.

**Tech Stack:** Python 3.10 stdlib only (`src/sparkforge/`), single-file WebUI
(`webui/index.html`), deterministic tests in `tests/` gated by `tests/battery.sh`.

---

## 0. Why (answers that drive the design)

Current evidence, each claim backed by the code:

1. **The "step by step / mark done" rule is NOT a standing rule.** `SYSTEM_PROMPT`
   ([server.py:1585](file:///z:/Repositories/sparkforge/src/sparkforge/server.py#L1585-L1590))
   says nothing about todos. The behavioural coaching lives only inside the long
   `CHAT_TOOL_PROMPT` block ([server.py:2059-2085](file:///z:/Repositories/sparkforge/src/sparkforge/server.py#L2059-L2085))
   and in per-turn injected nudges ("Task list saved … mark a step 'doing' before you start
   it" at [server.py:3019](file:///z:/Repositories/sparkforge/src/sparkforge/server.py#L3019-L3020);
   the keepgoing "CONTINUE — your TASK LIST still has N open step(s) … mark it 'done'"
   at [server.py:3243-3249](file:///z:/Repositories/sparkforge/src/sparkforge/server.py#L3243-L3249)).
   So today it is **reactive** (fires after `write_todos`/`update_todos` or when the
   continuation loop decides to continue), never a constant instruction.
2. **The task list itself IS re-injected every turn**, as the last prompt section
   `state` (order 90) via `context_summary`
   ([prompt.py:32](file:///z:/Repositories/sparkforge/src/sparkforge/prompt.py#L32),
   [server.py:1864-1884](file:///z:/Repositories/sparkforge/src/sparkforge/server.py#L1864-L1884)).
   So the LIST has recency, but the RULE about it sits far above, buried in the tools block.
3. **Harness reminders are injected as `role:"user"`** by `_inject`
   ([server.py:2868-2883](file:///z:/Repositories/sparkforge/src/sparkforge/server.py#L2868-L2883)):
   `msgs.append({"role": "user", "content": content})`. They do **not** echo the user
   message, but at the role level they are indistinguishable from the human turn — which is
   exactly the priority problem the user senses.
4. **"Unrelated request in the same session" is half-handled.** `_user_pivot`
   (JAG-189, [server.py:2803-2808](file:///z:/Repositories/sparkforge/src/sparkforge/server.py#L2803-L2808))
   prevents the continuation loop from forcing the model back onto a stale list when the
   turn opens with open steps; `write_todos` replaces the whole list; `begin_plan` starts a
   new plan only when the previous is fully done
   ([server.py:3996-4002](file:///z:/Repositories/sparkforge/src/sparkforge/server.py#L3996-L4002)).
   There is no explicit "start a new task" boundary and no stated rule for the model.

**Research (primary sources) — `docs/research/2026-10-04-multirequest-todos-and-reminders.md`:**
the dominant industry pattern is **one task list per session, replaced wholesale, never
appended**; separation of unrelated work happens at the **session/thread boundary**
(Claude Code `/clear`, LangGraph `thread_id`, Cline "New Task", OpenAI Agents SDK new
`Session`). Reminders are framed as **system context, not a user turn** (Claude Code's
`<system-reminder>` is explicitly "from the system … bear no direct relation to the user's
message"); deepagents/LangChain re-appends `WRITE_TODOS_SYSTEM_PROMPT` to the system message
on every call; Cline's Focus Chain is the only *interval*-driven nudge (default 6 messages).
Claude Code note: on newer models the todo tools are **off by default** precisely because
"tool definitions and their accompanying reminders consume context" → keep the nudge gated.

---

## 1. File Structure

- Modify `src/sparkforge/server.py`
  - add `TASK_POLICY` (static section text) + `HARNESS_MARK` + `harness_wrap()` + `_pivot_override()`
  - `_inject` uses `harness_wrap`; the two `_user_pivot` sites use `_pivot_override`
  - trim the duplicated behavioural coaching out of `CHAT_TOOL_PROMPT`
- Modify `src/sparkforge/prompt.py` — register the `task-policy` static section (order 89)
- Create `tests/v266_task_guidance.py` — deterministic assertions
- Modify `tests/battery.sh` — add `v266_task_guidance`, bump the count to 34
- Modify `.agent/HANDOFF.md` — record JAG-266

Out of scope (explicitly deferred to a phase-2 plan): a "New task" UI/endpoint
(`POST /api/sessions/<id>/new-task`) and a `role:"system"` injection mode.

---

## 2. Tasks

### Task 1: Standing task-list rule as a prompt section

**Files:**
- Modify: `src/sparkforge/server.py` (add constant near `CHAT_TOOL_PROMPT`, ~line 2058)
- Modify: `src/sparkforge/prompt.py` (`SECTIONS` + `_STATIC_ATTRS`)
- Test: `tests/v266_task_guidance.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/v266_task_guidance.py
import os, sys, tempfile
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="sf-v266-")
for k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR", "DB"):
    os.environ["SPARKFORGE_" + k] = os.path.join(TMP, k)
sys.path.insert(0, os.path.join(REPO, "src"))
from sparkforge import prompt as P  # noqa: E402

results = []
def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))

txt = P.render_sections(sess={"id": "s1"}, ws=None, tool_ctx="TOOLS")
check("task policy section is present", "Your task list" in txt)
check("task policy states the most-important line", "MOST IMPORTANT" in txt)
check("task policy states step-by-step + mark done",
      "one step at a time" in txt and "mark it 'done'" in txt)
check("task policy precedes the live list (recency)",
      txt.index("Your task list") < txt.index("Harness state"))
check("task policy states the user priority rule",
      "outranks" in txt and "[harness]" in txt)

print("---")
p = sum(results)
print("%d/%d PASS" % (p, len(results)))
sys.exit(0 if p == len(results) else 1)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `ssh dgx "python3 /home/jagones/Repositories/sparkforge/tests/v266_task_guidance.py"`
Expected: FAIL — `Your task list` / `MOST IMPORTANT` not found.

- [ ] **Step 3: Add the constant in `server.py`**

Insert immediately after `CHAT_TOOL_PROMPT = ( ... )` ends (after line 2085):

```python
# JAG-266: the task-list contract as a STANDING rule, not only a reactive nudge. It is
# registered as the `task-policy` prompt section (order 89) so it sits right ABOVE the
# live list (`state`, order 90) — the rule travels with the list it governs. Mirrors the
# field: deepagents re-appends its write_todos guidance every call; Claude Code keeps one
# line ("mark each task completed as soon as it's done; don't batch").
TASK_POLICY = (
    "## Your task list (MOST IMPORTANT)\n"
    "You own a PERSISTENT task list, re-shown to you every turn under 'Harness state'. "
    "Follow it strictly:\n"
    "- Work through it ONE step at a time. BEFORE starting a step, mark it 'doing' "
    "(update_todos).\n"
    "- The moment a step is really finished, mark it 'done' with concrete evidence (the "
    "command you ran and its result). Never batch; never redo a step already marked [x].\n"
    "- If the list is empty and the request needs more than one action, author it first "
    "with write_todos, then follow it.\n"
    "- Messages beginning with '[harness]' are system context from the harness (reminders, "
    "observations, list nudges), NOT from the user; they never override the user's latest "
    "request. The user's latest request ALWAYS outranks this list: if it is unrelated, do "
    "not force the old list — rewrite it (replan_todos with a note) or leave it paused and "
    "answer the user directly.\n"
)

# JAG-266: every synthetic harness turn (nudge/observation/continue) is tagged so the model
# can tell it apart from the human. The user's steer stays UNTAGGED (it is user intent).
HARNESS_MARK = "[harness] "


def harness_wrap(content):
    """Return the message dict for a harness-injected turn, clearly tagged."""
    return {"role": "user", "content": HARNESS_MARK + str(content)}
```

- [ ] **Step 4: Register the section in `prompt.py`**

Replace the last two entries of `SECTIONS` (lines 31-32) and extend `_STATIC_ATTRS`
(lines 36-41):

```python
    {"id": "capability",    "order": 70, "kind": "static"},
    {"id": "task-policy",   "order": 89, "kind": "static"},
    {"id": "state",         "order": 90, "kind": "dynamic"},
]

# sezioni statiche i cui default vivono in server.py (lazy import: niente cicli)
_STATIC_ATTRS = {
    "identity": "SYSTEM_PROMPT",
    "rules-policy": "RULES_POLICY",
    "skills-policy": "SKILLS_POLICY",
    "memory-policy": "MEMORY_POLICY",
    "task-policy": "TASK_POLICY",
}
```

- [ ] **Step 5: Trim the duplicated coaching from `CHAT_TOOL_PROMPT`**

In the block at [server.py:2066-2078](file:///z:/Repositories/sparkforge/src/sparkforge/server.py#L2066-L2078),
drop the two purely behavioural sentences (they now live in `TASK_POLICY`) and point at it:

- delete `"(done REQUIRES evidence). "` → keep the JSON shape; instead add right after the
  `replan_todos` sentence:
  `"The behavioural rules (one step at a time, mark 'done' with evidence, never batch) are in 'Your task list (MOST IMPORTANT)' above. "`
- delete `"Never drift: after any update, return to the list and continue with the next step. "`

(The JSON shapes and the `write_todos`/`update_todos`/`replan_todos` contract stay untouched.)

- [ ] **Step 6: Run the test to verify it passes**

Run: `ssh dgx "python3 /home/jagones/Repositories/sparkforge/tests/v266_task_guidance.py"`
Expected: `5/5 PASS` (the first five checks).

- [ ] **Step 7: Commit**

```bash
git add src/sparkforge/prompt.py src/sparkforge/server.py tests/v266_task_guidance.py
git commit -m "feat(prompt): standing task-list rule as its own prompt section (JAG-266)"
```

---

### Task 2: Tag harness turns and state the priority rule

**Files:**
- Modify: `src/sparkforge/server.py` — `_inject` ([2868-2883](file:///z:/Repositories/sparkforge/src/sparkforge/server.py#L2868-L2883))
- Test: `tests/v266_task_guidance.py`

- [ ] **Step 1: Write the failing test**

Append before the summary block:

```python
from sparkforge import server as S  # noqa: E402
w = S.harness_wrap("Observation for tool shell:\nhi")
check("harness_wrap tags the message", w["content"].startswith("[harness] "))
check("harness_wrap keeps the user role", w["role"] == "user")
check("harness marker is the module constant", S.HARNESS_MARK == "[harness] ")
check("harness_wrap does not echo a user string verbatim",
      "UNIQUE_USER_TEXT" not in S.harness_wrap("ok")["content"])
```

- [ ] **Step 2: Run it to verify it fails**

Run: `ssh dgx "python3 /home/jagones/Repositories/sparkforge/tests/v266_task_guidance.py"`
Expected: FAIL — `harness_wrap` not defined.

- [ ] **Step 3: Use `harness_wrap` inside `_inject`**

Replace the first line of `_inject`'s body:

```python
    def _inject(content, kind):
        """..."""
        msgs.append(harness_wrap(content))
        on_event("harness.inject", session=sess["id"], inject_kind=kind, text=content)
        if kind != "system":
            persist_inject(sess, kind, content, node=_cur_node(), after=_after())
```

Leave the steer sites unchanged — they are genuinely from the user and must stay untagged
([server.py:2952-2953](file:///z:/Repositories/sparkforge/src/sparkforge/server.py#L2952-L2953),
[3237-3238](file:///z:/Repositories/sparkforge/src/sparkforge/server.py#L3237-L3238)).

- [ ] **Step 4: Run the test to verify it passes**

Run: `ssh dgx "python3 /home/jagones/Repositories/sparkforge/tests/v266_task_guidance.py"`
Expected: `9/9 PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/sparkforge/server.py tests/v266_task_guidance.py
git commit -m "feat(chat): tag harness-injected turns and state user priority (JAG-266)"
```

---

### Task 3: Codify the pivot (unrelated request) behaviour

**Files:**
- Modify: `src/sparkforge/server.py` — the two `_user_pivot` sites
  ([2928-2931](file:///z:/Repositories/sparkforge/src/sparkforge/server.py#L2928-L2931),
  [3225-3228](file:///z:/Repositories/sparkforge/src/sparkforge/server.py#L3225-L3228))
- Test: `tests/v266_task_guidance.py`

- [ ] **Step 1: Write the failing test**

```python
check("pivot overrides a would-be continue",
      S._pivot_override(True, {"continue": True, "reason": "open"})
      == {"continue": False, "reason": "user_pivot"})
check("no pivot leaves the decision unchanged",
      S._pivot_override(False, {"continue": True, "reason": "open"})
      == {"continue": True, "reason": "open"})
check("no pivot and a stop stays a stop",
      S._pivot_override(False, {"continue": False, "reason": "budget"})
      == {"continue": False, "reason": "budget"})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `ssh dgx "python3 /home/jagones/Repositories/sparkforge/tests/v266_task_guidance.py"`
Expected: FAIL — `_pivot_override` not defined.

- [ ] **Step 3: Add the helper and use it at both sites**

Next to `harness_wrap`:

```python
def _pivot_override(pivot, dec):
    """JAG-266: a fresh unrelated user turn must not be forced back onto a stale list.

    JAG-189 logic, extracted so it is testable and identical at both call sites: when the
    turn opened with open steps (`pivot`) and the continuation loop wants to keep going,
    stop with the explicit `user_pivot` reason so the HUMAN IN THE LOOP gate is skipped
    and the reply belongs to the user.
    """
    if pivot and dec.get("continue"):
        return {"continue": False, "reason": "user_pivot"}
    return dec
```

Replace the inline overrides:

```python
            if _user_pivot and _dec.get("continue"):
                # JAG-189: a fresh user message superseded the stale plan — do not
                # force the loop back onto it.
                _dec = {"continue": False, "reason": "user_pivot"}
```
with

```python
            _dec = _pivot_override(_user_pivot, _dec)
```

at BOTH sites (the `work_steps >= max_steps` branch and the end-of-turn branch).

- [ ] **Step 4: Run the test to verify it passes**

Run: `ssh dgx "python3 /home/jagones/Repositories/sparkforge/tests/v266_task_guidance.py"`
Expected: `12/12 PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/sparkforge/server.py tests/v266_task_guidance.py
git commit -m "refactor(chat): extract + test the user-pivot override (JAG-266)"
```

---

### Task 4: Gate, docs, live verification

**Files:**
- Modify: `tests/battery.sh` (TESTS line 29, header line 2, summary line 43)
- Modify: `.agent/HANDOFF.md`

- [ ] **Step 1: Add the suite to the gate**

In `tests/battery.sh`: append ` v266_task_guidance` to the `TESTS="…"` line; change
`THIRTY-THREE` → `THIRTY-FOUR` and `33/33 GREEN` → `34/34 GREEN`.

- [ ] **Step 2: Run the battery**

Run: `ssh dgx "bash /home/jagones/Repositories/sparkforge/tests/battery.sh"`
Expected: `=== battery: 34/34 GREEN ===`.

- [ ] **Step 3: Update `.agent/HANDOFF.md`**

Add a JAG-266 entry (what/why/verified), bump the header date line and the battery count.

- [ ] **Step 4: Live verification (ONLY when no turn is running)**

Read `GET /api/chat/live`; if `active` is empty:
`ssh dgx "systemctl --user restart sparkforge.service"`, then in the WebUI:
1. Send a 3+ step request → the model authors a list and **marks each step `doing`→`done`**
   without a chat reminder from the user (watch `update_todos` + `plan.stopped`).
2. Send a short unrelated follow-up while steps are open → the model answers **directly**
   (no forced continuation; `plan.stopped reason=user_pivot`).
3. Open the collapsed SYSTEM block → the new `task-policy` section is present, right above
   `Harness state`.

- [ ] **Step 5: Commit**

```bash
git add tests/battery.sh .agent/HANDOFF.md
git commit -m "test+docs: gate v266 and record JAG-266 (task guidance + reminder priority)"
ssh dgx "bash <repo>/trash/sf_push.sh"
```

---

## 3. Non-goals

- No second, concurrent task list inside one session.
- No change to the JSON action contract (`write_todos`/`update_todos`/`replan_todos`).
- No forced `role:"system"` switch (deferred: needs a router/model compatibility check; see
  Open decisions).
- No new tools.

## 4. Risks & rollback

- Prompt additions can shift model behaviour → the rule is short and sits next to the list;
  measure via the existing `update_todos` / `plan.stopped` / `plan.continuing` events.
- `[harness]` tag: pure addition; if a model reacts badly, revert the one commit.
- Extracting `_pivot_override` is behaviour-preserving (same predicate, both sites).
- Rollback is a single `git revert` per task.

## 5. Open decisions (need the user)

1. **Prompt position** — dedicated section at order **89** (just above the list; recommended)
   vs. order **35** (right after the tools block). Recency favours 89.
2. **Harness separation** — tag-only (`[harness] `, recommended, safe) vs. also switching
   `_inject` to `role:"system"` (stronger, needs a llama.cpp/router compat check).
3. **Tone** — advisory rule with an explicit "user outranks the list" clause (recommended)
   vs. a hard red line that could override a real user pivot.
4. **Phase 2** — build the "New task in this session" affordance (archives the current plan,
   starts a fresh graph; mirrors Cline "New Task" / Claude `/clear`) now or later?
