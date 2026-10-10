#!/usr/bin/env python3
"""v345 — property gate for server.extract_json (stdlib, deterministic).

Revives the coverage the dead Hypothesis suite (tests/properties/test_pure_logic.py,
needs an uninstalled `hypothesis`) was supposed to provide: extract_json — the
function that turns a model's prose into an action dict — had ZERO runnable gate.
Randomized but SEEDED, so it is deterministic and belongs in the battery.

Property: for any JSON object/array V rendered inside prose/markdown, extract_json
returns a value equal to V (the FIRST balanced value in the text) and never raises.

Deterministic, no model. Run: python3 tests/acceptance/v345_json_extract_props.py
"""
import json
import os
import random
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun import server  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


random.seed(345)


def rnd_scalar():
    return random.choice([0, 1, -1, 3.14, "", "plain", "brace { } inside",
                          'quote " inside', "back\\slash", "unicode \u2713 \u00e9",
                          True, False, None])


def rnd_key():
    return random.choice(["a", "b", "n", "k1", "with space", "brace{}", 'quote"',
                          "uni\u2713", ""])


def rnd_value(depth=0):
    r = random.random()
    if depth >= 3 or r < 0.45:
        return rnd_scalar()
    if r < 0.72:
        return [rnd_value(depth + 1) for _ in range(random.randint(0, 3))]
    return {rnd_key(): rnd_value(depth + 1) for _ in range(random.randint(0, 3))}


# --- A: the exact value (dict/array) wrapped in prose/markdown is recovered ----
N = 400
bad = []
for _ in range(N):
    v = rnd_value()
    while not isinstance(v, (dict, list)):
        v = rnd_value()
    payload = random.choice([
        "```json\n%s\n```" % json.dumps(v),
        "Here is the result:\n```json\n%s\n```\nDone." % json.dumps(v),
        "prose before %s prose after" % json.dumps(v),
        "Here is the result:\n```json\n%s\n```\nDone." % json.dumps(v, ensure_ascii=False),
    ])
    got = server.extract_json(payload)
    if got != v:
        bad.append((v, got))
check("A %d randomized wrapped values recovered exactly" % N, not bad,
      "" if not bad else "first mismatch: %r -> %r" % (bad[0][0], bad[0][1]))

# --- B: edge cases -------------------------------------------------------------
check("B1 empty object {}", server.extract_json("```json\n{}\n```") == {})
check("B2 empty array []", server.extract_json("x [] y") == [])
check("B3 nested empties", server.extract_json('{"a": {}, "b": []}') == {"a": {}, "b": []})
check("B4 bare valid JSON parses", server.extract_json('{"status": "ok"}') == {"status": "ok"})
check("B5 empty/None input -> None",
      server.extract_json("") is None and server.extract_json(None) is None)
check("B6 no JSON -> None", server.extract_json("no json here") is None)
check("B7 a brace inside a STRING does not fool the scanner",
      server.extract_json('{"s": "a { b } c"}') == {"s": "a { b } c"})

# --- C: first-of-many precedence -----------------------------------------------
check("C1 the FIRST of several objects wins",
      server.extract_json('{"a": 1} then {"b": 2}') == {"a": 1})

# --- D: never raises on malformed input ----------------------------------------
crashed = []
for junk in ["{{{{", "]]]]", '{"a": ', "{]", '["unterminated', '"', "\\",
             "{'x': 1}", "{,}", "\u0000\u0001"]:
    try:
        server.extract_json(junk)
    except Exception as e:  # noqa: BLE001
        crashed.append((junk, repr(e)))
check("D malformed input never raises", not crashed,
      "" if not crashed else "raised: %r" % (crashed[0],))

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
