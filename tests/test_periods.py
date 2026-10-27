"""Tests for spreading billing periods over days."""

from __future__ import annotations

from datetime import date, timedelta

from custom_components.virginia_natural_gas.api import Bill, MeterRead
from custom_components.virginia_natural_gas.periods import daily_cost, daily_usage, spread


def test_spread_adds_up_exactly() -> None:
    """Rounded daily parts still sum to the period total."""
    parts = spread(4.0, date(2026, 9, 3), 33)
    assert len(parts) == 33
    assert min(parts) == date(2026, 9, 3)
    assert max(parts) == date(2026, 10, 5)
    assert round(sum(parts.values()), 4) == 4.0
    assert all(abs(v - 4 / 33) < 0.0002 for v in parts.values())


def test_daily_usage_ends_the_day_before_the_read() -> None:
    """A read's usage covers the days since the previous read, not the read day."""
    reads = [
        MeterRead(date(2026, 9, 3), 100.0, 0.0, 29, True),
        MeterRead(date(2026, 10, 6), 104.0, 4.0, 33, True),
    ]
    days = daily_usage(reads)
    assert min(days) == date(2026, 8, 5)
    assert max(days) == date(2026, 10, 5)
    assert sum(v for d, v in days.items() if d < date(2026, 9, 3)) == 0
    assert round(sum(days.values()), 4) == 4.0


def test_daily_usage_skips_bad_lengths() -> None:
    """Reads with no days, or implausibly long periods, are skipped."""
    reads = [
        MeterRead(date(2026, 1, 1), 1.0, 5.0, 0, True),
        MeterRead(date(2026, 6, 1), 2.0, 5.0, 120, True),
    ]
    assert daily_usage(reads) == {}


def test_daily_cost_uses_consecutive_bill_dates() -> None:
    """Each bill covers the days since the previous bill; the oldest is skipped."""
    bills = [
        Bill(date(2026, 8, 5), 20.18, 20.18),
        Bill(date(2026, 9, 3), 18.07, 18.07),
        Bill(date(2026, 10, 6), 26.31, 26.31),
    ]
    days = daily_cost(bills)
    assert min(days) == date(2026, 8, 5)
    assert max(days) == date(2026, 10, 5)
    september = [days[date(2026, 9, 3) + timedelta(days=i)] for i in range(33)]
    assert round(sum(september), 2) == 26.31
    assert round(sum(days.values()), 2) == round(18.07 + 26.31, 2)


def test_daily_cost_leaves_gaps_for_missing_bills() -> None:
    """A gap longer than a billing period is not filled."""
    bills = [Bill(date(2026, 1, 5), 50.0, 50.0), Bill(date(2026, 6, 5), 20.0, 20.0)]
    assert daily_cost(bills) == {}


def test_daily_cost_adds_bills_on_the_same_date() -> None:
    """Two bills dated on the same read are one period's charges."""
    bills = [
        Bill(date(2026, 1, 5), 50.0, 50.0),
        Bill(date(2026, 2, 4), 30.0, 30.0),
        Bill(date(2026, 2, 4), 5.0, 5.0),
    ]
    assert round(sum(daily_cost(bills).values()), 2) == 35.0
