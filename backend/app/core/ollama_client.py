"""Thin client for the local Ollama runtime (PS8 generation + PS2 self-consistency).

Ollama is the only model runtime in the stack. There is no paid third-party API
anywhere, which both problem statements require as a hard constraint.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

from ..config import settings

logger = logging.getLogger(__name__)


class OllamaUnavailable(RuntimeError):
    """Raised when the local Ollama runtime cannot be reached or the model is missing."""


@dataclass
class OllamaStatus:
    reachable: bool
    host: str
    model: str
    model_available: bool
    models_present: list[str]
    detail: str


class OllamaClient:
    def __init__(self, host: str | None = None, model: str | None = None) -> None:
        self.host = (host or settings.ollama_host).rstrip("/")
        self.model = model or settings.ollama_model

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------
    def status(self) -> OllamaStatus:
        """Non-throwing health probe used by /api/v1/health."""
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(f"{self.host}/api/tags")
                resp.raise_for_status()
                names = [m.get("name", "") for m in resp.json().get("models", [])]
        except Exception as exc:
            return OllamaStatus(
                reachable=False,
                host=self.host,
                model=self.model,
                model_available=False,
                models_present=[],
                detail=f"{type(exc).__name__}: {exc}",
            )

        # Ollama reports tags as "name:tag"; treat a bare name as matching ":latest".
        available = any(
            n == self.model or n.split(":")[0] == self.model.split(":")[0] for n in names
        )
        return OllamaStatus(
            reachable=True,
            host=self.host,
            model=self.model,
            model_available=available,
            models_present=names,
            detail="ok" if available else f"model {self.model!r} not pulled",
        )

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------
    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float | None = None,
        timeout_s: float | None = None,
        json_mode: bool = True,
        max_tokens: int | None = None,
    ) -> str:
        """Run a single completion and return the raw text the model produced.

        `json_mode` asks Ollama to constrain output to valid JSON. We still run the
        tolerant parser over the result because constrained decoding can emit JSON
        that is well-formed but does not match our schema.
        """
        payload: dict = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": (
                    settings.generation_temperature if temperature is None else temperature
                ),
                "top_p": settings.generation_top_p,
                "num_predict": max_tokens or settings.max_generation_tokens,
            },
        }
        if system:
            payload["system"] = system
        if json_mode:
            payload["format"] = "json"

        timeout = timeout_s or settings.ollama_timeout_s
        try:
            with httpx.Client(timeout=timeout) as client:
                # Ollama occasionally answers a healthy request with a one-off 5xx
                # (observed mid-batch; the identical request succeeded on replay).
                # Retry those rather than letting one blip end a whole batch.
                for server_try in range(settings.ollama_server_error_retries + 1):
                    resp = client.post(f"{self.host}/api/generate", json=payload)
                    if resp.status_code < 500 or server_try == settings.ollama_server_error_retries:
                        break
                    logger.warning(
                        "Ollama HTTP %s (%s); retrying %s/%s",
                        resp.status_code,
                        resp.text[:200],
                        server_try + 1,
                        settings.ollama_server_error_retries,
                    )
                    time.sleep(settings.ollama_server_error_backoff_s)
                resp.raise_for_status()
                return resp.json().get("response", "")
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:200].strip()
            raise OllamaUnavailable(
                f"Ollama returned HTTP {exc.response.status_code} for model "
                f"{self.model!r}" + (f": {detail}" if detail else "")
                + f". If the model is missing, run: ollama pull {self.model}"
            ) from exc
        except Exception as exc:
            raise OllamaUnavailable(
                f"Could not reach Ollama at {self.host} ({type(exc).__name__}: {exc}). "
                "Start it with: ollama serve"
            ) from exc


ollama = OllamaClient()
