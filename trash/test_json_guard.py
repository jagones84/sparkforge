#!/usr/bin/env python3
import sys

sys.path.insert(0, "/home/jagones/Repositories/sparkforge")
import server  # noqa: E402

cases = [
    ('{"action":"fs.read","path":"/home/jagones/Repos/', True),   # truncated JSON
    ('{"action":"tool","tool":"shell","args":{}}', True),          # canonical
    ('{"action":"fs.read","path":"/x"}', True),                    # action-name variant
    ('Ciao, come stai?', False),                                   # plain prose
    ('Lo scenario è questo: {"a":1} dentro il testo', False),      # JSON inside prose
    ('{"foo": 1}', False),                                         # irrelevant JSON
]
bad = 0
for text, exp in cases:
    got = server._looks_like_json_action(text)
    ok = got == exp
    bad += 0 if ok else 1
    print("%s %-55r got=%s exp=%s" % ("OK " if ok else "BAD", text[:53], got, exp))
print("RESULT:", "ALL OK" if bad == 0 else "%d BAD" % bad)
