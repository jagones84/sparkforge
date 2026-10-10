#!/usr/bin/env python3
"""v304 — the harness accepts the model's own JSON ARTIFACT as an answer (JAG-304).

Observed live on J2: the coordinator (A3) delivered a legitimate JSON artifact —
a Book JSON-Schema and a list-response envelope — as its plain-text answer. The
chat loop rejected ANY parsed JSON object as a stray action ("That was not a
valid action"), forcing retries and risking a `no_valid_action` halt at four in
a row. Locked here:
  * `_looks_like_action_dict` is False for artifacts (schema / envelope / record);
  * it is True for real action attempts (action / tool / args / todos / steps /
    a bare tool-arg key), so those still get the retry nudge;
  * the chat loop surfaces a keyless dict as the final answer and exempts it from
    the tail JSON guard.

Deterministic, no live model. Run: python3 tests/v304_json_artifact.py
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


from sparkforge.server import _looks_like_action_dict  # noqa: E402

# --- artifacts the model means as its ANSWER: must NOT be treated as actions ---
BOOK_SCHEMA = json.loads(
    '{"$schema": "https://json-schema.org/draft/2020-12/schema", "title": "Book", '
    '"type": "object", "additionalProperties": false, "required": ["id", "title"], '
    '"properties": {"id": {"type": "string"}, "title": {"type": "string"}}}')
ENVELOPE = {"items": [], "pagination": {"page": 1, "limit": 25, "total": 0},
            "links": {"self": "/v1/books?page=1&limit=25", "next": None, "prev": None}}
RECORD = {"id": "b1", "title": "Dune", "author": "Herbert", "readingStatus": "read"}

check("a JSON-Schema artifact is not an action", _looks_like_action_dict(BOOK_SCHEMA) is False)
check("a list-response envelope is not an action", _looks_like_action_dict(ENVELOPE) is False)
check("a data record is not an action", _looks_like_action_dict(RECORD) is False)
check("the schema's $schema/title/type keys are recognised as artifact keys",
      not ({"$schema", "title", "type", "properties"} & {"action", "tool", "args"}))

# --- real action attempts: must STILL be treated as actions (retry preserved) ---
check("a tool call is an action", _looks_like_action_dict({"action": "tool", "tool": "shell", "args": {}}) is True)
check("a bare tool envelope is an action", _looks_like_action_dict({"tool": "shell", "args": {"command": "ls"}}) is True)
check("write_todos is an action", _looks_like_action_dict({"action": "write_todos", "todos": []}) is True)
check("a bare todos payload is an action", _looks_like_action_dict({"todos": ["a"]}) is True)
check("a bare steps payload is an action", _looks_like_action_dict({"steps": [{"id": 1}]}) is True)
check("a bare tool-arg key is an action (never leak a stray call)",
      _looks_like_action_dict({"command": "rm -rf /"}) is True)
check("an unknown action name is an action", _looks_like_action_dict({"action": "explain"}) is True)

# --- shapes that are not dicts ---
check("a list is not a dict action", _looks_like_action_dict([{"a": 1}]) is False)
check("a string is not a dict action", _looks_like_action_dict("hello") is False)
check("None is not a dict action", _looks_like_action_dict(None) is False)

# ------------------------------------------------------------------ source locks
s = read("src", "sparkforge", "server.py") + read("src", "sparkforge", "agent.py")
check("the action-dict discriminator exists", "def _looks_like_action_dict(act)" in s)
check("it keys on the action signals",
      '_JSON_ACTION_KEYS = ("action", "tool", "tool_name", "args", "todos", "steps")' in s)
check("it keys on the tool-arg signals",
      '_JSON_TOOL_ARG_KEYS = ("command", "path", "content", "url", "query", "pattern")' in s)
check("the chat loop surfaces a keyless dict as the final answer",
      "if not _looks_like_action_dict(act):" in s and "final_answer = answer" in s)
check("the artifact flag exists", "_final_is_artifact = False" in s)
check("the artifact branch raises the flag", "_final_is_artifact = True" in s)
check("the tail guard exempts a confirmed artifact",
      "(_looks_like_json_action(content) and not _final_is_artifact)" in s)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
