"""Tests for cycle summary."""

from politrade.crypto.cycle_summary import _compute_readiness, _format_lessons
from politrade.storage.models import SimDecision


def test_compute_readiness():
    score = _compute_readiness(60, 20, 15, [])
    assert 0 < score <= 100


def test_format_lessons_edge_skips():
    decisions = [
        SimDecision(
            id=i, asset="btc", window_ts=1, slug=f"s{i}", action="skip",
            reason="edge 10% < 15% נדרש", phase="bet", worth_investing=False,
        )
        for i in range(5)
    ]
    text = _format_lessons(decisions, [])
    assert "edge" in text.lower() or "min_edge" in text
