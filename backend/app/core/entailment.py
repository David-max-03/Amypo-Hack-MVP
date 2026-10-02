"""Local entailment model (PS2).

Source grounding used to mean "the corpus has a sentence about this, in these
words". That cannot tell a statement from its opposite: "TCP is a connectionless
protocol" shares its topic and its vocabulary with the entry that says TCP is
connection-oriented. A natural-language-inference cross-encoder reads the corpus
sentence and the claim together and says whether the sentence entails the claim,
contradicts it, or neither.

Like the embedding model it is local, runs on CPU and is baked into the Docker
image. If it cannot be loaded, PS2 falls back to the similarity + keyword rule and
says so on /api/v1/health - the fallback is reported, never silent.
"""

from __future__ import annotations

import logging
import threading

from ..config import settings

logger = logging.getLogger(__name__)


class EntailmentModel:
    def __init__(self) -> None:
        self._model = None
        self._state = "uninitialised"
        self._load_error: str | None = None
        self._labels: dict[str, int] = {}
        self._lock = threading.Lock()
        self._cache: dict[tuple[str, str], tuple[float, float]] = {}

    def _ensure_loaded(self) -> None:
        if self._state != "uninitialised":
            return
        with self._lock:
            if self._state != "uninitialised":
                return
            if not settings.entailment_enabled:
                self._state = "disabled"
                return
            try:
                from sentence_transformers import CrossEncoder  # noqa: PLC0415

                model = CrossEncoder(settings.entailment_model, device="cpu")
                labels = {str(v).lower(): int(k) for k, v in model.model.config.id2label.items()}
                if not {"entailment", "contradiction"} <= set(labels):
                    raise ValueError(f"not an NLI model: labels {sorted(labels)}")
                self._model, self._labels, self._state = model, labels, "ready"
                logger.info("PS2 entailment backend: %s", settings.entailment_model)
            except Exception as exc:  # pragma: no cover - environment dependent
                self._load_error = f"{type(exc).__name__}: {exc}"
                self._state = "unavailable"
                logger.warning(
                    "Could not load the entailment model %s (%s). PS2 falls back to "
                    "similarity + keyword grounding; this is reported via /api/v1/health.",
                    settings.entailment_model, self._load_error,
                )

    @property
    def available(self) -> bool:
        self._ensure_loaded()
        return self._state == "ready"

    @property
    def backend(self) -> str:
        self._ensure_loaded()
        return settings.entailment_model if self._state == "ready" else f"{self._state} (similarity + keyword fallback)"

    @property
    def load_error(self) -> str | None:
        return self._load_error

    def warm_up(self) -> None:
        if self.available:
            self.judge(["A stack is a last-in, first-out structure."], "A stack is last-in, first-out.")

    def judge(self, premises: list[str], hypothesis: str) -> list[tuple[float, float]]:
        """(entailment, contradiction) probability of `hypothesis` given each premise."""
        if not premises:
            return []
        if not self.available:
            raise RuntimeError("entailment model is not available")
        missing = [p for p in dict.fromkeys(premises) if (p, hypothesis) not in self._cache]
        if missing:
            with self._lock:
                probs = self._model.predict([(p, hypothesis) for p in missing], apply_softmax=True)
            for premise, row in zip(missing, probs):
                self._cache[(premise, hypothesis)] = (
                    float(row[self._labels["entailment"]]),
                    float(row[self._labels["contradiction"]]),
                )
        return [self._cache[(p, hypothesis)] for p in premises]


entailment = EntailmentModel()
