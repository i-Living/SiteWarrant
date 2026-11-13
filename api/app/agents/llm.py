import json
import os
import re
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, Field

DEFAULT_BASE_URL = "https://opencode.ai/zen/go/v1"
DEFAULT_MODEL = "deepseek-v4.1-flash"
# Cloudflare in front of the provider answers 1010 to a request without a user agent, and
# the Go plan routes only requests that carry a session id.
USER_AGENT = "SiteWarrant/0.1 (+https://github.com/i-Living/SiteWarrant)"


class LlmError(RuntimeError):
    """The provider failed, timed out, or answered with something unusable."""


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class LlmReply(BaseModel):
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0


class LlmClient(Protocol):
    """What the agent loop needs from a model. Tests replace it with a cassette."""

    model: str

    async def complete(
        self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LlmReply: ...


def parse_reply(body: dict[str, Any]) -> LlmReply:
    """Read an OpenAI-shaped completion into the narrow shape the loop uses."""
    choices = body.get("choices") or []
    if not choices:
        raise LlmError(f"provider returned no choices: {str(body)[:300]}")
    message = choices[0].get("message") or {}
    usage = body.get("usage") or {}
    calls: list[ToolCall] = []
    for item in message.get("tool_calls") or []:
        function = item.get("function") or {}
        raw = function.get("arguments") or "{}"
        try:
            arguments = json.loads(raw) if isinstance(raw, str) else dict(raw)
        except json.JSONDecodeError as error:
            raise LlmError(f"tool arguments are not JSON: {raw[:200]}") from error
        calls.append(
            ToolCall(
                id=str(item.get("id") or uuid.uuid4()),
                name=str(function.get("name") or ""),
                arguments=arguments,
            )
        )
    return LlmReply(
        content=message.get("content"),
        tool_calls=calls,
        finish_reason=choices[0].get("finish_reason"),
        tokens_in=int(usage.get("prompt_tokens") or 0),
        tokens_out=int(usage.get("completion_tokens") or 0),
    )


class OpenAiCompatibleClient:
    """The production client: one OpenAI-compatible endpoint, one model.

    The provider is OpenCode Zen Go with deepseek-v4.1-flash, the decision recorded in
    docs/PLAN.md section 17. Nothing here is provider-specific except the two headers the
    gateway requires.
    """

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str | None = None,
        session_id: str | None = None,
        timeout_s: float = 120.0,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.environ.get("SITEWARRANT_LLM_API_KEY") or ""
        if not self.api_key:
            self.api_key = _key_from_hermes_env() or ""
        self.session_id = session_id or f"sitewarrant-{uuid.uuid4()}"
        self.timeout_s = timeout_s

    async def complete(
        self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LlmReply:
        if not self.api_key:
            raise LlmError("no API key: set SITEWARRANT_LLM_API_KEY or OPENCODE_GO_API_KEY")
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            "x-opencode-session": self.session_id,
        }
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions", json=payload, headers=headers
                )
        except httpx.HTTPError as error:
            detail = str(error) or repr(error)
            raise LlmError(
                f"{self.model} request failed after {self.timeout_s:.0f} s: "
                f"{type(error).__name__}: {detail}"
            ) from error
        if response.status_code >= 400:
            raise LlmError(
                f"{self.model} answered HTTP {response.status_code}: {response.text[:300]}"
            )
        try:
            reply = parse_reply(response.json())
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            # A 2xx with a body the client cannot read is a provider failure like any other: it has
            # to arrive as LlmError, or an agent run and the chief narration get an exception they
            # are not allowed to treat as a failed call.
            raise LlmError(
                f"{self.model} answered with an unusable body: {response.text[:300]}"
            ) from error
        reply.latency_ms = int((time.monotonic() - started) * 1000)
        return reply


def _key_from_hermes_env() -> str | None:
    """Fall back to the key the local agent harness already has, without copying it."""
    env_file = Path.home() / ".hermes/profiles/dev/.env"
    if not env_file.exists():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("OPENCODE_GO_API_KEY="):
            return stripped.split("=", 1)[1].strip().strip('"').strip("'")
    return None


PLACEHOLDER = re.compile(r"\{\{first:([a-z_]+)\}\}")


class CassetteClient:
    """A recorded conversation, replayed in order.

    The plan calls for tests on cassettes: the loop, the validator and the prompts can be
    exercised without a network call, and the recorded exchange is the fixture a reviewer
    reads to see what the agent actually did.

    A recording cannot contain a real observation id, because ids are generated per audit, so
    a cassette may write `{{first:contrast}}` and the client substitutes the first observation
    id of that channel in the audit under test. The substitution is explicit and never
    invents an id: if the audit has no such channel, the call fails.
    """

    def __init__(
        self,
        path: Path,
        *,
        record: bool = False,
        model: str = DEFAULT_MODEL,
        resolve: Callable[[str], str] | None = None,
    ) -> None:
        self.path = path
        self.record = record
        self.model = model
        self.resolve = resolve
        self.index = 0
        self.recorded: list[dict[str, Any]] = []
        self.interactions: list[dict[str, Any]] = []
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            self.interactions = data.get("interactions") or []

    async def complete(
        self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LlmReply:
        if self.index >= len(self.interactions):
            raise LlmError(
                f"cassette {self.path.name} has {len(self.interactions)} interaction(s), "
                f"the loop asked for number {self.index + 1}"
            )
        interaction = self.interactions[self.index]
        self.index += 1
        if self.resolve is not None:
            interaction = {"response": self._substitute(interaction["response"])}
        self.recorded.append(
            {
                "request": {"messages": messages, "tools": tools},
                "response": interaction["response"],
            }
        )
        return parse_reply(interaction["response"])

    def _substitute(self, value: Any) -> Any:
        if isinstance(value, str):

            def replace(match: re.Match[str]) -> str:
                if self.resolve is None:
                    raise LlmError(f"cassette placeholder {match.group(0)} needs a resolver")
                return self.resolve(match.group(1))

            return PLACEHOLDER.sub(replace, value)
        if isinstance(value, dict):
            return {key: self._substitute(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._substitute(item) for item in value]
        return value

    def save(self) -> None:
        if not self.record:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"model": self.model, "interactions": self.recorded}, indent=2),
            encoding="utf-8",
        )
