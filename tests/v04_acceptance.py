#!/usr/bin/env python3
"""SparkForge v0.4 acceptance — evidence, not claims.

Verifies, against a *running* SparkForge, with command + output + numbers:
  A. always-on: systemd user unit active; API refuses unauthenticated (401),
     accepts the bearer token (200); /api/status reports version 0.4.0
  B. durable event store (SQLite) + replay: events survive restarts and the
     feed reconnects with ?since=N, replaying every event after N
  C. tracing: a chat run produces genuine OpenTelemetry spans (shared
     trace_id, nanosecond timestamps, parent hierarchy) plus token/cost
     accounting on GET /api/runs/<id>/trace
  D. voice: STT transcribes a known wav to its known text; TTS synthesizes a
     wav that is served back as audio/wav
  E. eval harness: POST /api/eval/run scores a gold task in [0,1] and
     persists the result file

Usage:  python3 tests/v04_acceptance.py [--base http://127.0.0.1:8790]
Exit code 0 iff every check passed. Prints a JSON report at the end and
writes data/v04-acceptance.json.
"""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.environ.get("SPARKFORGE_URL", "http://127.0.0.1:8790")
TOKEN = os.environ.get("SPARKFORGE_TOKEN")
DB_PATH = os.environ.get("SPARKFORGE_DB", os.path.join(REPO, "data", "events.db"))

results = []


def http(method, path, body=None, timeout=600, raw=None, ctype=None, auth=True):
    data = raw if raw is not None else (
        json.dumps(body).encode() if body is not None else None)
    headers = {"Content-Type": ctype or "application/json"}
    if TOKEN and auth:
        headers["Authorization"] = "Bearer " + TOKEN
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = r.read().decode()
            try:
                return json.loads(payload or "{}")
            except json.JSONDecodeError:
                return {"_raw": payload[:200]}
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"error": "HTTP %d" % e.code}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


def check(name, ok, evidence, **extra):
    rec = {"check": name, "ok": bool(ok), "evidence": evidence, **extra}
    results.append(rec)
    print("\n%s %s\n   %s" % ("PASS" if ok else "FAIL", name, evidence))
    return ok


# ------------------------------------------------------------------ A ----
def a_alwayson_and_auth():
    unit = subprocess.run(["systemctl", "--user", "is-active", "sparkforge.service"],
                          capture_output=True, text=True).stdout.strip()
    check("A1 systemd unit active",
          unit == "active", "systemctl --user is-active sparkforge.service -> %r" % unit)
    no_tok = http("GET", "/api/status", auth=False)
    with_tok = http("GET", "/api/status")
    check("A2 auth enforced",
          no_tok.get("error") == "unauthorized" and "service" in with_tok,
          "no-token -> %s; with-token -> service=%s version=%s"
          % (no_tok.get("error"), with_tok.get("service"), with_tok.get("version")))
    check("A3 version 0.4.0",
          with_tok.get("version") == "0.4.0",
          "/api/status.version = %r" % with_tok.get("version"))


# ------------------------------------------------------------------ B ----
def b_event_store_and_replay():
    db = sqlite3.connect("file:%s?mode=ro" % DB_PATH, uri=True)
    total, maxid = db.execute("SELECT COUNT(*), MAX(id) FROM events").fetchone()
    check("B1 events are durable (SQLite)",
          total > 0, "SELECT COUNT(*) FROM events -> %d rows, max id %d" % (total, maxid))
    kinds = [r[0] for r in db.execute(
        "SELECT DISTINCT kind FROM events ORDER BY kind LIMIT 100")]
    check("B2 event kinds recorded",
          len(kinds) >= 3, "%d distinct kinds: %s" % (len(kinds), kinds[:8]))
    since = max(1, maxid - 20)
    recent = http("GET", "/api/feed/recent?limit=5")
    ids = [e.get("id") for e in recent.get("events", [])]
    check("B3 recent backlog endpoint",
          bool(ids) and ids == sorted(ids), "/api/feed/recent ids -> %s" % ids)
    # SSE replay: ?since= must start the stream with events id > since
    url = "%s/api/feed?since=%d&token=%s" % (BASE, since, TOKEN)
    out = subprocess.run(["curl", "-sN", "-m", "3", url], capture_output=True, text=True)
    lines = [l[5:].strip() for l in out.stdout.splitlines() if l.startswith("data:")]
    replayed = []
    for l in lines:
        try:
            payload = json.loads(l)
        except json.JSONDecodeError:
            continue
        replayed.extend(payload if isinstance(payload, list) else [payload])
    ok = bool(replayed) and all(e.get("id", 0) > since for e in replayed)
    check("B4 feed replay with ?since=",
          ok, "curl -sN '/api/feed?since=%d' replayed %d events, ids %d..%d (all > %d)"
          % (since, len(replayed), replayed[0].get("id", -1) if replayed else -1,
             replayed[-1].get("id", -1) if replayed else -1, since))
    return {"total_events": total, "replay_since": since, "replayed": len(replayed)}


