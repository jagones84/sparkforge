# Todos, reminders, and multiple unrelated requests across agent harnesses

Date: 2026-10-04
Scope: how the main agent harnesses handle (1) step-by-step todo
completion reminders/nudges, (2) **multiple UNRELATED user requests in one
session** (open a new task list vs. append to the existing one), and (3) the
priority of the user message vs. harness-injected reminders.
Method: primary sources only where possible — official product docs, official
API/SDK references, and the actual middleware/tool source code. Where only a
faithful community transcription of a leaked system prompt exists, it is marked
as secondary.

> TL;DR
> - **Todo tool vs. no todo tool.** Claude Code, deepagents/LangChain, Cline,
>   and OpenHands ship a first-class todo/plan tool. LangGraph, the OpenAI
>   Agents SDK, and Aider ship **no** built-in todo tool (they give you state,
>   sessions, or plan *modes* instead).
> - **Q2 (unrelated requests) — the dominant pattern is ONE task list per
>   session/thread, and the list is REPLACED wholesale, not appended.** Every
>   harness that has a list encodes "replace the entire list" in the tool
>   contract (`write_todos`, OpenHands `plan`, Claude Code `TodoWrite`→Task
>   tools). Separation of unrelated work is done at the *session/thread* level
>   (`/clear`, a new `thread_id`, a new Cline task), not by opening a second list
>   inside the same session.
> - **Q3 — reminders are almost always framed as SYSTEM context, never as the
>   user.** Claude Code literally tells the model that `<system-reminder>` tags
>   "bear no direct relation to the specific tool results or user messages".
>   Cline's fixed-interval reminder is injected as harness feedback, and the
>   user's edit of the todo file wins.

---

## 1. Claude Code / Claude Agent SDK (Anthropic)

Primary sources: official docs [`agent-sdk/todo-tracking`][cc-todo],
[`tools-reference`][cc-tools]; the leaked Claude Code system prompt via
[`system_prompts_leaks`][cc-prompt] (secondary but faithful transcription).

### Task model
- Two generations of tooling, same concept:
  - **Legacy:** single `TodoWrite` tool (whole-list replacement).
  - **Current:** four Task tools — `TaskCreate`, `TaskGet`, `TaskUpdate`,
    `TaskList` — or `TodoWrite` again when `CLAUDE_CODE_ENABLE_TASKS=0`
    ([cc-todo][cc-todo]).
- **Lifecycle:** `pending → in_progress → completed`, plus deletion via
  `TaskUpdate` with `status: "deleted"` ([cc-todo][cc-todo]).
- **Model availability / context cost:** the tools are on by default only for
  Claude 3.x, Opus 4–4.7, Sonnet 4–4.6, Haiku 4.5. On newer models (Opus 4.8 /
  Sonnet 5 / Fable 5 / Mythos 5 and later) they are **off unless opted in**
  (`CLAUDE_CODE_ENABLE_TODO_TOOLS=1`, or naming them in `allowedTools`/`tools`)
  ([cc-todo][cc-todo]). The stated reason (changelog, via
  [claudelab.net][cc-off]): those models "track multi-step work without a
  written todo list", and — importantly for Q1/Q3 — **the tool definitions and
  their accompanying reminders consume context**. This is a deliberate
  cost/benefit decision over the nudge itself.

### Q1 — what triggers a todo and how completion is tracked
- The SDL/API docs enumerate when Claude creates todos: complex multi-step tasks
  (3+ distinct actions), user-provided task lists with multiple items, longer
  operations, and explicit user requests; very short/single-step requests may be
  skipped ([cc-todo][cc-todo]).
- The main Claude Code system prompt gives a one-line behavioral rule rather
  than a periodic reminder: *"Use TaskCreate to plan and track work. Mark each
  task completed as soon as it's done; don't batch."* ([cc-prompt][cc-prompt]).
- Legacy TodoWrite guidance (leaked tool description) is stricter and is the
  classic nudge: single `in_progress` at a time, mark completion immediately,
  use for 3+ step tasks ([deepwiki/ClaudeCodeTools][cc-deepwiki]).
