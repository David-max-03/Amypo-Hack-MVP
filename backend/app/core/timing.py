"""Lightweight timing instrumentation.

PS2 has a hard <10 s per-response budget, so every stage records how long it took
and the numbers are returned in the API response rather than only logged. We report
measured times; we never assert a latency we have not observed.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field

from ..config import settings

logger = logging.getLogger(__name__)


@dataclass
class Stopwatch:
    """Accumulates named stage durations in milliseconds."""

    stages: dict[str, float] = field(default_factory=dict)
    _started: float = field(default_factory=time.perf_counter)

    @contextmanager
    def stage(self, name: str):
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            self.stages[name] = round(self.stages.get(name, 0.0) + elapsed_ms, 2)
            if settings.log_timings:
                logger.info("[timing] %-28s %8.1f ms", name, elapsed_ms)

    @property
    def total_ms(self) -> float:
        return round((time.perf_counter() - self._started) * 1000.0, 2)

    def as_dict(self) -> dict[str, float]:
        return {**self.stages, "total_ms": self.total_ms}
