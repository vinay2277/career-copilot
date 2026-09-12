"""Tests for the sliding-window rate limiter.

Time is injected rather than slept, so these are fast and not flaky.
"""

from __future__ import annotations

from app.core.ratelimit import SlidingWindowLimiter


def test_requests_under_the_limit_are_allowed():
    limiter = SlidingWindowLimiter(limit=3, window_seconds=60)
    for expected_remaining in (2, 1, 0):
        decision = limiter.check("a", now=0.0)
        assert decision.allowed
        assert decision.remaining == expected_remaining


def test_the_request_over_the_limit_is_rejected():
    limiter = SlidingWindowLimiter(limit=2, window_seconds=60)
    limiter.check("a", now=0.0)
    limiter.check("a", now=0.0)

    decision = limiter.check("a", now=0.0)
    assert not decision.allowed
    assert decision.remaining == 0
    assert decision.retry_after > 0
    assert decision.limit == 2


def test_keys_are_independent():
    """One caller hitting the limit must not affect anyone else."""
    limiter = SlidingWindowLimiter(limit=1, window_seconds=60)
    assert limiter.check("a", now=0.0).allowed
    assert not limiter.check("a", now=0.0).allowed
    assert limiter.check("b", now=0.0).allowed


def test_the_window_slides():
    limiter = SlidingWindowLimiter(limit=2, window_seconds=60)
    limiter.check("a", now=0.0)
    limiter.check("a", now=30.0)
    assert not limiter.check("a", now=40.0).allowed

    # The first event ages out at t=60, freeing exactly one slot.
    assert limiter.check("a", now=61.0).allowed
    assert not limiter.check("a", now=61.0).allowed

    # The second ages out at t=90.
    assert limiter.check("a", now=91.0).allowed


def test_a_sliding_window_prevents_the_boundary_burst():
    """The reason this isn't a fixed window.

    A fixed window would let a caller spend the full budget at the end of one
    period and again at the start of the next — double the intended rate.
    """
    limiter = SlidingWindowLimiter(limit=5, window_seconds=60)
    for _ in range(5):
        assert limiter.check("a", now=59.0).allowed

    # One second later a fixed window would have reset. This must not.
    assert not limiter.check("a", now=60.5).allowed


def test_rejected_attempts_are_not_recorded():
    """Otherwise hammering the endpoint extends your own lockout forever."""
    limiter = SlidingWindowLimiter(limit=1, window_seconds=60)
    limiter.check("a", now=0.0)

    for t in range(1, 50):
        limiter.check("a", now=float(t))

    # Only the single allowed event at t=0 counts, so it ages out at t=60.
    assert limiter.check("a", now=61.0).allowed


def test_retry_after_points_past_the_oldest_event():
    limiter = SlidingWindowLimiter(limit=1, window_seconds=60)
    limiter.check("a", now=0.0)

    decision = limiter.check("a", now=10.0)
    assert not decision.allowed
    # The slot frees at t=60, i.e. 50s away; allow for the +1 rounding guard.
    assert 50 <= decision.retry_after <= 52


def test_reset_clears_one_key():
    limiter = SlidingWindowLimiter(limit=1, window_seconds=60)
    limiter.check("a", now=0.0)
    limiter.check("b", now=0.0)

    limiter.reset("a")
    assert limiter.check("a", now=0.0).allowed
    assert not limiter.check("b", now=0.0).allowed


def test_reset_clears_everything():
    limiter = SlidingWindowLimiter(limit=1, window_seconds=60)
    limiter.check("a", now=0.0)
    limiter.check("b", now=0.0)

    limiter.reset()
    assert limiter.check("a", now=0.0).allowed
    assert limiter.check("b", now=0.0).allowed


def test_prune_drops_only_stale_keys():
    """Without pruning the key map grows once per client and never shrinks."""
    limiter = SlidingWindowLimiter(limit=5, window_seconds=60)
    limiter.check("old", now=0.0)
    limiter.check("recent", now=100.0)

    removed = limiter.prune(now=120.0)
    assert removed == 1
    assert limiter.check("recent", now=120.0).remaining == 3  # its event survived


def test_limit_below_one_is_rejected_at_construction():
    """A limit of 0 would block everything, which is never the intent."""
    import pytest

    with pytest.raises(ValueError):
        SlidingWindowLimiter(limit=0, window_seconds=60)