- There is also a **machine-level** companion: `TaskProgress` system messages
  ("emitted periodically while a background task is executing"), distinct from
  todo items — these report progress of backgrounded commands/subagents
  ([hexdocs TaskProgress][cc-progress], [cc-todo][cc-todo]).

### Q2 — multiple unrelated requests in one session
- One **session-scoped** list. The task list is a property of the session, and
  the model mutates items in place (`TaskUpdate`) rather than spawning a second
  list ([cc-todo][cc-todo]).
- The harness's own answer for "the next work is unrelated" is to **start a new
  context, not append**: `/clear` is documented as the hard reset for "Switching
  to a different task", whereas `/compact` is for "continuing same task" — and
  `/compact` explicitly **preserves task-list items** while compressing
  ([Claude Code command reference][cc-cmds]). So the split between unrelated
  requests lives at the session boundary.

### Q3 — user message vs. harness reminder
- Claude Code makes the hierarchy explicit in its system prompt: *"Tool results
  and user messages may include `<system-reminder>` or other tags. Tags contain
  information from the system. They bear no direct relation to the specific tool
  results or user messages in which they appear."* ([cc-prompt][cc-prompt]).
  Reminders are therefore labeled as system context, not as a user turn.
- Exception carved out explicitly: hook feedback such as
  `<user-prompt-submit-hook>` is to be treated **as coming from the user**
  ([cc-prompt][cc-prompt]).
