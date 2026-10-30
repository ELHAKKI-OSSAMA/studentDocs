"""OpenAI-compatible chat completions client (Ollama, vLLM, LM Studio, OpenAI-compatible APIs).

Plain httpx, no SDK. Privacy guarantees enforced here:
- the endpoint is classified once: `is_local` only if every address of the host is private / loopback;
  a non-local endpoint is refused unless AI_ALLOW_EXTERNAL=true (explicit configuration decision);
- every outgoing request must target that single host (event hook), redirects are not followed and
  environment proxies are ignored: data cannot be sent anywhere else;
- no tools / functions are ever declared, and an answer containing a tool call is rejected.
"""

import ipaddress
import json
import socket
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

from app.ai.provider import LLMInvalidOutput, LLMNotAllowed, LLMRefused, LLMResult, LLMUnavailable


def endpoint_is_local(base_url: str) -> bool:
    """True when the host resolves only to private, loopback or link-local addresses."""
    host = urlsplit(base_url).hostname
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False  # cannot verify: treated as external
    addresses = {info[4][0] for info in infos}
    if not addresses:
        return False
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
        if not (ip.is_private or ip.is_loopback or ip.is_link_local) or ip.is_unspecified:
            return False
    return True


@dataclass
class OpenAICompatibleProvider:
    base_url: str
    model: str
    api_key: str | None = None
    timeout: float = 60.0
    allow_external: bool = False
    json_mode: str = "json_schema"
    name: str = "openai_compatible"
    is_local: bool = field(init=False)

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        self._host = urlsplit(self.base_url).hostname or ""
        self.is_local = endpoint_is_local(self.base_url)

    def _guard(self, request: httpx.Request) -> None:
        if request.url.host != self._host:
            raise LLMNotAllowed(f"request to an unexpected host refused: {request.url.host}")

    def complete_json(self, system: str, user: str, schema: dict, *, max_tokens: int) -> LLMResult:
        if not self.is_local and not self.allow_external:
            raise LLMNotAllowed("external AI endpoint without AI_ALLOW_EXTERNAL")
        if self.json_mode == "json_schema":
            response_format = {
                "type": "json_schema",
                "json_schema": {"name": "email_extraction", "schema": schema, "strict": False},
            }
        else:
            response_format = {"type": "json_object"}
        payload = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": response_format,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        started = time.monotonic()
        try:
            with httpx.Client(
                timeout=self.timeout,
                follow_redirects=False,
                trust_env=False,
                event_hooks={"request": [self._guard]},
            ) as client:
                response = client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise LLMUnavailable("timeout") from exc
        except httpx.TransportError as exc:
            raise LLMUnavailable("connection_failed") from exc
        latency = int((time.monotonic() - started) * 1000)
        if response.status_code == 429 or response.status_code >= 500:
            raise LLMUnavailable(f"http_{response.status_code}")
        if response.status_code != 200:
            raise LLMRefused(f"http_{response.status_code}")
        try:
            body = response.json()
            choice = body["choices"][0]
            message = choice["message"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMInvalidOutput("malformed response") from exc
        if (
            message.get("tool_calls")
            or message.get("function_call")
            or choice.get("finish_reason")
            in (
                "tool_calls",
                "function_call",
            )
        ):
            raise LLMInvalidOutput("tool call refused")
        if choice.get("finish_reason") == "length":
            raise LLMInvalidOutput("truncated answer")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise LLMInvalidOutput("empty answer")
        usage = body.get("usage") or {}
        return LLMResult(
            content=content,
            latency_ms=latency,
            tokens_in=usage.get("prompt_tokens"),
            tokens_out=usage.get("completion_tokens"),
        )


def parse_json_object(content: str) -> dict:
    """Strict JSON object. A fenced block (```json … ```) is tolerated, nothing else around it."""
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMInvalidOutput("not JSON") from exc
    if not isinstance(value, dict):
        raise LLMInvalidOutput("not a JSON object")
    return value
