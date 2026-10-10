"""Prose-tolerant text helpers: split `<think>` blocks, recover JSON from prose.

Models frequently wrap their action JSON in prose and emit SEVERAL values in one
message; these scanners recover each complete value without dropping the turn.

Extracted from ``server.py`` (JAG-370). Pure functions, stdlib only.
"""
import json
import re


def strip_think(text):
    """Split optional <think>...</think> out of content."""
    m = re.search(r"<think>(.*?)</think>", text, re.S)
    if m:
        return text[: m.start()] + text[m.end():], m.group(1)
    return text, None


def _iter_json_objects(text):
    """Every balanced top-level JSON object/array found in `text`, in order.

    Models frequently wrap their action JSON in prose ("Here is the plan. {..} Now
    I proceed. {..}") or emit SEVERAL actions in one message. The old
    first-`{`..last-`}` slice swallowed the prose between the objects and failed
    to parse, so the turn fell through to "announce and stop". This scanner walks
    the text with a brace/quote-aware cursor and yields each complete value
    independently.
    """
    objs, i, n = [], 0, len(text)
    while i < n:
        if text[i] in "{[":
            depth, instr, esc, start = 0, False, False, i
            j = i
            while j < n:
                c = text[j]
                if instr:
                    if esc:
                        esc = False
                    elif c == "\\":
                        esc = True
                    elif c == '"':
                        instr = False
                else:
                    if c == '"':
                        instr = True
                    elif c in "{[":
                        depth += 1
                    elif c in "}]":
                        depth -= 1
                        if depth == 0:
                            break
                j += 1
            if depth == 0 and j < n:
                try:
                    objs.append(json.loads(text[start:j + 1]))
                except Exception:  # noqa: BLE001 — skip an unparseable blob
                    pass
                i = j + 1
                continue
        i += 1
    return objs


def extract_json(text):
    """First JSON value in `text` (prose-tolerant, multi-object safe).

    Tolerates prose around and BETWEEN objects: returns the FIRST complete
    {"action": ...} the model emitted, so the chat/agent loop acts on it instead
    of dropping the whole turn.
    """
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    objs = _iter_json_objects(text)
    return objs[0] if objs else None
