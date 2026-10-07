#!/usr/bin/env python3
"""v0.7.8 acceptance — the MODEL drives its own task graph (JAG-75).

Before this, the task list could be created by the model but only the UI/API could
advance it. Now the model itself marks steps doing/done (with evidence) and can
briefly re-plan, then resume the plan — the behaviour the user described.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="sf-tg-")
os.environ["SPARKFORGE_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["SPARKFORGE_DB"] = os.path.join(tmp, "events.db")
os.environ["SPARKFORGE_GRAPH_DIR"] = os.path.join(tmp, "graphs")
os.makedirs(os.environ["SPARKFORGE_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["SPARKFORGE_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from sparkforge import server  # noqa: E402
from sparkforge import taskgraph  # noqa: E402

server.CHAT_TOOL_MAX_STEPS = 10
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# The model: plan -> doing -> done(evidence) -> brief replan -> final prose.
seq = [
    ('{"action":"write_todos","todos":[{"label":"passo uno"},{"label":"passo due"}]}', "", "m"),
    ('{"action":"update_todos","steps":[{"index":0,"status":"doing"}]}', "", "m"),
    ('{"action":"update_todos","steps":[{"index":0,"status":"done","evidence":"prova: file creato"}]}', "", "m"),
    ('{"action":"replan_todos","note":"serve un passo di verifica"}', "", "m"),
    ("Fatto: piano completato.", "", "m"),
]


def fake_stream(msgs, model, kind, on_delta, timeout=300, usage=None):
    return seq.pop(0) if seq else ("Fine.", "", model)


server.stream_with_fallback = fake_stream

# replan must NOT call a real model in the test: stub it to add one node.
replanned = {"n": 0}


def fake_replan(graph, note=None, model=None, on_event=None):
    replanned["n"] += 1
    node = taskgraph.add_node(graph, "verifica finale (replan)", source="test:replan")
    return [node]


taskgraph.replan_from_model = fake_replan

events = []


def on_event(kind, **data):
    events.append(kind)


sess = server.get_or_create_session("tg-test")
reply, _ = server.chat_once(sess, "fai due passi", None,
                            on_delta=lambda ch, t: None, on_event=on_event)

graph = taskgraph.ensure("tg-test")
nodes = graph["nodes"]
check("G1 the model authored the initial plan (2 steps)", len(nodes) >= 2,
      "nodes=%d" % len(nodes))
check("G2 the model advanced its own step to 'done'",
      nodes[0].get("status") == "done", "status=%s" % nodes[0].get("status"))
check("G3 the completion carries the model's evidence",
      any("prova: file creato" in str(e) for e in (nodes[0].get("evidence") or [])),
      "evidence=%s" % nodes[0].get("evidence"))
check("G4 the graph update streamed to the app (graph.node.updated)",
      "graph.node.updated" in events, "kinds=%s" % sorted(set(events)))
check("G5 an inline card was emitted for update_todos",
      "tool.call" in events and "tool.result" in events)
check("G6 the model was able to briefly re-plan and the loop continued",
      replanned["n"] == 1 and len(graph["nodes"]) >= 3,
      "replanned=%d nodes=%d" % (replanned["n"], len(graph["nodes"])))
check("G7 the final reply is real prose, not an action JSON",
      "action" not in reply.get("content", ""), "content=%s" % reply.get("content", "")[:60])

print("\n==== %d/%d checks passed ====" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
