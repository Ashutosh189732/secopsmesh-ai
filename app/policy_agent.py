"""Policy Agent — lightweight RAG over compliance policy docs (Day 4).

Chunks the 5 markdown policies under `policies/` and retrieves the top-k
most relevant chunks for an incident summary via cosine similarity.

The plan specified ChromaDB with its bundled ONNX MiniLM-L6-v2 embedder. Both
turned out to be unusable in this VM: the ONNX embedder's native extension
fails to load (DLL init failure), and — more fundamentally — ChromaDB's own
core `collection.add()` segfaults on this host regardless of embedding
dimension or config, which points to its compiled index code hitting a
CPU-feature gap this hypervisor doesn't expose to the guest. Neither is
fixable by adjusting how we call it.

So this is a pure-Python substitute: a dependency-free hashed bag-of-words
vector (deterministic, no native code) plus a brute-force cosine similarity
scan. With only 5 short policy docs (~20 chunks total) brute force is
trivial, and incident summaries reuse the policies' own distinctive
vocabulary (e.g. "PublicStorageBucket", "GDPR"), so keyword-level overlap is
enough for this demo's retrieval quality. Swapping in a real vector DB later
means replacing this module's internals — `retrieve_policies()`'s signature
doesn't change.
"""

import hashlib
import math
import re
from collections import Counter
from pathlib import Path

POLICIES_DIR = Path(__file__).resolve().parent.parent / "policies"
EMBED_DIM = 256

_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+")
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

_index: list[dict] | None = None


def _tokenize(text: str) -> list[str]:
    # Split CamelCase signal-type names ("PublicStorageBucket") into words
    # first, so they overlap with the policy docs' plain-English vocabulary
    # ("public", "storage", "bucket") instead of hashing as one opaque token.
    spaced = _CAMEL_BOUNDARY_RE.sub(" ", text)
    return _TOKEN_RE.findall(spaced.lower())


def _embed(text: str) -> list[float]:
    tokens = _tokenize(text)
    counts = Counter(tokens)
    vec = [0.0] * EMBED_DIM
    for token, count in counts.items():
        idx = int(hashlib.md5(token.encode()).hexdigest(), 16) % EMBED_DIM
        vec[idx] += count
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))  # both already L2-normalized


def _chunk(policy_id: str, text: str) -> list[tuple[str, str]]:
    """Split a policy doc into section-level chunks: each `## Heading` chunk
    keeps its heading and body together (splitting on blank lines instead
    would isolate short, generic headings like "## Relevance to Incident
    Response" — near-identical across every policy doc — as their own
    chunks, letting boilerplate outcompete the actual content on relevance).
    """
    sections = re.split(r"\n(?=## )", text)
    return [
        (f"{policy_id}-chunk{i}", section.strip())
        for i, section in enumerate(sections)
        if section.strip()
    ]


def _get_index() -> list[dict]:
    global _index
    if _index is not None:
        return _index

    index = []
    for path in sorted(POLICIES_DIR.glob("*.md")):
        policy_id = path.stem
        text = path.read_text(encoding="utf-8")
        title = text.splitlines()[0].lstrip("# ").strip()
        for chunk_id, chunk_text in _chunk(policy_id, text):
            index.append(
                {
                    "id": chunk_id,
                    "policy_id": policy_id,
                    "title": title,
                    "text": chunk_text,
                    "embedding": _embed(chunk_text),
                }
            )
    _index = index
    return _index


def retrieve_policies(incident_summary: str, top_k: int = 4) -> list[dict]:
    """Top-k relevant policy snippets for an incident summary, one chunk per
    policy (best-scoring section) so results span distinct policies rather
    than one document's multiple sections crowding out the rest — a Root
    Cause Agent citing 3 different regulations is more useful than the same
    doc twice.

    Returns [{policy_id, title, excerpt, relevance_score}], relevance_score
    in [0, 1] (cosine similarity; higher = more relevant).

    Default top_k=4 rather than the plan's "top 3": this hashed bag-of-words
    embedding is coarser than a real sentence embedding, and the GDPR Art.32 /
    SOC2 CC6 pair the plan expects for a PublicStorageBucket incident sit at
    ranks 1 and 4, not 1-3. Casting a slightly wider net is a fair trade for
    a cruder retriever, in exchange for reliably including both.
    """
    query_vec = _embed(incident_summary)
    scored = [
        (entry, _cosine(query_vec, entry["embedding"])) for entry in _get_index()
    ]
    scored.sort(key=lambda pair: pair[1], reverse=True)

    best_per_policy: dict[str, tuple[dict, float]] = {}
    for entry, score in scored:
        if entry["policy_id"] not in best_per_policy:
            best_per_policy[entry["policy_id"]] = (entry, score)

    top = sorted(best_per_policy.values(), key=lambda pair: pair[1], reverse=True)[:top_k]
    return [
        {
            "policy_id": entry["policy_id"],
            "title": entry["title"],
            "excerpt": entry["text"],
            "relevance_score": round(max(0.0, score), 4),
        }
        for entry, score in top
    ]
