"""Gold-task eval harness.

Loads ``eval/gold_tasks.json``, drives every task through the agent loop
(``agent_run`` — imported lazily inside ``eval_run`` to avoid an import cycle)
and scores the trajectory against the expected actions. Extracted from
``server.py`` (JAG-378). Stdlib + sibling modules only.
"""
import json
import os
import time

from longrun.core.events import publish
from longrun.util.paths import REPO_ROOT as REPO


# ---------------------------------------------------------- eval harness ----

EVAL_DIR = os.path.join(REPO, "eval")
GOLD_PATH = os.path.join(EVAL_DIR, "gold_tasks.json")
EVAL_RESULTS_DIR = os.path.join(EVAL_DIR, "results")


def eval_list_tasks():
    try:
        with open(GOLD_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data["tasks"] if isinstance(data, dict) else data
    except FileNotFoundError:
        return []


def _is_subsequence(needle, haystack):
    it = iter(haystack)
    return all(any(x == n for x in it) for n in needle)


def eval_score(result, task):
    """Score one agent run against the gold task.

    Returns dict with per-criterion pass/bool and total score in [0,1].
    Criteria (pattern Winder.AI): every expected action appears, the expected
    ones appear in order (as a subsequence — extra legitimate actions don't
    penalize), finish summary is non-empty, loop did not stall.
    """
    trace = result.get("trace") or []
    # finish is a real action and gold sets list it in expected_actions
    got_actions = [t.get("action") for t in trace if t.get("action")]
    expected = task.get("expected_actions", [])
    checks = {
        "actions_present": all(a in got_actions for a in expected),
        "actions_in_order": _is_subsequence(expected, got_actions),
        "finished": any(t.get("action") == "finish" for t in trace),
        "summary_nonempty": bool((trace[-1].get("summary", "") if trace else "").strip()),
        "no_stall": all((t.get("observation") or t.get("summary") or "")
                        != "unknown action" for t in trace),
    }
    score = sum(1 for v in checks.values() if v) / len(checks)
    return {"score": round(score, 3), "checks": checks,
            "actions_seen": got_actions}


def eval_run(model=None, max_steps=6, task_id=None, save=True):
    """Run every gold task (or one) through the agent loop and score it."""
    from longrun.core.server import agent_run  # lazy: the agent loop lives in server
    tasks = eval_list_tasks()
    if task_id:
        tasks = [t for t in tasks if t.get("id") == task_id]
    if not tasks:
        return {"error": "no eval tasks (missing %s)" % GOLD_PATH}
    results = []
    for t in tasks:
        result = agent_run(t["goal"], max_steps, model)
        sc = eval_score(result, t)
        results.append({"task": t["id"], "goal": t["goal"], "run_id": result.get("run_id"),
                        "score": sc["score"], "checks": sc["checks"],
                        "actions_seen": sc["actions_seen"]})
    summary = {"ts": round(time.time(), 3), "model": model or "default",
               "mean_score": round(sum(r["score"] for r in results) / len(results), 3),
               "per_task": results}
    if save:
        os.makedirs(EVAL_RESULTS_DIR, exist_ok=True)
        path = os.path.join(EVAL_RESULTS_DIR, "eval-%d.json" % int(time.time()))
        with open(path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        summary["saved_to"] = path
    publish("eval.done", mean_score=summary["mean_score"], n=len(results))
    return summary

