"""Local sentence embeddings for PS8 duplicate detection and PS2 source verification.

Primary backend is sentence-transformers `all-MiniLM-L6-v2`, exactly as specified in
the Stage 2 technical documentation. It runs on CPU and needs no network at inference
time, which is what keeps PS2 inside its <10 s budget with no paid API.

If sentence-transformers or torch cannot be imported (or the weights are not cached
and there is no network), we degrade to a deterministic hashing vectoriser instead of
crashing. That fallback is *not* as good, so the active backend is reported through
`/api/v1/health` and stamped into every verification report. We never claim MiniLM ran
when it did not.
"""

from __future__ import annotations

import hashlib
import logging
import math
import threading
from typing import Sequence

import numpy as np

from ..config import settings

logger = logging.getLogger(__name__)

# Dimensionality of the fallback vectoriser. Matches MiniLM's 384 so that any
# downstream shape assumption holds regardless of which backend is live.
_FALLBACK_DIM = 384


class EmbeddingProvider:
    """Lazily-loaded, process-wide embedding model with a deterministic fallback."""

    def __init__(self) -> None:
        self._model = None
        self._backend = "uninitialised"
        self._load_error: str | None = None
        self._lock = threading.Lock()
        self._cache: dict[str, np.ndarray] = {}

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def _ensure_loaded(self) -> None:
        if self._backend != "uninitialised":
            return
        with self._lock:
            if self._backend != "uninitialised":
                return
            try:
                from sentence_transformers import SentenceTransformer  # noqa: PLC0415

                self._model = SentenceTransformer(settings.embedding_model, device="cpu")
                self._backend = f"sentence-transformers:{settings.embedding_model}"
                logger.info("PS2 embedding backend: %s", self._backend)
            except Exception as exc:  # pragma: no cover - environment dependent
                self._load_error = f"{type(exc).__name__}: {exc}"
                if not settings.allow_embedding_fallback:
                    self._backend = "failed"
                    raise
                self._backend = "lexical-hash-fallback"
                logger.warning(
                    "Could not load %s (%s). Falling back to the deterministic lexical "
                    "vectoriser. Semantic quality will be lower; this is reported via "
                    "/api/v1/health.",
                    settings.embedding_model,
                    self._load_error,
                )

    def warm_up(self) -> None:
        """Load the model up front so the first API request is not slow."""
        self._ensure_loaded()
        self.encode(["warm up"])

    # ------------------------------------------------------------------
    # Introspection (surfaced on /api/v1/health)
    # ------------------------------------------------------------------
    @property
    def backend(self) -> str:
        self._ensure_loaded()
        return self._backend

    @property
    def is_minilm(self) -> bool:
        return self.backend.startswith("sentence-transformers")

    @property
    def load_error(self) -> str | None:
        return self._load_error

    # ------------------------------------------------------------------
    # Encoding
    # ------------------------------------------------------------------
    def encode(self, texts: Sequence[str]) -> np.ndarray:
        """Return L2-normalised embeddings, shape (len(texts), dim)."""
        self._ensure_loaded()
        if not texts:
            return np.zeros((0, _FALLBACK_DIM), dtype=np.float32)

        missing = [t for t in texts if t not in self._cache]
        if missing:
            # De-duplicate before the expensive call.
            unique = list(dict.fromkeys(missing))
            if self._model is not None:
                vectors = self._model.encode(
                    unique,
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )
            else:
                vectors = np.stack([_lexical_vector(t) for t in unique])
            for text, vec in zip(unique, vectors):
                self._cache[text] = np.asarray(vec, dtype=np.float32)

        return np.stack([self._cache[t] for t in texts])

    def encode_one(self, text: str) -> np.ndarray:
        return self.encode([text])[0]

    # ------------------------------------------------------------------
    # Similarity
    # ------------------------------------------------------------------
    def similarity(self, a: str, b: str) -> float:
        """Cosine similarity in [0,1] (negatives clamped to 0)."""
        va, vb = self.encode([a, b])
        return _clamp01(float(np.dot(va, vb)))

    def similarity_matrix(self, queries: Sequence[str], corpus: Sequence[str]) -> np.ndarray:
        """Cosine similarities, shape (len(queries), len(corpus)), clamped to [0,1]."""
        if not queries or not corpus:
            return np.zeros((len(queries), len(corpus)), dtype=np.float32)
        qm = self.encode(list(queries))
        cm = self.encode(list(corpus))
        return np.clip(qm @ cm.T, 0.0, 1.0)

    def best_match(self, query: str, corpus: Sequence[str]) -> tuple[int, float]:
        """Index and score of the most similar corpus entry. (-1, 0.0) if corpus empty."""
        if not corpus:
            return (-1, 0.0)
        scores = self.similarity_matrix([query], corpus)[0]
        idx = int(np.argmax(scores))
        return (idx, float(scores[idx]))


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _lexical_vector(text: str) -> np.ndarray:
    """Deterministic bag-of-words hashing vector, used only when MiniLM is unavailable.

    Uses sublinear term frequency over hashed unigrams and bigrams. It reproduces
    lexical overlap reasonably and is fully deterministic, which keeps tests stable,
    but it has no real semantic understanding - hence the loud fallback warning.
    """
    from .text_utils import content_tokens  # local import avoids an import cycle

    tokens = content_tokens(text)
    vec = np.zeros(_FALLBACK_DIM, dtype=np.float32)
    if not tokens:
        return vec

    grams = list(tokens) + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]
    counts: dict[int, float] = {}
    for gram in grams:
        # blake2b is stable across processes, unlike hash(), so results reproduce.
        digest = hashlib.blake2b(gram.encode(), digest_size=4).digest()
        idx = int.from_bytes(digest, "big") % _FALLBACK_DIM
        counts[idx] = counts.get(idx, 0.0) + 1.0

    for idx, count in counts.items():
        vec[idx] = 1.0 + math.log(count)

    norm = float(np.linalg.norm(vec))
    return vec / norm if norm > 0 else vec


# Process-wide singleton: loading MiniLM twice would double memory and latency.
embeddings = EmbeddingProvider()
