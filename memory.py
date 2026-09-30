#!/usr/bin/env python3
"""SparkForge persistent memory store — v0.3

Write-rules: append-only markdown documents with an optional vector-similarity
index (via numpy cosine-sim). Records are written on semantically significant
harness events (plan update, task complete, tool result, chat summary) and can
be retrieved by keyword or semantic similarity.

Two backends:
- **flat** — markdown files in `data/memory/` (always on; no deps)
- **vector** — numpy-based cosine similarity on sentence embeddings
  (requires `numpy` and optionally `sentence-transformers` or a local embedding
  endpoint; uses a bag-of-words fallback if neither is available)

Rules:
- Every write has a timestamp, kind, session/run id, and freeform content.
- Old entries are never mutated (append-only).
- The vector index is rebuilt on server start and after every N writes.
"""

import json
import os
import re
import threading
import time

import registry

REPO = registry.REPO
DATA_DIR = os.path.join(REPO, "data", "memory")

_lock = threading.RLock()
_writes_since_index = 0
_REBUILD_INTERVAL = 20  # rebuild vector index every N writes

# ---------------------------------------------------------------- markdown ----

MEMORY_FIELDS = {
    "tool.result": "tool_result.md",
    "plan.update": "plan_updates.md",
    "task.done": "task_done.md",
    "chat.summary": "chat_summaries.md",
    "agent.note": "agent_notes.md",
    "memory.store": "user_memories.md",
}


def _path(kind):
    fn = MEMORY_FIELDS.get(kind, "other.md")
    p = os.path.join(DATA_DIR, fn)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return p


def store(kind, content, **meta):
    """Write one append-only record.

    Args:
        kind: one of the MEMORY_FIELDS keys (or any string; unknown kinds
              go to other.md)
        content: the main text payload
        meta: key=value pairs stored as YAML front-matter (id, session,
              run_id, tags, etc.)

    Returns the record dict.
    """
    global _writes_since_index
    with _lock:
        rec = {
            "ts": round(time.time(), 3),
            "kind": kind,
            "content": str(content)[:8000],
            **{k: str(v)[:500] for k, v in meta.items()},
        }
        md = _render_md(rec)
        p = _path(kind)
        with open(p, "a", encoding="utf-8") as f:
            f.write(md + "\n")
        _writes_since_index += 1
        if _writes_since_index >= _REBUILD_INTERVAL:
            _rebuild_index()
    return rec


def _render_md(rec):
    """Render a record as a multi-line markdown block."""
    lines = ["---"]
    for key in ("ts", "kind", "session", "run_id", "tags", "model", "tool"):
        val = rec.get(key)
        if val is not None:
            lines.append("%s: %s" % (key, val))
    lines.append("---")
    lines.append(str(rec.get("content", "")).strip())
    lines.append("")  # trailing blank line separators
    return "\n".join(lines)


# ------------------------------------------------------------------ query ----

def query(term=None, kind=None, limit=20):
    """Search memory by keyword (substring/regex) and/or kind.

    Returns up to `limit` records sorted by recency (newest first).
    """
    out = []
    kinds = [kind] if kind else list(MEMORY_FIELDS.keys()) + ["other"]
    for k in kinds:
        p = _path(k)
        if not os.path.isfile(p):
            continue
        for rec in _parse_md_file(p):
            if term and not _match(rec.get("content", ""), term):
                continue
            out.append(rec)
    out.sort(key=lambda r: r.get("ts", 0), reverse=True)
    return out[:limit]


def _match(text, term):
    try:
        if re.search(term, text, re.I):
            return True
    except re.error:
        pass
    if term.lower() in text.lower():
        return True
    # fall back to AND-of-words: every whitespace-separated term must appear
    words = [w for w in re.split(r"\W+", term.lower()) if len(w) > 2]
    low = text.lower()
    return bool(words) and all(w in low for w in words)


def _parse_md_file(path):
    """Parse records from an append-only markdown file."""
    records = []
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    blocks = content.split("\n---\n")
    for block in blocks:
        block = block.strip()
        if not block or block == "---":
            continue
        rec = {"content": ""}
        lines = block.split("\n")
        in_front = block.startswith("---") or block.startswith("ts:")
        i = 0
        if in_front:
            for i, line in enumerate(lines):
                if line.startswith("---"):
                    continue
                if ":" in line:
                    key, _, val = line.partition(":")
                    key = key.strip()
                    val = val.strip()
                    if key:
                        rec[key] = _cast(val)
                else:
                    break
            else:
                i = len(lines)
            rec["content"] = "\n".join(l for l in lines[i:] if l.strip()).strip()
        else:
            rec["content"] = block[:2000]
        if rec.get("content") or rec.get("kind"):
            records.append(rec)
    return records


def _cast(val):
    for fn in (int, float):
        try:
            return fn(val)
        except (ValueError, TypeError):
            continue
    if val.lower() in ("true", "yes"): return True
    if val.lower() in ("false", "no"): return False
    if val.strip().startswith("[") or val.strip().startswith("{"):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, ValueError):
            pass
    return val


# ---------------------------------------------------------- vector index ----

_vector_db = None  # {kind: {vectors: [[…]], records: [{…}], dim: int}}


