from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Union

Payload = Union[dict[str, Any], str]
PayloadFactory = Callable[[dict[str, Any]], Payload]
PayloadInput = Union[Payload, PayloadFactory]


@dataclass
class FakeUsage:
    prompt_tokens: int
    completion_tokens: int


class _Message:
    def __init__(self, content: str) -> None:
        self.content = content


class _Choice:
    def __init__(self, content: str) -> None:
        self.message = _Message(content)


class _Response:
    def __init__(self, content: str, usage: FakeUsage | None = None) -> None:
        self.choices = [_Choice(content)]
        if usage is not None:
            self.usage = usage


class _Completions:
    def __init__(self, client: FakeLLMClient) -> None:
        self._client = client

    def create(self, **kwargs: Any) -> _Response:
        return self._client._create(kwargs)


class _Chat:
    def __init__(self, client: FakeLLMClient) -> None:
        self.completions = _Completions(client)


class FakeLLMClient:
    """Stand in for the OpenAI client: client.chat.completions.create(**kwargs).

    payloads: a single payload returned on every call, or a list consumed
        strictly in order. An exhausted list raises IndexError, preserving
        the current pop(0) failure signal.
        Each payload may be a dict (JSON-serialized into message content),
        a str (used verbatim, for invalid-JSON tests), or a callable
        (kwargs) -> dict | str (for per-call dynamic content).
    capture: optional list; raw create(**kwargs) dicts are appended.
    calls: number of create() invocations.
    usage: optional token usage object attached to every fake response.
    """

    def __init__(
        self,
        payloads: PayloadInput | list[PayloadInput],
        *,
        capture: list[dict[str, Any]] | None = None,
        usage: FakeUsage | None = None,
    ) -> None:
        self._payload = None if isinstance(payloads, list) else payloads
        self._payloads = list(payloads) if isinstance(payloads, list) else None
        self._capture = capture
        self._usage = usage
        self.calls = 0
        self.chat = _Chat(self)

    def _create(self, kwargs: dict[str, Any]) -> _Response:
        self.calls += 1
        if self._capture is not None:
            self._capture.append(dict(kwargs))
        payload = self._next_payload()
        if callable(payload):
            payload = payload(kwargs)
        if isinstance(payload, dict):
            return _Response(json.dumps(payload), usage=self._usage)
        if isinstance(payload, str):
            return _Response(payload, usage=self._usage)
        raise TypeError(f"Unsupported fake LLM payload: {type(payload).__name__}")

    def _next_payload(self) -> PayloadInput:
        if self._payloads is not None:
            return self._payloads.pop(0)
        if self._payload is None:
            raise IndexError("Fake LLM payload list is exhausted")
        return self._payload
