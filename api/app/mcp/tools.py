"""Read-only fact access for agents, scoped to one audit.

Every function here takes the audit id explicitly, so a tool cannot reach another audit's
facts even if the model asks for an id it saw somewhere else.
"""

import base64
import uuid
from typing import Any

from sqlalchemy import select

from app.core.db import session_scope
from app.core.models import Observation, Page, Snapshot
from app.rules import corpus

MAX_ROWS = 50
SUMMARY_CHARS = 240
# A full-page PNG above this is refused rather than silently shrunk: a downscale would change
# what the model sees, and the refusal is a fact the report can carry.
MAX_IMAGE_BYTES = 4_000_000
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _short(payload: dict[str, Any], limit: int = SUMMARY_CHARS) -> str:
    import json

    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= limit else text[:limit] + "…"


async def list_pages(audit_id: uuid.UUID) -> list[dict[str, Any]]:
    async with session_scope() as session:
        rows = await session.execute(
            select(Page).where(Page.audit_id == audit_id).order_by(Page.page_key)
        )
        return [
            {
                "page_key": page.page_key,
                "url": page.url,
                "status_code": page.status_code,
                "render_mode": page.render_mode,
            }
            for page in rows.scalars()
        ]


async def list_observations(
    audit_id: uuid.UUID,
    *,
    tool: str | None = None,
    rule_ref: str | None = None,
    viewport: str | None = None,
    limit: int = MAX_ROWS,
) -> list[dict[str, Any]]:
    async with session_scope() as session:
        query = (
            select(Observation)
            .join(Page, Observation.page_id == Page.id)
            .where(Page.audit_id == audit_id)
            .order_by(Observation.tool, Observation.kind, Observation.id)
            .limit(max(1, min(limit, MAX_ROWS)))
        )
        if tool:
            query = query.where(Observation.tool == tool)
        if rule_ref:
            query = query.where(Observation.rule_ref == rule_ref)
        if viewport:
            query = query.where(Observation.viewport == viewport)
        rows = await session.execute(query)
        return [
            {
                "observation_id": str(row.id),
                "tool": row.tool,
                "kind": row.kind,
                "rule_ref": row.rule_ref,
                "viewport": row.viewport,
                "summary": _short(row.payload),
            }
            for row in rows.scalars()
        ]


async def get_observation(audit_id: uuid.UUID, observation_id: str) -> dict[str, Any]:
    try:
        parsed = uuid.UUID(observation_id)
    except ValueError:
        return {"error": f"{observation_id} is not an observation id"}
    async with session_scope() as session:
        row = await session.execute(
            select(Observation)
            .join(Page, Observation.page_id == Page.id)
            .where(Page.audit_id == audit_id, Observation.id == parsed)
        )
        observation = row.scalar_one_or_none()
        if observation is None:
            return {"error": f"observation {observation_id} does not exist in this audit"}
        return {
            "observation_id": str(observation.id),
            "tool": observation.tool,
            "kind": observation.kind,
            "rule_ref": observation.rule_ref,
            "viewport": observation.viewport,
            "payload": observation.payload,
        }


async def channel_report(
    audit_id: uuid.UUID,
    *,
    channel: str,
    viewport: str | None = None,
    page_key: str | None = None,
) -> list[dict[str, Any]]:
    """All observations of one channel, with full payloads.

    This is the drill-down: the digest in the prompt is abbreviated, and an agent that needs
    the whole DOM snapshot or every axe node asks for it here.
    """
    async with session_scope() as session:
        query = (
            select(Observation)
            .join(Page, Observation.page_id == Page.id)
            .where(Page.audit_id == audit_id, Observation.tool == channel)
            .order_by(Observation.viewport, Observation.kind)
            .limit(MAX_ROWS)
        )
        if viewport:
            query = query.where(Observation.viewport == viewport)
        if page_key:
            query = query.where(Page.page_key == page_key)
        rows = await session.execute(query)
        return [
            {
                "observation_id": str(row.id),
                "kind": row.kind,
                "rule_ref": row.rule_ref,
                "viewport": row.viewport,
                "payload": row.payload,
            }
            for row in rows.scalars()
        ]


