"""Query layer over the in-memory dataset.

Pure functions plus a thin process-wide holder. Keeping filtering and sorting
here - rather than inside the routers - means the analytics module and the
HTTP layer share exactly one definition of "which alarms are in scope", which
is the thing most likely to drift between endpoints.

No SQL is used anywhere in the simulator; scope filters are applied as typed
Python predicates over immutable records, so there is no injection surface.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime

from alarm_api.domain.seed import Dataset, build_dataset
from alarm_api.schemas import (
    Alarm,
    AlarmStatus,
    AlarmType,
    Asset,
    AssetMetadata,
    Pagination,
    Severity,
)

SORTABLE_ALARM_FIELDS = frozenset(
    {
        "start_time",
        "severity",
        "status",
        "alarm_name",
        "asset_name",
        "alarm_id",
        "ack_delay_seconds",
    }
)

_SEVERITY_ORDER: dict[Severity, int] = {
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}


class UnknownSortFieldError(ValueError):
    """Raised when a caller asks to sort by a field that is not sortable."""


# --------------------------------------------------------------------------
# Process-wide dataset holder
# --------------------------------------------------------------------------
_dataset: Dataset | None = None


def get_dataset(seed: int | None = None) -> Dataset:
    """Return the process-wide dataset, building it on first use."""
    global _dataset
    if _dataset is None:
        from alarm_api.config import get_settings

        _dataset = build_dataset(seed if seed is not None else get_settings().seed)
    return _dataset


def reset_dataset() -> None:
    """Drop the cached dataset so the next call rebuilds it (tests)."""
    global _dataset
    _dataset = None


# --------------------------------------------------------------------------
# Assets
# --------------------------------------------------------------------------
def search_assets(
    dataset: Dataset,
    query: str,
    *,
    site: str | None = None,
    unit: str | None = None,
    asset_type: str | None = None,
    limit: int = 10,
) -> list[Asset]:
    """Case-insensitive substring search over asset name, tag, type and id.

    Results are ranked so that a prefix match on the name beats a match
    anywhere else - "Boiler Feed Pump 101" should be the first hit for the
    query "Boiler Feed Pump 101" even though "102" also contains the stem.
    """
    needle = query.strip().lower()

    def score(asset: AssetMetadata) -> tuple[int, str]:
        name = asset.asset_name.lower()
        if name == needle:
            rank = 0
        elif name.startswith(needle):
            rank = 1
        elif needle in name:
            rank = 2
        elif needle in asset.asset_type.lower() or needle in asset.tag.lower():
            rank = 3
        else:
            rank = 4
        return rank, asset.asset_id

    matches: list[AssetMetadata] = []
    for asset in dataset.assets:
        if site and asset.site != site:
            continue
        if unit and asset.unit != unit:
            continue
        if asset_type and asset.asset_type != asset_type:
            continue
        haystack = " ".join(
            (asset.asset_name, asset.asset_type, asset.tag, asset.asset_id, asset.unit)
        ).lower()
        if needle and needle not in haystack:
            continue
        matches.append(asset)

    matches.sort(key=score)
    # Project down to the lighter Asset shape; metadata needs its own endpoint.
    return [Asset(**a.model_dump(include=set(Asset.model_fields))) for a in matches[:limit]]


def get_asset(dataset: Dataset, asset_id: str) -> AssetMetadata | None:
    return dataset.assets_by_id.get(asset_id)


def resolve_scope_asset_ids(
    dataset: Dataset,
    *,
    asset_ids: Sequence[str] | None,
    site: str | None,
    unit: str | None,
) -> set[str] | None:
    """Turn a scope selector into a concrete set of asset ids.

    Returns ``None`` when the scope is "everything", which lets callers skip
    the membership test entirely.
    """
    if not asset_ids and not site and not unit:
        return None
    selected: set[str] = set()
    for asset in dataset.assets:
        if asset_ids and asset.asset_id not in asset_ids:
            continue
        if site and asset.site != site:
            continue
        if unit and asset.unit != unit:
            continue
        selected.add(asset.asset_id)
    return selected


def unknown_asset_ids(dataset: Dataset, asset_ids: Iterable[str]) -> list[str]:
    """Asset ids the caller referenced that do not exist."""
    return sorted(a for a in asset_ids if a not in dataset.assets_by_id)


# --------------------------------------------------------------------------
# Alarms
# --------------------------------------------------------------------------
def filter_alarms(
    dataset: Dataset,
    *,
    asset_ids: Sequence[str] | None = None,
    site: str | None = None,
    unit: str | None = None,
    status: Sequence[AlarmStatus] | None = None,
    severity: Sequence[Severity] | None = None,
    alarm_types: Sequence[AlarmType] | None = None,
    alarm_name: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    min_severity: Severity | None = None,
) -> list[Alarm]:
    """Apply every scope and attribute filter, preserving dataset order.

    ``start_time``/``end_time`` bound the alarm's *onset*, inclusive of the
    start and exclusive of the end, matching :class:`TimeRange`'s semantics.
    """
    scope = resolve_scope_asset_ids(dataset, asset_ids=asset_ids, site=site, unit=unit)
    status_set = set(status) if status else None
    severity_set = set(severity) if severity else None
    type_set = set(alarm_types) if alarm_types else None
    min_rank = _SEVERITY_ORDER[min_severity] if min_severity else None
    name_needle = alarm_name.lower() if alarm_name else None

    out: list[Alarm] = []
    for alarm in dataset.alarms:
        if scope is not None and alarm.asset_id not in scope:
            continue
        if status_set and alarm.status not in status_set:
            continue
        if severity_set and alarm.severity not in severity_set:
            continue
        if type_set and alarm.alarm_type not in type_set:
            continue
        if min_rank is not None and _SEVERITY_ORDER[alarm.severity] < min_rank:
            continue
        if name_needle and name_needle not in alarm.alarm_name.lower():
            continue
        if start_time is not None and alarm.start_time < start_time:
            continue
        if end_time is not None and alarm.start_time >= end_time:
            continue
        out.append(alarm)
    return out


def sort_alarms(alarms: list[Alarm], sort_by: str, sort_order: str) -> list[Alarm]:
    """Sort a result set, raising :class:`UnknownSortFieldError` on a bad field."""
    if sort_by not in SORTABLE_ALARM_FIELDS:
        raise UnknownSortFieldError(sort_by)
    reverse = sort_order.lower() == "desc"

    def key(alarm: Alarm):
        if sort_by == "severity":
            return _SEVERITY_ORDER[alarm.severity]
        if sort_by == "ack_delay_seconds":
            # Unacknowledged alarms sort last ascending / first descending.
            return alarm.ack_delay_seconds if alarm.ack_delay_seconds is not None else -1
        value = getattr(alarm, sort_by)
        return value.value if hasattr(value, "value") else value

    # Secondary key on alarm_id keeps the order total and therefore stable
    # across processes - important because pagination is offset-based.
    return sorted(alarms, key=lambda a: (key(a), a.alarm_id), reverse=reverse)


def paginate(items: list[Alarm], page: int, page_size: int) -> tuple[list[Alarm], Pagination]:
    total = len(items)
    total_pages = max(1, -(-total // page_size))  # ceiling division
    start = (page - 1) * page_size
    window = items[start : start + page_size]
    return window, Pagination(
        page=page,
        page_size=page_size,
        total_items=total,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_previous=page > 1,
    )


def get_alarm(dataset: Dataset, alarm_id: str) -> Alarm | None:
    return dataset.alarms_by_id.get(alarm_id)


def occurrences_since(dataset: Dataset, asset_id: str, alarm_name: str, since: datetime) -> int:
    """How many times this alarm has fired on this asset since ``since``."""
    return sum(
        1
        for a in dataset.alarms_by_asset.get(asset_id, ())
        if a.alarm_name == alarm_name and a.start_time >= since
    )
