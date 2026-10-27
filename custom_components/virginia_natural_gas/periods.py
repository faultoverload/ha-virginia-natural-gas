"""Spread billing-period totals over the days of each period.

The portal only knows totals per billing period (about a month, ending on a meter
read). Long-term statistics get one row per day, so each period's usage and charges
are split evenly across its days. A period runs from the previous read date up to
the day before its own read date; bills are dated on the read that closed them.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta

from .api import Bill, MeterRead
from .const import MAX_PERIOD_DAYS


def spread(total: float, start: date, days: int) -> dict[date, float]:
    """Split ``total`` over ``days`` days from ``start`` so the parts add up exactly.

    Each day gets the difference of rounded running totals, so rounding never makes
    the period's sum drift from what the portal reported.
    """
    parts: dict[date, float] = {}
    previous = 0.0
    for offset in range(days):
        running = round(total * (offset + 1) / days, 4)
        parts[start + timedelta(days=offset)] = round(running - previous, 4)
        previous = running
    return parts


def daily_usage(reads: Iterable[MeterRead]) -> dict[date, float]:
    """CCF per day, from each read's usage and days since the previous read."""
    days: dict[date, float] = {}
    for read in reads:
        if 0 < read.days <= MAX_PERIOD_DAYS:
            days.update(spread(read.usage, read.read_date - timedelta(days=read.days), read.days))
    return days


def daily_cost(bills: Iterable[Bill]) -> dict[date, float]:
    """Gas charges per day.

    Bills don't say how many days they cover, but consecutive bill dates bound each
    period, so this reaches back further than the usage history. The oldest bill has
    no start and is skipped. Two bills on the same date (a corrected bill, say) are
    added together.
    """
    charges: dict[date, float] = {}
    for bill in bills:
        charges[bill.bill_date] = round(charges.get(bill.bill_date, 0.0) + bill.gas_charges, 2)
    days: dict[date, float] = {}
    ordered = sorted(charges)
    for start, end in zip(ordered, ordered[1:], strict=False):
        length = (end - start).days
        if 0 < length <= MAX_PERIOD_DAYS:
            days.update(spread(charges[end], start, length))
    return days
