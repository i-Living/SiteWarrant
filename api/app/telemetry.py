"""Spans for one audit: audit → page → agent → tool call → model call.

The records use OpenTelemetry's vocabulary — trace id, span id, parent id, name, start and end,
attributes — and are written as JSON lines, so an exporter can read them without this module. The
SDK is deliberately not a dependency: an audit runs one process, the interesting tree is small, and
a span recorder that cannot fail the audit is worth more here than a collector.

`current_trace_id()` is what lets a model call written by another module carry the trace it belongs
to; without it the column would be decorative.
"""

from __future__ import annotations

import json
import secrets
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_current_span: ContextVar[str | None] = ContextVar("sitewarrant_span", default=None)
_current_trace: ContextVar[str | None] = ContextVar("sitewarrant_trace", default=None)


def new_id() -> str:
    return secrets.token_hex(16)


def current_trace_id() -> str | None:
    return _current_trace.get()


def current_span_id() -> str | None:
    return _current_span.get()


@dataclass
class Span:
    name: str
    trace_id: str
    span_id: str = field(default_factory=new_id)
    parent_id: str | None = None
    started_unix: float = field(default_factory=time.time)
    ended_unix: float | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"
    error: str | None = None

    @property
    def duration_ms(self) -> int:
        if self.ended_unix is None:
            return 0
        return int((self.ended_unix - self.started_unix) * 1000)

    def as_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_id,
            "name": self.name,
            "start_unix_ns": int(self.started_unix * 1_000_000_000),
            "end_unix_ns": None
            if self.ended_unix is None
            else int(self.ended_unix * 1_000_000_000),
            "duration_ms": self.duration_ms,
            "status": self.status,
            "error": self.error,
            "attributes": self.attributes,
        }


class Tracer:
    """Collects spans for one operation and keeps the nesting honest."""

    def __init__(self, trace_id: str | None = None) -> None:
        self.trace_id = trace_id or new_id()
        self.spans: list[Span] = []

    @contextmanager
    def span(self, name: str, **attributes: Any) -> Iterator[Span]:
        parent = _current_span.get()
        span = Span(
            name=name,
            trace_id=self.trace_id,
            parent_id=parent,
            attributes={key: value for key, value in attributes.items() if value is not None},
        )
        span_token = _current_span.set(span.span_id)
        trace_token = _current_trace.set(self.trace_id)
        try:
            yield span
        except BaseException as error:
            span.status = "error"
            span.error = f"{type(error).__name__}: {error}"[:500]
            raise
        finally:
            span.ended_unix = time.time()
            self.spans.append(span)
            _current_span.reset(span_token)
            _current_trace.reset(trace_token)

    def to_jsonl(self) -> str:
        return "".join(json.dumps(span.as_dict(), sort_keys=True) + "\n" for span in self.spans)

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_jsonl(), encoding="utf-8")
        return path

    def summary(self) -> dict[str, int]:
        """How many spans of each name — enough for a report to prove the tree exists."""
        counts: dict[str, int] = {}
        for span in self.spans:
            counts[span.name] = counts.get(span.name, 0) + 1
        return dict(sorted(counts.items()))