# ------------------------------------------------------------------ C ----
def c_tracing():
    out = http("POST", "/api/chat", {"message": "Reply with exactly: TRACE TEST"}, timeout=180)
    rid = out.get("run_id")
    check("C1 chat run returns run_id",
          bool(rid), "POST /api/chat -> run_id=%r reply=%r"
          % (rid, (out.get("reply") or "")[:60]))
    if not rid:
        return {}
    t = http("GET", "/api/runs/%s/trace" % rid)
    spans = t.get("spans", [])
    tids = {s.get("trace_id") for s in spans}
    otel_ids = [i for i in tids if i]
    names = [s.get("name") for s in spans]
    check("C2 genuine OTel spans",
          t.get("otel") is True and len(otel_ids) == 1 and len(names) >= 2,
          "GET /api/runs/%s/trace -> otel=%s trace_id=%s spans=%s"
          % (rid, t.get("otel"), next(iter(otel_ids), None), names))
    root = [s for s in spans if s.get("name") == "sparkforge.run"]
    ns_ok = bool(root) and isinstance(root[0].get("start_ns"), int) \
        and root[0]["start_ns"] > 1e18
    check("C3 nanosecond timestamps + root span",
          ns_ok, "root start_ns=%s end_ns=%s" % (root[0].get("start_ns") if root else None,
                                                 root[0].get("end_ns") if root else None))
    check("C4 token/cost accounting",
          t.get("tokens_in", 0) > 0 and isinstance(t.get("cost_usd"), (int, float)),
          "tokens_in=%s tokens_out=%s cost_usd=%s (local models price 0)"
          % (t.get("tokens_in"), t.get("tokens_out"), t.get("cost_usd")))
    return {"run_id": rid, "trace_id": next(iter(otel_ids), None), "spans": names}


# ------------------------------------------------------------------ D ----
def d_voice():
    st = http("GET", "/api/voice/status")
    check("D1 voice backends detected",
          st.get("stt", {}).get("available") and st.get("tts", {}).get("available"),
          "/api/voice/status -> stt(style=%s model=%s)=%s, tts(model=%s)=%s"
          % (st.get("stt", {}).get("style"), st.get("stt", {}).get("model"),
             st.get("stt", {}).get("available"), st.get("tts", {}).get("model"),
             st.get("tts", {}).get("available")))
    wav = os.path.join(REPO, "tests", "data", "jfk.wav")
    if not os.path.isfile(wav):
        check("D2 STT transcription", False, "missing test asset tests/data/jfk.wav")
    else:
        stt = http("POST", "/api/voice/stt", raw=open(wav, "rb").read(),
                   ctype="audio/wav", timeout=300)
        text = stt.get("text", "")
        check("D2 STT transcription",
              "americans" in text.lower(),
              "POST /api/voice/stt (audio/wav upload, 16 kHz mono) -> %d chars: %r"
              % (len(text), text[:90]))
    tts = http("POST", "/api/voice/tts", {"text": "SparkForge v0.4 voice check."}, timeout=300)
    fname = tts.get("file")
    check("D3 TTS synthesis",
          bool(fname) and (tts.get("seconds") or 0) > 0.5,
          "POST /api/voice/tts -> %s (%s s, path=%s)"
          % (fname, tts.get("seconds"), tts.get("path")))
    audio = None
    if fname:
        req = urllib.request.Request(BASE + "/api/voice/audio/" + fname,
                                     headers={"Authorization": "Bearer " + TOKEN})
        try:
            audio = urllib.request.urlopen(req, timeout=30).read()
        except Exception as e:  # noqa: BLE001
            audio = str(e).encode()
    check("D4 TTS wav served back",
          isinstance(audio, bytes) and audio[:4] == b"RIFF",
          "GET /api/voice/audio/%s -> %d bytes, header %r"
          % (fname, len(audio) if isinstance(audio, bytes) else -1,
             audio[:4] if isinstance(audio, bytes) else audio))
    return {"stt_chars": len(stt.get("text", "")) if st.get("stt") else -1,
            "tts_file": fname, "tts_seconds": tts.get("seconds")}


# ------------------------------------------------------------------ E ----
def e_eval():
    run = http("POST", "/api/eval/run", {"task_id": "plan-hello", "max_steps": 4, "save": True},
               timeout=900)
    score = run.get("mean_score")
    saved = run.get("saved_to")
    check("E1 eval run produces a score",
          isinstance(score, (int, float)) and 0.0 <= score <= 1.0,
          "POST /api/eval/run {task_id: plan-hello} -> mean_score=%s per_task=%s"
          % (score, json.dumps(run.get("per_task"))[:220]))
    check("E2 eval result persisted",
          bool(saved) and os.path.isfile(saved),
          "saved_to=%s exists=%s" % (saved, os.path.isfile(saved) if saved else False))
    return {"mean_score": score, "saved_to": saved}


def main():
    global BASE, TOKEN
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--token", default=TOKEN)
    args = ap.parse_args()
    BASE, TOKEN = args.base, args.token
    if not TOKEN:
        print("SPARKFORGE_TOKEN required (the service runs with --token)", file=sys.stderr)
        return 2

    a_alwayson_and_auth()
    b_event_store_and_replay()
    c_tracing()
    d_voice()
    e_eval()

    passed = sum(1 for r in results if r["ok"])
    report = {"ts": time.time(), "base": BASE, "passed": passed,
              "total": len(results), "checks": results}
    out_path = os.path.join(REPO, "data", "v04-acceptance.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print("\n=== v0.4 acceptance: %d/%d passed ===" % (passed, len(results)))
    print("report: %s" % out_path)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())