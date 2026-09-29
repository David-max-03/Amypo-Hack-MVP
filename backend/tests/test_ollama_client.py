"""Ollama client: transient server errors are retried, real outages are surfaced."""

from __future__ import annotations

import httpx
import pytest

from backend.app.config import settings
from backend.app.core import ollama_client as oc


def _patch_transport(monkeypatch, statuses: list[int]) -> list[int]:
    """Serve the given status codes in order; return the list of served codes."""
    served: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        status = statuses[len(served)]
        served.append(status)
        if status == 200:
            return httpx.Response(200, json={"response": '{"ok": true}'})
        return httpx.Response(status, text="llama runner process has terminated")

    real_client = httpx.Client
    monkeypatch.setattr(
        oc.httpx,
        "Client",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    monkeypatch.setattr(settings, "ollama_server_error_backoff_s", 0.0)
    return served


def test_one_off_500_is_retried(monkeypatch):
    served = _patch_transport(monkeypatch, [500, 200])
    assert oc.OllamaClient().generate("p") == '{"ok": true}'
    assert served == [500, 200]


def test_persistent_500_raises_with_ollama_detail(monkeypatch):
    served = _patch_transport(monkeypatch, [500] * (settings.ollama_server_error_retries + 1))
    with pytest.raises(oc.OllamaUnavailable, match="llama runner process has terminated"):
        oc.OllamaClient().generate("p")
    assert len(served) == settings.ollama_server_error_retries + 1


def test_4xx_is_not_retried(monkeypatch):
    served = _patch_transport(monkeypatch, [404])
    with pytest.raises(oc.OllamaUnavailable, match="HTTP 404"):
        oc.OllamaClient().generate("p")
    assert served == [404]