def _rebuild_index():
    """Rebuild the in-memory vector index from all markdown files."""
    global _vector_db, _writes_since_index
    try:
        import numpy as np  # noqa: F401
    except ImportError:
        _vector_db = {}
        _writes_since_index = 0
        return
    db = {}
    for kind, fn in MEMORY_FIELDS.items():
        p = os.path.join(DATA_DIR, fn)
        if not os.path.isfile(p):
            continue
        records = _parse_md_file(p)
        if not records:
            continue
        texts = [r.get("content", "")[:2000] for r in records]
        vocab = _build_vocab(texts)
        vecs = _embed_batch(texts, vocab)
        if vecs is not None and len(vecs) == len(records):
            db[kind] = {"vectors": vecs, "records": records,
                        "dim": len(vecs[0]), "vocab": vocab}
    _vector_db = db
    _writes_since_index = 0


def _build_vocab(texts):
    """Sorted vocabulary shared by index and query bag-of-words vectors."""
    vocab = set()
    for t in texts:
        vocab.update(t.lower().split())
    return sorted(vocab)


_EMBEDDER = None
_EMBEDDER_READY = False
_EMBEDDER_LOCK = threading.Lock()
_ENDPOINT_DISABLED = False


def _get_embedder():
    """Load the sentence-transformer backend ONCE and reuse it (JAG-72).

    The old code constructed `SentenceTransformer(...)` on EVERY search — seconds
    of work (and, on a cold cache, a possible multi-minute model download) per
    turn. That is the main reason the agent looked "inactive". Now it is loaded a
    single time; if it is unavailable we remember that and never retry.
    """
    global _EMBEDDER, _EMBEDDER_READY
    if _EMBEDDER_READY:
        return _EMBEDDER
    with _EMBEDDER_LOCK:
        if not _EMBEDDER_READY:
            try:
                from sentence_transformers import SentenceTransformer
                _EMBEDDER = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
            except Exception:
                _EMBEDDER = None
            _EMBEDDER_READY = True
    return _EMBEDDER


def _embed_batch(texts, vocab=None):
    """Return a list of numpy vectors, or None if no embedding backend works.

    `vocab` pins the bag-of-words dimensionality: the query vector must use
    the exact vocab the index was built with or the cosine product misaligns.
    """
    # Priority: sentence-transformers (GPU-friendly) > local endpoint > bag-of-words
    global _ENDPOINT_DISABLED
    model = _get_embedder()
    if model is not None:
        try:
            return model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
        except Exception:
            pass
    if not _ENDPOINT_DISABLED:
        try:
            import urllib.request
            import json as j
            body = j.dumps({"model": "default", "input": texts}).encode()
            req = urllib.request.Request(
                "http://127.0.0.1:8080/v1/embeddings", data=body,
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = j.loads(resp.read().decode())
            emb = [d["embedding"] for d in data.get("data", [])]
            import numpy as np
            return np.array(emb) / np.linalg.norm(emb, axis=1, keepdims=True)
        except Exception:
            # JAG-72: one failed probe disables it for the session so we never
            # pay this timeout again (it used to be 30s per kind, per call).
            _ENDPOINT_DISABLED = True
    try:
        import numpy as np
        # bag-of-words fallback over the shared vocab
        if vocab is None:
            vocab = _build_vocab(texts)
        w2i = {w: i for i, w in enumerate(vocab)}
        vecs = np.zeros((len(texts), len(vocab)), dtype=np.float32)
        for i, t in enumerate(texts):
            for w in t.lower().split():
                if w in w2i:
                    vecs[i, w2i[w]] += 1
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1
        return vecs / norms
    except Exception:
        return None


def semantic_query(query_text, kind=None, limit=10, min_score=0.15):
    """Semantic similarity search over the vector index.

    Returns [(score, record)] sorted by descending score.
    """
    if _vector_db is None:
        _rebuild_index()
    if not _vector_db:
        # fallback to keyword query
        return [(1.0, r) for r in query(query_text, kind, limit)]
    try:
        import numpy as np
    except ImportError:
        return [(1.0, r) for r in query(query_text, kind, limit)]
    results = []
    for k, db in _vector_db.items():
        if kind and k != kind:
            continue
        # embed the query with this kind's own vocab (bag-of-words dims must
        # match the index exactly); sentence-transformer embeddings are
        # backend-wide so this is a no-op there
        vec = _embed_batch([query_text], db.get("vocab"))
        if vec is None or db["vectors"].shape[1] != vec.shape[1]:
            continue
        scores = np.dot(db["vectors"], vec[0])
        for i, score in enumerate(scores):
            if score >= min_score:
                results.append((float(score), db["records"][i]))
    results.sort(key=lambda x: x[0], reverse=True)
    return results[:limit]


# ----------------------------------------------------------- public API ----

def write(kind, content, **meta):
    """Store a memory record and return it."""
    return store(kind, content, **meta)


def search(query_text, kind=None, limit=10, semantic=False):
    """Search memory: keyword or semantic."""
    if semantic:
        return semantic_query(query_text, kind, limit)
    return [(1.0, r) for r in query(query_text, kind, limit)]


def stats():
    """Return counts per kind and whether the vector index is available."""
    kinds = {}
    for k, fn in MEMORY_FIELDS.items():
        p = os.path.join(DATA_DIR, fn)
        if os.path.isfile(p):
            kinds[k] = len(_parse_md_file(p))
        else:
            kinds[k] = 0
    has_numpy = False
    try:
        import numpy  # noqa: F401
        has_numpy = True
    except ImportError:
        pass
    return {"kinds": kinds, "total": sum(kinds.values()),
            "vector_index": _vector_db is not None,
            "numpy_available": has_numpy}


def init():
    """Load the vector index at startup."""
    _rebuild_index()


# auto-init
init()