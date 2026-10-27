from __future__ import annotations

from datetime import datetime


def chronological_split(
    dates: list[datetime],
    train_ratio: float = 0.7,
    val_ratio: float = 0.15,
) -> tuple[list[datetime], list[datetime], list[datetime]]:
    """Split unique issuance dates so train ends before validation, which ends before test."""
    ordered = sorted(set(dates))
    count = len(ordered)
    if count < 30:
        raise ValueError(f"Need at least 30 issuance dates for a chronological split, found {count}.")
    train_end = max(1, int(count * train_ratio))
    val_end = max(train_end + 1, int(count * (train_ratio + val_ratio)))
    val_end = min(val_end, count - 1)
    train_dates = ordered[:train_end]
    val_dates = ordered[train_end:val_end]
    test_dates = ordered[val_end:]
    if not val_dates or not test_dates:
        raise ValueError("Chronological split produced an empty validation or test period.")
    if not (max(train_dates) < min(val_dates) < max(val_dates) < min(test_dates)):
        raise ValueError("Chronological split did not keep the periods in time order.")
    return train_dates, val_dates, test_dates
