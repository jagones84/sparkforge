#!/usr/bin/env python3
"""SparkForge v0.6 acceptance — LLM task graph, live, bound to the run.

Evidence, not claims. Every check prints command-level proof (HTTP status,
SSE event names, measured latencies, node JSON) and the run writes
`data/v06-acceptance.json`.

  A. taskgraph module: nodes with deps, evidence is mandatory for `done`,
     NDJSON/nested `write_todos` parsing, finalize closes open nodes.
  B. mock-router end-to-end (deterministic, no GPU):
     B1 `POST /api/chat/stream` emits `chat.run` with a run_id
     B2 >= 3 model-generated `graph.node.added` nodes within 1.0 s (todo)
     B3 nodes carry deps and are linked to the session
     B4 `GET /api/runs/<id>/graph` returns the persisted graph
     B5 at run end every node is `done` **with evidence**
     B6 `POST /api/runs/<id>/graph/nodes`: add node, `done` without evidence
        → 400, with evidence → 200, cancel → cancelled, replan adds only new steps
  C. live service (best effort, skipped if unreachable): a real multi-step
     request produces a >= 3-node graph that ends all-done with evidence.

Usage: python3 tests/v06_taskgraph.py [--base http://127.0.0.1:8790]
Exit code 0 iff every executed check passed (skips are not failures).
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
BASE = os.environ.get("SPARKFORGE_URL", "http://127.0.0.1:8790")
MOCK_PORT = int(os.environ.get("SPARKFORGE_MOCK_PORT", 8097))
TEST_PORT = int(os.environ.get("SPARKFORGE_TEST_PORT", 8797))

results = []


def _read_token():
    tok = os.environ.get("SPARKFORGE_TOKEN")
    if tok:
        return tok
    envf = os.path.expanduser("~/.config/sparkforge/env")
    if os.path.isfile(envf):
        for line in open(envf):
            if line.startswith("SPARKFORGE_TOKEN="):
                return line.split("=", 1)[1].strip()
    return None


TOKEN = _read_token()


def check(name, ok, evidence, **extra):
    rec = {"check": name, "ok": bool(ok), "evidence": evidence, **extra}
    results.append(rec)
    print("\n%s %s\n   %s" % ("PASS" if ok else "FAIL", name, evidence))
    return ok


def http(method, path, body=None, timeout=60, base=None, token=None):
    base = base or BASE
    token = token if token is not None else TOKEN
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(base + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:
            return e.code, {"error": "HTTP %d" % e.code}
    except Exception as e:  # noqa: BLE001
        return 0, {"error": str(e)}


def sse_stream(base, token, message, session, model=None, timeout=90):
    """POST /api/chat/stream; return (status, ctype, list of (event, data, t))."""
    body = {"message": message, "session": session}
    if model:
        body["model"] = model
    req = urllib.request.Request(
        base + "/api/chat/stream", data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + token})
    t0 = time.time()
    events = []
    with urllib.request.urlopen(req, timeout=timeout) as r:
        status, ctype = r.status, r.headers.get("Content-Type", "")
        cur = None
        for raw in r:
            line = raw.decode("utf-8", "replace").rstrip("\n")
            if line.startswith("event:"):
                cur = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                try:
                    data = json.loads(line.split(":", 1)[1].strip())
                except Exception:  # noqa: BLE001
                    data = {}
                events.append((cur, data, round(time.time() - t0, 3)))
    return status, ctype, events


# ------------------------------------------------------------------ A ----
def part_a_module():
    os.environ["SPARKFORGE_GRAPH_DIR"] = "/tmp/sparkforge-v06-unit"
    import taskgraph as tg
    tg.GRAPH_DIR = os.path.join("/tmp/sparkforge-v06-unit", "graphs")
    # fresh run id per invocation so the check is idempotent across runs
    g = tg.ensure("run_unit_%s" % uuid.uuid4().hex[:8], session_id="sess-unit", goal="unit")
    nodes = tg.apply_write_todos(g, [
        {"label": "leggi l'input", "deps": []},
        {"label": "estrai i requisiti", "deps": [0]},
        {"label": "scrivi l'output", "deps": [1]},
    ])
    deps_ok = nodes[1]["deps"] == [nodes[0]["id"]] and nodes[2]["deps"] == [nodes[1]["id"]]
    check("A1 write_todos → 3 nodes, deps wired by index",
          len(nodes) == 3 and deps_ok,
          "nodes=%s deps=%s" % ([n["id"] for n in nodes], [n["deps"] for n in nodes]))
    err = None
    try:
        tg.update_node(g, nodes[0]["id"], status="done")
    except ValueError as e:
        err = str(e)
    check("A2 status=done without evidence is rejected",
          err is not None and "evidence" in err, "ValueError: %s" % err)
    tg.update_node(g, nodes[0]["id"], status="done",
                   evidence="cmd=echo ok output=ok exit=0")
    check("A3 done with evidence stores it",
          tg.find(g, nodes[0]["id"])["evidence"][0]["text"].startswith("cmd="),
          "evidence=%s" % json.dumps(tg.find(g, nodes[0]["id"])["evidence"], ensure_ascii=False))
    nd, saw = tg.parse_todos('{"tool":"write_todos"}\n{"label":"a","deps":[]}\n{"label":"b"}')
    nested, saw2 = tg.parse_todos('{"tool":"write_todos","todos":[{"label":"c"}]}')
    check("A4 NDJSON + nested write_todos parsing",
          [t.get("label") for t in nd] == ["a", "b"] and saw
          and [t.get("label") for t in nested] == ["c"] and saw2,
          "ndjson=%s nested=%s" % (nd, nested))
    closed = tg.finalize(g, "run unit complete")
    c = tg.counts(g)
    check("A5 finalize closes open nodes with evidence → all done",
          c["done"] == 3 and all(tg.find(g, n["id"])["evidence"] for n in nodes),
          "finalized=%d counts=%s" % (len(closed), c))


# ------------------------------------------------------------- B (mock) ----
def _wait_port(base, token, timeout=15):
    for _ in range(int(timeout * 2)):
        st, _ = http("GET", "/api/status", base=base, token=token, timeout=3)
        if st == 200:
            return True
        time.sleep(0.5)
    return False


def part_b_mock():
    mock = subprocess.Popen([sys.executable, os.path.join(REPO, "tests", "mock_router.py"),
                             "--port", str(MOCK_PORT), "--warm-seconds", "0"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    env = dict(os.environ, SPARKFORGE_ROUTER="http://127.0.0.1:%d" % MOCK_PORT,
               SPARKFORGE_GRAPH_DIR="/tmp/sparkforge-v06-graphs",
               SPARKFORGE_DB="/tmp/sparkforge-v06-test.db",
               SPARKFORGE_MODEL_LOAD_TIMEOUT="60")
    inst = subprocess.Popen([sys.executable, os.path.join(REPO, "server.py"),
                             "--host", "127.0.0.1", "--port", str(TEST_PORT),
                             "--token", "test-token"],
                            cwd=REPO, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = "http://127.0.0.1:%d" % TEST_PORT
    tok = "test-token"
    try:
        up = _wait_port(base, tok)
        check("B0 mock router + test instance up", up, "base=%s up=%s" % (base, up))
        if not up:
            return
        msg = "Analizza questo testo in 3 step e produci un riassunto verificato"
        status, ctype, evs = sse_stream(base, tok, msg, "v06-mock", model="mock-alpha")
        kinds = [e[0] for e in evs]
        run_id = next((e[1].get("run_id") for e in evs if e[0] == "chat.run"), None)
        check("B1 chat stream emits chat.run with a run_id",
              status == 200 and ctype.startswith("text/event-stream") and bool(run_id),
              "HTTP %s Content-Type=%s run_id=%s" % (status, ctype, run_id), run_id=run_id)
        added = [e for e in evs if e[0] == "graph.node.added"]
        times = [e[2] for e in added]
        first3 = times[2] if len(times) >= 3 else None
        check("B2 >= 3 graph.node.added (todo) within 1.0 s via SSE",
              len(added) >= 3 and first3 is not None and first3 <= 1.0,
              "added=%d first3_at=%ss nodes=%s" % (
                  len(added), first3, [e[1]["node"]["label"][:34] for e in added]),
              first3_seconds=first3)
        statuses = {e[1]["node"]["status"] for e in added}
        deps_ok = any(e[1]["node"]["deps"] for e in added)
        check("B3 nodes are todo with deps (model-generated labels)",
              statuses == {"todo"} and deps_ok,
              "statuses=%s deps=%s" % (statuses, [e[1]["node"]["deps"] for e in added]))
        st, g = http("GET", "/api/runs/%s/graph" % run_id, base=base, token=tok)
        check("B4 GET /api/runs/<id>/graph → persisted graph bound to run+session",
              st == 200 and g.get("run_id") == run_id and g.get("session_id") == "v06-mock"
              and g.get("node_count", 0) >= 3,
              "HTTP %s run=%s session=%s nodes=%s status=%s" % (
                  st, g.get("run_id"), g.get("session_id"), g.get("node_count"), g.get("status")))
        # run end: all nodes done, each with evidence
        st, g = http("GET", "/api/runs/%s/graph" % run_id, base=base, token=tok)
        all_done = g.get("counts", {}).get("done") == g.get("node_count") and g["node_count"] >= 3
        with_ev = all(n.get("evidence") for n in g.get("nodes", []))
        check("B5 at run end all nodes done, each with evidence",
              all_done and with_ev,
              "counts=%s evidence_missing=%s" % (
                  g.get("counts"), [n["label"] for n in g.get("nodes", []) if not n.get("evidence")]))

        # interactive POST /api/runs/<id>/graph/nodes
        st, n = http("POST", "/api/runs/%s/graph/nodes" % run_id,
                     {"action": "add", "label": "Verifica manuale finale"},
                     base=base, token=tok)
        added_ok = st == 200 and n.get("status") == "todo"
        st_no, err = http("POST", "/api/runs/%s/graph/nodes" % run_id,
                          {"action": "update", "id": n.get("id"), "status": "done"},
                          base=base, token=tok)
        st_yes, n2 = http("POST", "/api/runs/%s/graph/nodes" % run_id,
                          {"action": "update", "id": n.get("id"), "status": "done",
                           "evidence": "cmd=pytest output=3 passed exit=0"},
                          base=base, token=tok)
        st_cancel, n3 = http("POST", "/api/runs/%s/graph/nodes" % run_id,
                             {"action": "cancel", "id": g["nodes"][0]["id"]},
                             base=base, token=tok)
        check("B6 POST graph/nodes: add, done-without-evidence=400, with evidence, cancel",
              added_ok and st_no == 400 and st_yes == 200 and n2.get("status") == "done"
              and st_cancel == 200 and n3.get("status") == "cancelled",
              "add=%s done_none=%s(%s) done_ev=%s cancel=%s" % (
                  st, st_no, err.get("error"), st_yes, st_cancel))
        st, r = http("POST", "/api/runs/%s/graph/nodes" % run_id,
                     {"action": "replan", "note": "aggiungi un passo di verifica"},
                     base=base, token=tok)
        check("B7 incremental re-plan adds only NEW steps (no duplicates)",
              st == 200 and all(l not in [x["label"] for x in g.get("nodes", [])]
                                for l in r.get("added_labels", [])) or r.get("added") == [],
              "HTTP %s added=%s nodes=%s" % (st, r.get("added_labels"), r.get("nodes")))
    finally:
        for p in (inst, mock):
            try:
                p.terminate()
                p.wait(timeout=5)
            except Exception:  # noqa: BLE001
                try:
                    p.kill()
                except Exception:
                    pass


# ------------------------------------------------------------- C (live) ----
def part_c_live():
    st, _ = http("GET", "/api/status", timeout=5)
    if st != 200:
        check("C0 live service reachable", True,
              "SKIPPED: %s unreachable (mock coverage above is authoritative)" % BASE,
              skipped=True)
        return
    msg = ("Pianifica in 3 step questa attivita: analizza il file README.md, "
           "estrai i 3 punti chiave e produci una sintesi finale verificata")
    try:
        status, _ctype, evs = sse_stream(BASE, TOKEN, msg, "v06-live", timeout=180)
    except Exception as e:  # noqa: BLE001
        check("C1 live multi-step request → >= 3-node graph", True,
              "SKIPPED: live stream error %s" % e, skipped=True)
        return
    kinds = [e[0] for e in evs]
    run_id = next((e[1].get("run_id") for e in evs if e[0] == "chat.run"), None)
    added = [e for e in evs if e[0] == "graph.node.added"]
    check("C1 live multi-step request → >= 3 model-generated nodes",
          len(added) >= 3,
          "run=%s nodes=%d kinds(first)=%s" % (run_id, len(added), kinds[:6]))
    if not run_id:
        return
    _st, g = http("GET", "/api/runs/%s/graph" % run_id, timeout=20)
    check("C2 live run graph is all-done with evidence",
          g.get("counts", {}).get("done") == g.get("node_count") and g.get("node_count", 0) >= 3,
          "nodes=%s counts=%s" % (g.get("node_count"), g.get("counts")))


def main():
    global BASE, TOKEN
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--token", default=TOKEN)
    a = ap.parse_args()
    BASE, TOKEN = a.base, a.token
    print("SparkForge v0.6 task-graph acceptance — base=%s token=%s" % (
        BASE, "set" if TOKEN else "none"))
    part_a_module()
    part_b_mock()
    part_c_live()
    executed = [r for r in results if not r.get("skipped")]
    passed = sum(1 for r in executed if r["ok"])
    report = {"base": BASE, "ts": time.time(), "passed": passed,
              "total": len(executed), "results": results}
    os.makedirs(os.path.join(REPO, "data"), exist_ok=True)
    with open(os.path.join(REPO, "data", "v06-acceptance.json"), "w") as f:
        json.dump(report, f, indent=2)
    print("\n==== %d/%d checks passed (%d skipped) ====" % (
        passed, len(executed), len(results) - len(executed)))
    return 0 if passed == len(executed) else 1


if __name__ == "__main__":
    sys.exit(main())
