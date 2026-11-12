import hashlib
import json
import math
import re
from collections.abc import Iterable, Sequence
from functools import lru_cache
from itertools import pairwise
from pathlib import Path

from pydantic import BaseModel

from app.rules.catalog import Category, Severity

CORPUS_DIR = Path(__file__).resolve().parents[3] / "rules"
CORPUS_FILE = CORPUS_DIR / "claims.jsonl"
EMBEDDING_DIM = 1024
TOKEN = re.compile(r"[a-z0-9]+")
STOPWORDS = frozenset(
    [
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "to",
        "in",
        "for",
        "on",
        "with",
        "is",
        "are",
        "be",
        "as",
        "at",
        "by",
        "that",
        "this",
        "it",
        "its",
        "from",
        "not",
        "no",
        "than",
        "then",
        "when",
        "where",
        "which",
        "who",
        "whom",
        "what",
        "how",
        "all",
        "any",
        "each",
        "more",
        "most",
        "other",
        "some",
        "such",
        "only",
        "own",
        "same",
        "so",
        "too",
        "very",
        "can",
        "will",
        "just",
        "should",
        "must",
        "may",
        "might",
        "do",
        "does",
        "did",
        "has",
        "have",
        "had",
    ]
)


class CorpusEntry(BaseModel):
    """One thing this project is willing to claim, with the text an agent may cite.

    Criteria are the external standard; claims are this project's assertions. An agent
    finding cites a claim id, and an accessibility finding also cites the criterion it
    rests on, so the report can quote the standard instead of paraphrasing it.
    """

    id: str
    kind: str
    title: str
    body: str
    tags: tuple[str, ...] = ()
    url: str | None = None
    source: str | None = None
    category: Category | None = None
    severity: Severity | None = None
    suggested_fix: str | None = None
    observation_tools: tuple[str, ...] = ()
    wcag: str | None = None

    @property
    def is_claim(self) -> bool:
        return self.kind == "claim"

    @property
    def is_criterion(self) -> bool:
        return self.kind == "criterion"


def tokens(text: str) -> list[str]:
    words = [word for word in TOKEN.findall(text.lower()) if word not in STOPWORDS]
    bigrams = [f"{first} {second}" for first, second in pairwise(words)]
    return words + bigrams


def embed(text: str) -> list[float]:
    """A deterministic hashed embedding: no model, no network, same vector everywhere.

    Feature hashing over words and bigrams is weaker than a trained model, and the plan
    calls for pgvector because a real embedding model can replace this without changing the
    schema. Until an embedding endpoint is available, this keeps retrieval reproducible:
    the same query returns the same chunks on every machine and in every test.
    """
    vector = [0.0] * EMBEDDING_DIM
    for token in tokens(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % EMBEDDING_DIM
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return vector
    return [value / norm for value in vector]


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


@lru_cache(maxsize=1)
def entries() -> tuple[CorpusEntry, ...]:
    """The corpus, read once per process. Order is the file order, which is stable."""
    loaded: list[CorpusEntry] = []
    for line in CORPUS_FILE.read_text(encoding="utf-8").splitlines():
        if line.strip():
            loaded.append(CorpusEntry.model_validate(json.loads(line)))
    return tuple(loaded)


@lru_cache(maxsize=1)
def _vectors() -> tuple[tuple[str, tuple[float, ...]], ...]:
    return tuple(
        (entry.id, tuple(embed(f"{entry.title} {entry.body} {' '.join(entry.tags)}")))
        for entry in entries()
    )


def claims() -> tuple[CorpusEntry, ...]:
    return tuple(entry for entry in entries() if entry.is_claim)


def criteria() -> tuple[CorpusEntry, ...]:
    return tuple(entry for entry in entries() if entry.is_criterion)


def entry_by_id(entry_id: str) -> CorpusEntry | None:
    return next((entry for entry in entries() if entry.id == entry_id), None)


def claim_by_id(claim_id: str) -> CorpusEntry | None:
    entry = entry_by_id(claim_id)
    return entry if entry is not None and entry.is_claim else None


def criterion_by_id(criterion_id: str) -> CorpusEntry | None:
    entry = entry_by_id(criterion_id)
    return entry if entry is not None and entry.is_criterion else None


def claims_for(category: Category) -> tuple[CorpusEntry, ...]:
    return tuple(entry for entry in claims() if entry.category == category)


def search(query: str, *, limit: int = 4, kinds: Iterable[str] | None = None) -> list[CorpusEntry]:
    """Rank the corpus against a query, deterministically.

    Ties break on id, so the same query returns the same order in tests and in production.
    """
    allowed = set(kinds) if kinds is not None else {"claim", "criterion"}
    query_vector = embed(query)
    scored = [
        (cosine(query_vector, vector), entry_id)
        for entry_id, vector in _vectors()
        if (entry := entry_by_id(entry_id)) is not None and entry.kind in allowed
    ]
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return [entry for score, entry_id in scored[:limit] if (entry := entry_by_id(entry_id))]


def corpus_digest() -> str:
    """Digest of the corpus text, part of agent_version."""
    payload = "\n".join(
        f"{entry.id}\t{entry.title}\t{entry.body}\t{entry.severity or ''}" for entry in entries()
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
