from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProgressEstimate:
    completed: int
    total: int
    elapsed_seconds: float
    remaining_seconds: float | None
    items_per_second: float | None


class ProgressEstimator:
    """Estimate remaining batch time from the observed average throughput."""

    def __init__(self) -> None:
        self._started_at: float | None = None

    def start(self, *, now: float | None = None) -> None:
        self._started_at = time.monotonic() if now is None else now

    def update(
        self,
        completed: int,
        total: int,
        *,
        now: float | None = None,
    ) -> ProgressEstimate:
        if completed < 0 or total < 0 or completed > total:
            raise ValueError("Некорректные значения прогресса")
        current = time.monotonic() if now is None else now
        if self._started_at is None:
            self.start(now=current)
        assert self._started_at is not None
        elapsed = max(current - self._started_at, 0.0)
        rate = completed / elapsed if completed > 0 and elapsed > 0 else None
        if completed >= total and total > 0:
            remaining = 0.0
        elif rate:
            remaining = (total - completed) / rate
        else:
            remaining = None
        return ProgressEstimate(
            completed=completed,
            total=total,
            elapsed_seconds=elapsed,
            remaining_seconds=remaining,
            items_per_second=rate,
        )


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "считается…"
    rounded = max(int(round(seconds)), 0)
    hours, remainder = divmod(rounded, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours} ч {minutes:02d} мин"
    if minutes:
        return f"{minutes} мин {secs:02d} сек"
    return f"{secs} сек"
