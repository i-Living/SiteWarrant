"""The rule corpus in Postgres, queried by vector similarity.

The file in `rules/claims.jsonl` is the source of truth and the thing a reviewer reads; this
module keeps the database copy in step with it and answers retrieval queries against pgvector.
"""

import json
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import session_scope
from app.core.models import RuleRecord
from app.rules import corpus


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.6f}" for value in vector) + "]"


async def ensure_indexed(session: AsyncSession) -> int:
    """Reindex when the corpus text changed, and report how many chunks are stored.

    Indexing is idempotent and keyed on the corpus digest, so a changed claim body cannot
    leave stale vectors behind and an unchanged corpus costs one query.
    """
    digest = corpus.corpus_digest()
    existing = await session.execute(select(RuleRecord.corpus_digest).limit(1))
    if existing.scalar_one_or_none() == digest:
        count = await session.execute(select(RuleRecord.id))
        return len(count.scalars().all())

    await session.execute(delete(RuleRecord))
    for entry in corpus.entries():
        session.add(
            RuleRecord(
                id=entry.id,
                kind=entry.kind,
                title=entry.title,
                body=entry.body,
                source=entry.source,
                category=entry.category,
                severity=entry.severity,
                suggested_fix=entry.suggested_fix,
                url=entry.url,
                wcag=entry.wcag,
                tags=list(entry.tags),
                observation_tools=list(entry.observation_tools),
                embedding=corpus.embed(f"{entry.title} {entry.body} {' '.join(entry.tags)}"),
                corpus_digest=digest,
            )
        )
    await session.commit()
    return len(corpus.entries())


async def search_indexed(query: str, *, limit: int = 4) -> list[dict[str, Any]]:
    """Nearest chunks by cosine distance, with the in-process corpus as the fallback.

    The fallback keeps the tool honest when the database has not been indexed yet: it returns
    the same entries, computed the same way, instead of pretending there are no rules.
    """
    vector = corpus.embed(query)
    async with session_scope() as session:
        try:
            rows = await session.execute(
                select(RuleRecord)
                .order_by(text("rules.embedding <=> :vector"))
                .params(vector=_vector_literal(vector))
                .limit(limit)
            )
            records = list(rows.scalars())
        except Exception:
            records = []
        if not records:
            return [
                {
                    "id": entry.id,
                    "kind": entry.kind,
                    "title": entry.title,
                    "body": entry.body,
                    "source": entry.source,
                    "url": entry.url,
                    "category": entry.category,
                    "severity": entry.severity,
                    "wcag": entry.wcag,
                }
                for entry in corpus.search(query, limit=limit)
            ]
        return [
            {
                "id": record.id,
                "kind": record.kind,
                "title": record.title,
                "body": record.body,
                "source": record.source,
                "url": record.url,
                "category": record.category,
                "severity": record.severity,
                "wcag": record.wcag,
            }
            for record in records
        ]


def dump_index() -> str:
    """The indexed view as JSON, for the CLI to print after indexing."""
    return json.dumps([entry.model_dump() for entry in corpus.entries()], ensure_ascii=False)
