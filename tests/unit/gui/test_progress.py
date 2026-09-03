import pytest

from lead_enrichment.gui.progress import ProgressEstimator, format_duration


def test_progress_estimator_calculates_average_eta() -> None:
    estimator = ProgressEstimator()
    estimator.start(now=100.0)

    estimate = estimator.update(4, 10, now=108.0)

    assert estimate.elapsed_seconds == 8.0
    assert estimate.items_per_second == 0.5
    assert estimate.remaining_seconds == 12.0


def test_progress_estimator_handles_start_and_completion() -> None:
    estimator = ProgressEstimator()

    initial = estimator.update(0, 10, now=50.0)
    complete = estimator.update(10, 10, now=70.0)

    assert initial.remaining_seconds is None
    assert complete.remaining_seconds == 0.0


def test_progress_estimator_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="прогресса"):
        ProgressEstimator().update(2, 1, now=1.0)


def test_format_duration_is_human_readable() -> None:
    assert format_duration(None) == "считается…"
    assert format_duration(8.2) == "8 сек"
    assert format_duration(125) == "2 мин 05 сек"
    assert format_duration(3725) == "1 ч 02 мин"