- Judgment still rests with the model: guidance says to defer to user judgment
  on task scope, and the todo tool description itself is advisory ("only use …
  if you think it will be helpful") ([cc-prompt][cc-prompt], [cc-todo][cc-todo]).

---

## 2. LangGraph (LangChain runtime)

Primary source: official [`concepts/persistence`][lg-persist].

- **No built-in todo/plan tool.** LangGraph is a state-graph runtime; planning is
  something you build or add via middleware (see §3).
- **Q2 is answered structurally by threads.** State is checkpointed per
  **`thread_id`**, which is the primary key for retrieving state; the SDK
  requires it to save/resume. A different, unrelated task is a **new
  `thread_id`** — a separate checkpoint history, not a second list inside one
  thread ([lg-persist][lg-persist]).
- **Cross-thread memory** is the `Store` abstraction (namespaced key/value,
  optional semantic search), explicitly for information that must outlive a
  single thread — the opposite of appending to the same thread
  ([lg-persist][lg-persist]).
- **Q3:** there is no reminder mechanism here; checkpoints enable
  human-in-the-loop interrupts/approvals, so a pause is a first-class control,
  not a nudge ([lg-persist][lg-persist]).

---

## 3. deepagents / LangChain `TodoListMiddleware` (the "Claude Code pattern" in the open)

Primary source: the actual middleware source
[`langchain_v1/.../agents/middleware/todo.py`][dd-src]; supporting docs
[deepagents overview][dd-overview] and [prebuilt middleware][dd-mw].

### Task model
- `TodoListMiddleware` adds a **`write_todos`** tool and a `todos` state slice
  (`PlanningState`); deepagents historically enabled planning by default, now
  documented as an optional middleware ([dd-overview][dd-overview],
  [dd-src][dd-src]).
- `write_todos(todos: list[Todo])` **replaces the entire list** and writes a
  `ToolMessage` ("Updated todo list to …"). Statuses: `pending`, `in_progress`,
  `completed` ([dd-src][dd-src]).
- Parallel-`write_todos` is **structurally forbidden**: an `after_model` hook
  rejects a turn containing more than one `write_todos` call, with the explicit
  rationale that "the tool replaces the entire todo list and parallel calls would
  create ambiguity about precedence" ([dd-src][dd-src]).

### Q1 — reminders/nudges
- Two mechanisms, both *static/structural*, not time-based:
  1. A `WRITE_TODOS_SYSTEM_PROMPT` is **appended to the system message on every
     model call** ("mark todos as completed as soon as you are done … do not
     batch"; unless all tasks are complete, always have at least one
     `in_progress`) ([dd-src][dd-src]).
  2. The tool description carries the same rule set and a strong "when NOT to
     use" list (skip for <3 trivial steps; don't call for simple requests)
     ([dd-src][dd-src]).
- Notably, **parallel `in_progress` is allowed** here ("you can have multiple
  tasks `in_progress` at a time if they are not related to each other and can be
  run in parallel") — the opposite of OpenHands' single-active-task rule
  ([dd-src][dd-src]).
- There is no periodic "remind me every N messages" loop; the persistent system
  prompt is the nudge ([dd-src][dd-src]).

### Q2 — multiple unrelated requests
- Because `write_todos` replaces the whole list, an unrelated request is handled
  by **rewriting the list** (the prompt explicitly blesses revising it: "New
  information may reveal new tasks … or old tasks that are irrelevant")
  ([dd-src][dd-src]).
- Isolation between truly unrelated work is left to the runtime layer: a new
  `thread_id` (LangGraph checkpointer) starts fresh, matching §2
  ([dd-overview][dd-overview], [lg-persist][lg-persist]).

### Q3 — priority
- Harness guidance lives in the **system message**, appended above/around the
  conversation; it is never injected as a user turn ([dd-src][dd-src]). User
  messages and the todo list stay in their own channels.

---

## 4. OpenAI Agents SDK

Primary source: official [`sessions` docs][oa-sessions].

- **No built-in todo, planning, or reminder tool.** The SDK is a minimal
  agent-loop + handoffs + guardrails + sessions + tracing surface; frameworks
  analyses describe it as having "no built-in memory, no graph orchestration"
  beyond sessions ([oa-sessions][oa-sessions], [framework-analysis][oa-analysis]).
- **Q2 is answered by sessions/databases, not by a task list.** A `Session`
  (e.g. `SQLiteSession`, `RedisSession`, `SQLAlchemySession`,
  `OpenAIConversationsSession`) persists conversation history per session ID; a
  new/unrelated conversation is a new session, and `session.clear_session()` /
  `pop_item()` exist to reset or correct history ([oa-sessions][oa-sessions]).
- **Q3 is a first-class API: merging history and the new turn is explicit and
  user-controlled.** `RunConfig.session_input_callback(history, new_input)`
  receives copies of both and returns exactly what the model sees; the SDK still
  persists only the **new** turn's items ([oa-sessions][oa-sessions]). This is
  the cleanest statement in any of the surveyed harnesses that the user's new
  input is not silently outranked by stored memory — you decide the merge.
- If you want todos, you build the tool yourself (the community examples add
  `manageTodo` tools on top) ([Vercel AI SDK tutorial — secondary][oa-tutorial]).

---

## 5. Cline (VS Code / CLI agent)

Primary sources: official [`features/focus-chain`][cl-focus],
[`prompting/understanding-context-management`][cl-ctx], Cline blog
[New Task tool][cl-newtask]; secondary code-read of the prompt pipeline
[cgodwin.io][cl-code].

### Task model — "Focus Chain"
- Automatic todo list stored as an **editable markdown file**; progress shown as
  `3/8` in the task header; markdown checklist with one "← Currently working"
  marker ([cl-focus][cl-focus]).
- Focus Chain is documented as **disabled by default** on the feature page with a
  "Remind Cline Interval (default: 6 messages)" setting ([cl-focus][cl-focus]).
  Note the docs conflict: the context-management page calls Focus Chain "Default:
  ON" ([cl-ctx][cl-ctx]) — treat the default as version/config dependent and the
  **interval = 6 messages** as the stable, citable fact.

### Q1 — reminders/nudges (the most explicit nudge in this survey)
- **Time/message-based reminder loop:** "Remind Cline Interval" (default 6
  messages) is literally "How often Cline updates the todo list" ([cl-focus][cl-focus]).
- An additional reminder fires **on Plan→Act mode switch** ([PostQode mirror of
  the same Focus Chain feature][cl-pq]).
- Secondary code-read: the system prompt is assembled from components and the
  `FEEDBACK` section is rendered **only if focus chain is enabled**, with
  `TASK_PROGRESS` varying by variant — i.e. the reminder is a gated prompt
  section, and tool gating hides `focus_chain` when off ([cl-code][cl-code]).

### Q2 — multiple unrelated requests
- One Focus Chain list **per task**. For unrelated work Cline provides a **"New
  Task" tool**: "Cline can create new tasks using context from the current
  conversation, allowing you to maintain task flow while opening a new context
  window" ([cl-newtask][cl-newtask]).
- Cline also pushes **message checkpoints / restore** to rewind a conversation
  that went off-track, rather than appending corrections (LLMs degrade ~39% when
  instructions are sharded across turns, per their cited research)
  ([Cline blog: message checkpoints][cl-ckpt]).

### Q3 — priority
- The reminder is harness-injected feedback; the **user's edited markdown file
  wins** (Cline "automatically detects your updates" and uses them)
  ([cl-focus][cl-focus]). The todo list is explicitly user-editable, which makes
  user intent override the harness's plan.

---

## 6. Aider

Primary source: official [`usage/modes`][ai-modes].

- **No todo list, no task-tracking tool, no reminder loop.** Aider is a
  file-editing pair-programmer with a repo map and git-native commits
  ([ai-modes][ai-modes]).
- "Planning" exists only as **chat modes**, not as a persistent checklist:
  - `architect` mode: a main "architect" model proposes an approach, then an
    **editor model** turns the proposal into concrete file edits (two LLM
    requests) ([ai-modes][ai-modes]).
  - The recommended flow is to bounce `/ask` (discuss) → `/code` (edit);
    "go ahead" in code mode executes the agreed plan ([ai-modes][ai-modes]).
- **Q2:** unrelated requests are just successive messages; relevant files are
  managed with `/add` (not a task list). There is no session-level list to
  append to or restart — state separation is the git working tree / commits, not
  a todo store ([ai-modes][ai-modes], [DeployHQ guide — secondary][ai-deploy]).
- **Q3:** the user's message is the only driver; the "plan" is a model output
  that a follow-up message replaces.

---

## 7. OpenHands (Software Agent SDK / OpenHands)

Primary source: the actual tool implementation
[`openhands-tools/.../task_tracker/definition.py`][oh-src]; docs
[`getting-started`][oh-gs].

### Task model — `TaskTrackerTool`
- A tool with two commands: `command: "view"` shows the list, `command: "plan"`
  **creates or updates the list**; `plan` takes `task_list: list[TaskItem]` and
  **the full list is required** — i.e. `plan` replaces the whole list
  ([oh-src][oh-src]).
- Statuses: `todo`, `in_progress`, `done`; `TaskTrackerObservation.visualize`
  re-renders the list (with counts and icons) after every call, so the model sees
  the updated list as the tool result ([oh-src][oh-src]).

### Q1 — reminders/nudges (behavioral, not timed)
- The tool description is unusually directive and is the primary mechanism; it is
  a long spec of when to use / not use and how to transition states
  ([oh-src][oh-src]). Key lines:
  - "Work commencement — Update task status to in_progress before beginning
    implementation. **Maintain focus by limiting active work to one task**."
  - "Mark completion immediately upon task finish."
  - "**Limit active work to ONE task at any given time**."
  - Strict completion criteria: never mark done with failing tests, incomplete
    implementation, unresolved errors, or missing resources
    ([oh-src][oh-src]).
- There is **no periodic reminder loop**; the list is re-shown as the observation
  of each tracker call and the guidance is static in the tool description
  ([oh-src][oh-src]).

### Q2 — multiple unrelated requests
- Multiple concurrent requirements is an explicit trigger for the tool: use-case
  #4 is "**Multiple concurrent requirements** — When users present several work
  items that need coordination"; #5 "Project initiation — Capture and organize
  user requirements at project start" ([oh-src][oh-src]).
- Because `plan` replaces the entire list, unrelated work either rewrites the one
  list or lives in a different **Conversation** (the runtime owns the loop and
  may also expose a "Conversation Goals" strategy) ([oh-src][oh-src],
  [OpenHands getting-started][oh-gs]).

### Q3 — priority
- Guidance is in the tool description (system/tool channel); the task list is
  surfaced through tool observations, not user turns. There is a separate
  **critic** and **stuck detector** in the SDK, but they are evaluation
  mechanisms, not user-vs-harness reminders ([oh-src][oh-src]).

---

## 8. Side-by-side answers

### (1) Step-by-step completion reminders/nudges
| Harness | Static guidance | Timed/periodic nudge | Hard enforcement |
|---|---|---|---|
| Claude Code | Yes (main prompt + tool desc) | "accompanying reminders" of the tool set; `TaskProgress` system msgs | Newer models: tools removed entirely; `TaskUpdate` deletes |
| LangGraph | N/A (no todo) | No | Thread/checkpoint state |
| deepagents / LangChain | Yes (`WRITE_TODOS_SYSTEM_PROMPT` every call) | No | `after_model` rejects parallel `write_todos` |
| OpenAI Agents SDK | N/A (no todo) | No | You build the tool |
| Cline Focus Chain | Yes (gated FEEDBACK section) | **Yes — every 6 messages (configurable 1–100)** + on Plan→Act | Progress auto-updated; user-editable list |
| Aider | No todo; `architect` plan mode | No | git commits per change |
| OpenHands | Yes (long tool description) | No | "ONE task in_progress"; strict done criteria |

### (2) Multiple unrelated requests in one session
| Harness | New list or append? | Mechanism |
|---|---|---|
| Claude Code | One session-scoped list; **rewrite** it; new session for unrelated work | `TaskUpdate`/`TodoWrite` replace; `/clear` = "switching to a different task" |
| LangGraph | **New `thread_id`** (separate state) | checkpointer primary key |
| deepagents / LangChain | One list per thread; **rewrite** it | `write_todos` replaces whole list |
| OpenAI Agents SDK | **New session** (or clear/pop) | `Session` history per session id |
| Cline | One Focus Chain **per task**; **New Task** opens a new context window | `new_task` tool |
| Aider | Neither — just more messages on the same files | no task store |
| OpenHands | One list per conversation; `plan` **replaces** it | `task_list` is the full list |

### (3) User-message priority vs. harness reminders
| Harness | Where reminders live | Who wins |
|---|---|---|
| Claude Code | `<system-reminder>` tags, explicitly "from the system … bear no direct relation to [the] user messages"; hooks are the exception (treated as user) | User intent + model judgment; reminders are contextual system info |
| LangGraph | No reminders; interrupts/approvals are control flow | User/human-in-the-loop explicitly |
| deepagents / LangChain | Appended to the system message each call | User messages stay a separate channel |
| OpenAI Agents SDK | No reminders; merge is explicit via `session_input_callback` | Caller decides exactly what the model sees |
| Cline | Gated FEEDBACK prompt section + interval reminder | User's edited markdown todo overrides the plan |
| Aider | None | User message is the sole driver |
| OpenHands | Tool description + tool observations | User requests seed the list; tool output is observation |

---

## 9. What this implies for SparkForge (short)

SparkForge already has a per-session **task graph** (`taskgraph`) with
`write_todos`/`update_todos`/`replan_todos`, a one-`doing` enforcement, and
per-step nudging. Mapped against the above:

1. **Reminders.** SparkForge's per-step nudge is closer to Cline's Focus Chain
   (gated, interval-driven) than to OpenHands (static description only). The
   Claude Code lesson for 2026 is that a reminder is not free: definitions +
   reminders cost context, and strong newer models sometimes do better with no
   written list. Keep the nudge **gated and cheap**, and measure it.
2. **Unrelated requests.** Following the dominant pattern, keep **one task list
   per session** and make the semantics **replace-whole-list** (SparkForge's
   `write_todos` already does). Do **not** silently append a second, unrelated
   list; prefer an explicit "new session" or an explicit replan so the boundary
   is visible — mirroring Claude Code's `/clear` for a different task.
3. **Priority.** Frame nudges as **system context, not user turns**, and say so
   in the prompt (Claude Code's `<system-reminder>` framing). The user's latest
   message and explicit instructions should outrank an injected reminder; harness
   guidance should be advisory unless it is a hard gate (auditor/held-out).

---

## 10. Sources

Primary (official docs / source code):
- [cc-todo] Claude Code docs — "Track todos" (Agent SDK):
  https://code.claude.com/docs/en/agent-sdk/todo-tracking
- [cc-tools] Claude Code docs — Tools reference (task-tool availability):
  https://code.claude.com/docs/en/tools-reference
- [lg-persist] LangGraph docs — Persistence / Threads / Checkpoints:
  https://langchain-ai.github.io/langgraph/concepts/persistence/
- [dd-src] LangChain source — `TodoListMiddleware` / `write_todos`:
  https://github.com/langchain-ai/langchain/blob/master/libs/langchain_v1/langchain/agents/middleware/todo.py
- [dd-overview] Deep Agents overview (planning is optional middleware):
  https://docs.langchain.com/oss/python/deepagents/overview
- [dd-mw] Prebuilt middleware — To-do list:
  https://docs.langchain.com/oss/python/langchain/middleware/built-in
- [oa-sessions] OpenAI Agents SDK — Sessions:
  https://openai.github.io/openai-agents-python/sessions/
- [cl-focus] Cline docs — Focus Chain (Remind interval default 6):
  https://docs.cline.bot/features/focus-chain
- [cl-ctx] Cline docs — Context Management (Focus Chain default ON):
  https://docs.cline.bot/prompting/understanding-context-management
- [cl-newtask] Cline blog — "New Task" tool (3.10):
  https://cline.bot/blog/cline-3-10-local-chrome-integration-yolo-mode-drag-drop-and-more-workflow-enhancements
- [oh-src] OpenHands SDK source — `TaskTrackerTool` definition:
  https://github.com/OpenHands/software-agent-sdk/blob/main/openhands-tools/openhands/tools/task_tracker/definition.py
- [oh-gs] OpenHands docs — Getting started (default tools incl. task tracker):
  https://docs.openhands.dev/sdk/getting-started
- [ai-modes] Aider docs — Chat modes (code/ask/architect/help):
  https://aider.chat/docs/usage/modes.html

Secondary (transcriptions / community code-reads — flagged where used):
- [cc-prompt] Claude Code system prompt (transcription of leaked prompt; source
  for the `<system-reminder>` and "Use TaskCreate to plan and track work" lines):
  https://github.com/asgeirtj/system_prompts_leaks/blob/main/Anthropic/claude-code.md
- [cc-deepwiki] DeepWiki transcription of leaked `ClaudeCodeTools.md`
  (single `in_progress`, immediate completion):
  https://deepwiki.com/LouisShark/chatgpt_system_prompt/3.2-claude-code-system
- [cc-off] "Todo tools off by default" analysis citing the Claude Code changelog
  (tool defs + reminders consume context):
  https://claudelab.net/articles/claude-code/claude-code-todo-tools-off-by-default-progress-ledger
- [cc-cmds] Claude Code command reference (`/clear` vs `/compact`, task list
  preserved on compact):
  https://cloud.tencent.com/developer/article/2648539
- [cc-progress] `TaskProgress` system message shape (hexdocs, Claude CLI):
  https://hexdocs.pm/claude_code/ClaudeCode.Message.SystemMessage.TaskProgress.html
- [cl-code] "How Cline Engineers Context" — prompt section order and Focus Chain
  gating:
  https://www.cgodwin.io/blog/2026-08-07-cline-context-engineering/
- [cl-pq] Focus Chain reminder on Plan→Act (mirror of Cline docs):
  https://docs.postqode.ai/features/focus-chain
- [cl-ckpt] Cline blog — message checkpoints / course-correction research:
  https://cline.bot/blog/how-i-learned-to-stop-course-correcting-and-start-using-message-checkpoints
- [oa-analysis] OpenAI Agents SDK deep-dive (minimal SDK, no built-in planning):
  https://raw.githubusercontent.com/larsderidder/framework-analysis/main/tier-1/openai-agents-sdk.md
- [oa-tutorial] Vercel AI SDK tutorial building a custom `manageTodo` tool on top
  of the SDK (illustrates "you build it yourself"):
  https://www.fastcoding.dev/blog/build-ai-agent-nextjs-vercel-ai-sdk-tutorial
- [ai-deploy] DeployHQ Aider guide (git-native atomic commits, architect mode):
  https://www.deployhq.com/guides/aider