async def screenshot_artifact(
    audit_id: uuid.UUID, *, viewport: str | None = None
) -> list[dict[str, Any]]:
    """Where the captures are, and whether this run stored them.

    This lists keys only: `page_image` is the tool that returns the bytes for one viewport.
    """
    async with session_scope() as session:
        query = (
            select(Snapshot, Page)
            .join(Page, Snapshot.page_id == Page.id)
            .where(Page.audit_id == audit_id)
            .order_by(Snapshot.viewport)
        )
        if viewport:
            query = query.where(Snapshot.viewport == viewport)
        rows = await session.execute(query)
        return [
            {
                "viewport": snapshot.viewport,
                "page_key": page.page_key,
                "screenshot_key": snapshot.screenshot_key,
                "width": None,
                "height": None,
            }
            for snapshot, page in rows.all()
        ]


async def page_image(
    audit_id: uuid.UUID, *, viewport: str, page_key: str | None = None
) -> dict[str, Any]:
    """The stored full-page screenshot of one viewport, as bytes a model can look at.

    Decision 5a in docs/PLAN.md section 17: one capture per viewport, three viewports. The
    image is evidence of appearance, not a measurement — every number in a finding still has
    to come from an observation — so the answer carries the capture's own dimensions beside
    the bytes and refuses, rather than guesses, when there is nothing to show.
    """
    async with session_scope() as session:
        query = (
            select(Snapshot, Page)
            .join(Page, Snapshot.page_id == Page.id)
            .where(Page.audit_id == audit_id, Snapshot.viewport == viewport)
            .order_by(Page.page_key)
        )
        if page_key:
            query = query.where(Page.page_key == page_key)
        found = (await session.execute(query.limit(1))).first()
        if found is None:
            return {"error": f"this audit has no capture at {viewport}"}
        snapshot, page = found
        facts = (
            (
                await session.execute(
                    select(Observation).where(
                        Observation.page_id == page.id,
                        Observation.tool == "screenshot",
                        Observation.viewport == viewport,
                    )
                )
            )
            .scalars()
            .first()
        )

    if not snapshot.screenshot_key:
        return {
            "error": (
                "this run stored no screenshot bytes (artifacts were off), "
                "so there is no image to look at"
            )
        }
    from app.audit import artifact_path

    try:
        path = artifact_path(snapshot.screenshot_key)
    except ValueError:
        return {"error": "the stored screenshot key escapes the artifacts directory"}
    if not path.exists():
        return {"error": f"the screenshot file is missing on disk: {snapshot.screenshot_key}"}
    data = path.read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        return {"error": "the stored screenshot is not a PNG"}
    if len(data) > MAX_IMAGE_BYTES:
        return {
            "error": (
                f"the screenshot is {len(data)} bytes, above the {MAX_IMAGE_BYTES}-byte limit "
                f"for one request; visual review is skipped at {viewport}"
            )
        }
    payload = facts.payload if facts is not None else {}
    return {
        "page_key": page.page_key,
        "viewport": snapshot.viewport,
        "mime_type": "image/png",
        "data_b64": base64.b64encode(data).decode("ascii"),
        "bytes": len(data),
        # The dimensions below are the screenshot observation's; a tool that hands over a
        # number also names the row it came from, so the model can cite it.
        "observation_id": str(facts.id) if facts is not None else None,
        "width": payload.get("width"),
        "height": payload.get("height"),
        "clipped": bool(payload.get("clipped")),
    }


async def rules_lookup(query: str, *, limit: int = 4) -> list[dict[str, Any]]:
    """Retrieve corpus chunks by vector similarity, from the database when it is indexed."""
    from app.rules.store import search_indexed

    return await search_indexed(query, limit=limit)


def corpus_fallback(query: str, *, limit: int = 4) -> list[dict[str, Any]]:
    """The in-process retrieval, used when the database has no corpus yet."""
    return [
        {
            "id": entry.id,
            "kind": entry.kind,
            "title": entry.title,
            "body": entry.body,
            "source": entry.source,
            "url": entry.url,
        }
        for entry in corpus.search(query, limit=limit)
    ]
