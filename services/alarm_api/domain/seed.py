"""Deterministic synthetic dataset for the Alarm Management API simulator.

Everything is derived from a single integer seed, so the dataset is identical
on every machine and every run. That property is what lets the Postman
collections and the automated tests assert on concrete values instead of
merely on response shapes.

On top of a random background of alarm events, the generator injects a set of
*structures* the analytical endpoints are supposed to detect:

============================  =======================================================
Structure                     Why it exists
============================  =======================================================
Alarm flood in Unit 2         ``POST /alarms/flood-analysis`` must return a window
                              (Postman CHAIN-02 reads ``flood_windows[0]``).
Causal alarm pairs            ``POST /alarms/correlation`` must find real pairs rather
                              than coincidences (CHAIN-03, CHAIN-08).
Chattering fan vibration      ``POST /alarms/rationalization-candidates`` must have a
                              chattering candidate to report (CHAIN-10).
Stale actives in Unit 1       Gives the stale-alarm branch of rationalization data
                              (CHAIN-06).
EastRefinery active alarms    ``GET /alarms?site=EastRefinery&status=active`` must be
                              non-empty (CHAIN-09 asserts ``rows.length > 0``).
Recurring BFP-101 high-sev    The mandatory acceptance scenario: "recurring
                              high-severity alarms for Boiler Feed Pump 101 over the
                              last 90 days".
Slow acknowledgement at       Makes ``operator_response_efficiency`` meaningful
SouthPlant                    (CHAIN-07).
============================  =======================================================
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from alarm_api.config import DATA_NOW, DATA_START
from alarm_api.domain.catalog import (
    ASSET_SPECS,
    CAUSAL_PAIRS,
    TEMPLATES_BY_TYPE,
    AlarmTemplate,
    AssetSpec,
)
from alarm_api.schemas import (
    Alarm,
    AlarmStatus,
    AssetMetadata,
    Criticality,
    Severity,
)

_SEVERITIES: tuple[Severity, ...] = (
    Severity.LOW,
    Severity.MEDIUM,
    Severity.HIGH,
    Severity.CRITICAL,
)

# Mean operator acknowledgement delay per site, in seconds. SouthPlant is
# deliberately the worst performer so response-efficiency analytics have a
# signal to find.
_ACK_BASE_SECONDS: dict[str, int] = {
    "NorthPlant": 240,
    "SouthPlant": 900,
    "EastRefinery": 420,
}

_SEVERITY_ACK_FACTOR: dict[Severity, float] = {
    Severity.CRITICAL: 0.35,
    Severity.HIGH: 0.6,
    Severity.MEDIUM: 1.0,
    Severity.LOW: 1.6,
}

_CRITICALITY_RATE: dict[Criticality, float] = {
    Criticality.CRITICAL: 1.45,
    Criticality.HIGH: 1.15,
    Criticality.MEDIUM: 0.85,
    Criticality.LOW: 0.6,
}

# Alarms newer than this are candidates for still being open.
_RECENT_WINDOW = timedelta(days=14)
_FLOOD_START = datetime(2026, 6, 12, 3, 0, tzinfo=UTC)


@dataclass
class _Event:
    """An alarm occurrence before identifiers and lifecycle are assigned."""

    spec: AssetSpec
    asset_id: str
    template: AlarmTemplate
    start_time: datetime
    severity: Severity | None = None
    status: AlarmStatus | None = None
    tag_suffix: str = ""


@dataclass
class Dataset:
    """The fully materialised, immutable-by-convention plant dataset."""

    assets: list[AssetMetadata]
    alarms: list[Alarm]
    assets_by_id: dict[str, AssetMetadata] = field(default_factory=dict)
    alarms_by_id: dict[str, Alarm] = field(default_factory=dict)
    alarms_by_asset: dict[str, list[Alarm]] = field(default_factory=dict)
    seed: int = 0

    def __post_init__(self) -> None:
        self.assets_by_id = {a.asset_id: a for a in self.assets}
        self.alarms_by_id = {a.alarm_id: a for a in self.alarms}
        grouped: dict[str, list[Alarm]] = {a.asset_id: [] for a in self.assets}
        for alarm in self.alarms:
            grouped[alarm.asset_id].append(alarm)
        self.alarms_by_asset = grouped

    @property
    def summary(self) -> dict[str, object]:
        """Compact dataset description, surfaced by ``GET /health``."""
        return {
            "seed": self.seed,
            "assets": len(self.assets),
            "alarms": len(self.alarms),
            "active_alarms": sum(1 for a in self.alarms if a.status == AlarmStatus.ACTIVE),
            "window_start": DATA_START.isoformat(),
            "window_end": DATA_NOW.isoformat(),
        }


def _slug(name: str) -> str:
    """Build an instrument-style tag fragment from an asset name."""
    parts = [p for p in name.replace("-", " ").split() if p]
    letters = "".join(p[0] for p in parts if not p.isdigit()).upper()[:4]
    digits = "".join(p for p in parts if p.isdigit()) or "000"
    return f"{letters}-{digits}"


def _pick_severity(rng: random.Random, template: AlarmTemplate) -> Severity:
    return rng.choices(_SEVERITIES, weights=template.severity_weights, k=1)[0]


def _synthesise_value(
    rng: random.Random, template: AlarmTemplate
) -> tuple[float | None, float | None]:
    """Return ``(measured_value, limit_value)`` consistent with the template.

    ``overshoot`` is signed: positive templates breach a high limit, negative
    ones breach a low limit. Scaling by ``abs(limit)`` keeps the direction
    correct for negative limits such as a drum level of -150 mm.
    """
    if template.limit_value is None:
        return None, None
    limit = template.limit_value
    scale = abs(limit) if limit else 1.0
    factor = 0.6 + 0.8 * rng.random()
    value = limit + scale * template.overshoot * factor
    return round(value, 2), limit


def _build_assets(specs: tuple[AssetSpec, ...], rng: random.Random) -> list[AssetMetadata]:
    """Materialise asset records. Counts are filled in later by the caller."""
    unit_members: dict[tuple[str, str], list[str]] = {}
    ids: list[str] = []
    for index, spec in enumerate(specs, start=1):
        asset_id = f"AST-{index:04d}"
        ids.append(asset_id)
        unit_members.setdefault((spec.site, spec.unit), []).append(asset_id)

    assets: list[AssetMetadata] = []
    for asset_id, spec in zip(ids, specs, strict=True):
        siblings = [x for x in unit_members[(spec.site, spec.unit)] if x != asset_id]
        installed = DATA_START - timedelta(days=rng.randint(700, 5200))
        last_maint = DATA_NOW - timedelta(days=rng.randint(20, 300))
        templates = TEMPLATES_BY_TYPE.get(spec.asset_type, ())
        design_limits = {t.name: t.limit_value for t in templates if t.limit_value is not None}
        assets.append(
            AssetMetadata(
                asset_id=asset_id,
                asset_name=spec.name,
                asset_type=spec.asset_type,
                site=spec.site,
                unit=spec.unit,
                criticality=spec.criticality,
                tag=f"{spec.site[:2].upper()}-{spec.unit.split()[-1]}-{_slug(spec.name)}",
                manufacturer=spec.manufacturer,
                model_number=spec.model_number,
                serial_number=f"SN{rng.randint(100000, 999999)}",
                installation_date=installed,
                last_maintenance_date=last_maint,
                next_maintenance_due=last_maint + timedelta(days=180),
                operating_hours=rng.randint(8000, 96000),
                parent_asset_id=None,
                related_asset_ids=siblings,
                design_limits=design_limits,
                alarm_count_total=0,
                alarm_count_active=0,
            )
        )
    return assets


def _background_events(
    specs: tuple[AssetSpec, ...], asset_ids: list[str], rng: random.Random
) -> list[_Event]:
    """Poisson-ish background occurrences for every (asset, template) pair."""
    events: list[_Event] = []
    for spec, asset_id in zip(specs, asset_ids, strict=True):
        rate_multiplier = _CRITICALITY_RATE[spec.criticality] * (0.75 + 0.5 * rng.random())
        for template in TEMPLATES_BY_TYPE.get(spec.asset_type, ()):
            mean_hours = template.mean_interval_hours / rate_multiplier
            cursor = DATA_START + timedelta(hours=rng.uniform(0, mean_hours))
            while cursor < DATA_NOW:
                events.append(
                    _Event(spec=spec, asset_id=asset_id, template=template, start_time=cursor)
                )
                cursor += timedelta(hours=max(0.5, rng.expovariate(1.0 / mean_hours)))
    return events


def _template_for(spec: AssetSpec, name: str) -> AlarmTemplate | None:
    for template in TEMPLATES_BY_TYPE.get(spec.asset_type, ()):
        if template.name == name:
            return template
    return None


def _inject_flood(
    specs: tuple[AssetSpec, ...], asset_ids: list[str], rng: random.Random
) -> list[_Event]:
    """A dense burst across Unit 2, inside the Postman time window."""
    unit2 = [(s, a) for s, a in zip(specs, asset_ids, strict=True) if s.unit == "Unit 2"]
    events: list[_Event] = []
    for i in range(26):
        spec, asset_id = unit2[i % len(unit2)]
        templates = TEMPLATES_BY_TYPE.get(spec.asset_type, ())
        if not templates:
            continue
        template = templates[i % len(templates)]
        events.append(
            _Event(
                spec=spec,
                asset_id=asset_id,
                template=template,
                start_time=_FLOOD_START + timedelta(seconds=int(i * 19 + rng.randint(0, 8))),
                severity=Severity.HIGH if i % 3 else Severity.CRITICAL,
                tag_suffix="flood",
            )
        )
    return events


def _inject_causal_pairs(
    specs: tuple[AssetSpec, ...], asset_ids: list[str], rng: random.Random
) -> list[_Event]:
    """Leader/follower alarm pairs so correlation finds genuine structure."""
    events: list[_Event] = []
    for spec, asset_id in zip(specs, asset_ids, strict=True):
        for leader_name, follower_name, lag_minutes in CAUSAL_PAIRS:
            leader = _template_for(spec, leader_name)
            follower = _template_for(spec, follower_name)
            if leader is None or follower is None:
                continue
            # Both ends stay high-severity: CHAIN-08 runs correlation with
            # severity_threshold="high", so the injected pairs must survive
            # that filter to be discoverable.
            for _ in range(rng.randint(3, 6)):
                offset_hours = rng.uniform(0, (DATA_NOW - DATA_START).total_seconds() / 3600)
                start = DATA_START + timedelta(hours=offset_hours)
                if start >= DATA_NOW:
                    continue
                jitter = rng.uniform(0.5, 1.6)
                follow = start + timedelta(minutes=lag_minutes * jitter)
                if follow >= DATA_NOW:
                    continue
                events.append(
                    _Event(
                        spec, asset_id, leader, start, severity=Severity.HIGH, tag_suffix="causal"
                    )
                )
                events.append(
                    _Event(
                        spec,
                        asset_id,
                        follower,
                        follow,
                        severity=Severity.HIGH,
                        tag_suffix="causal",
                    )
                )
    return events


def _inject_chattering(
    specs: tuple[AssetSpec, ...], asset_ids: list[str], rng: random.Random
) -> list[_Event]:
    """Repeated short-lived vibration alarms on a cooling tower fan."""
    target = next(
        (
            (s, a)
            for s, a in zip(specs, asset_ids, strict=True)
            if s.name == "Cooling Tower Fan 201"
        ),
        None,
    )
    if target is None:
        return []
    spec, asset_id = target
    template = _template_for(spec, "High Vibration")
    if template is None:
        return []
    events: list[_Event] = []
    for burst in range(9):
        anchor = DATA_START + timedelta(
            days=7 * burst + rng.randint(0, 4), hours=rng.randint(0, 23)
        )
        for k in range(7):
            start = anchor + timedelta(minutes=k * rng.randint(3, 6))
            if start >= DATA_NOW:
                continue
            events.append(
                _Event(
                    spec, asset_id, template, start, severity=Severity.MEDIUM, tag_suffix="chatter"
                )
            )
    return events


def _inject_stale_actives(
    specs: tuple[AssetSpec, ...], asset_ids: list[str], rng: random.Random
) -> list[_Event]:
    """Long-standing unacknowledged alarms in NorthPlant / Unit 1."""
    unit1 = [
        (s, a)
        for s, a in zip(specs, asset_ids, strict=True)
        if s.site == "NorthPlant" and s.unit == "Unit 1"
    ]
    events: list[_Event] = []
    for i, (spec, asset_id) in enumerate(unit1):
        templates = TEMPLATES_BY_TYPE.get(spec.asset_type, ())
        if not templates:
            continue
        for k in range(2):
            template = templates[(i + k) % len(templates)]
            start = DATA_NOW - timedelta(days=rng.randint(21, 120), hours=rng.randint(0, 23))
            events.append(
                _Event(
                    spec,
                    asset_id,
                    template,
                    start,
                    severity=Severity.MEDIUM if k else Severity.HIGH,
                    status=AlarmStatus.ACTIVE,
                    tag_suffix="stale",
                )
            )
    return events


def _inject_east_actives(
    specs: tuple[AssetSpec, ...], asset_ids: list[str], rng: random.Random
) -> list[_Event]:
    """Guarantee a non-empty ``site=EastRefinery&status=active`` result."""
    east = [(s, a) for s, a in zip(specs, asset_ids, strict=True) if s.site == "EastRefinery"]
    events: list[_Event] = []
    for i, (spec, asset_id) in enumerate(east):
        templates = TEMPLATES_BY_TYPE.get(spec.asset_type, ())
        if not templates:
            continue
        for k in range(2):
            template = templates[(i + k * 2) % len(templates)]
            start = DATA_NOW - timedelta(
                days=rng.randint(0, 9), hours=rng.randint(0, 23), minutes=rng.randint(0, 59)
            )
            severity = Severity.CRITICAL if (i + k) % 3 == 0 else Severity.HIGH
            events.append(
                _Event(
                    spec,
                    asset_id,
                    template,
                    start,
                    severity=severity,
                    status=AlarmStatus.ACTIVE,
                    tag_suffix="east-active",
                )
            )
    return events


def _inject_bfp101_recurrence(
    specs: tuple[AssetSpec, ...], asset_ids: list[str], rng: random.Random
) -> list[_Event]:
    """The mandatory acceptance scenario's evidence base.

    Recurring high-severity alarms on Boiler Feed Pump 101 across the trailing
    90 days, weighted towards the most recent weeks so the trend reads as
    "increasing".
    """
    target = next(
        ((s, a) for s, a in zip(specs, asset_ids, strict=True) if s.name == "Boiler Feed Pump 101"),
        None,
    )
    if target is None:
        return []
    spec, asset_id = target
    events: list[_Event] = []
    for name, severity in (
        ("High Discharge Temperature", Severity.HIGH),
        ("High Vibration", Severity.HIGH),
        ("Low Suction Pressure", Severity.CRITICAL),
    ):
        template = _template_for(spec, name)
        if template is None:
            continue
        for k in range(11):
            # Quadratic spacing: sparse 90 days ago, dense in the last fortnight.
            days_ago = 90.0 * ((10 - k) / 10.0) ** 1.7
            start = DATA_NOW - timedelta(
                days=days_ago, hours=rng.randint(0, 23), minutes=rng.randint(0, 59)
            )
            if start < DATA_START:
                continue
            events.append(
                _Event(spec, asset_id, template, start, severity=severity, tag_suffix="bfp101")
            )
    return events


def _finalise(events: list[_Event], rng: random.Random) -> list[Alarm]:
    """Sort events, assign identifiers, and derive the lifecycle fields."""
    events.sort(key=lambda e: (e.start_time, e.asset_id, e.template.name))

    alarms: list[Alarm] = []
    for index, event in enumerate(events, start=1):
        template = event.template
        severity = event.severity or _pick_severity(rng, template)
        value, limit = _synthesise_value(rng, template)

        status = event.status
        if status is None:
            age = DATA_NOW - event.start_time
            if age > _RECENT_WINDOW:
                # Historic alarms are essentially all resolved.
                status = AlarmStatus.CLEARED if rng.random() < 0.96 else AlarmStatus.SUPPRESSED
            else:
                roll = rng.random()
                if roll < 0.55:
                    status = AlarmStatus.CLEARED
                elif roll < 0.78:
                    status = AlarmStatus.ACKNOWLEDGED
                elif roll < 0.95:
                    status = AlarmStatus.ACTIVE
                else:
                    status = AlarmStatus.SUPPRESSED

        ack_time: datetime | None = None
        clear_time: datetime | None = None
        ack_delay: int | None = None
        duration: int | None = None

        if status in (AlarmStatus.ACKNOWLEDGED, AlarmStatus.CLEARED):
            base = _ACK_BASE_SECONDS.get(event.spec.site, 400)
            factor = _SEVERITY_ACK_FACTOR[severity]
            ack_delay = max(15, int(rng.expovariate(1.0 / (base * factor))))
            ack_time = event.start_time + timedelta(seconds=ack_delay)

        if status == AlarmStatus.CLEARED and ack_time is not None:
            if event.tag_suffix == "chatter":
                duration = rng.randint(45, 240)
            else:
                span = {
                    Severity.CRITICAL: (900, 14400),
                    Severity.HIGH: (600, 21600),
                    Severity.MEDIUM: (300, 28800),
                    Severity.LOW: (120, 36000),
                }[severity]
                duration = rng.randint(*span)
            clear_time = event.start_time + timedelta(seconds=duration)
            if clear_time > DATA_NOW:
                clear_time = None
                duration = None
                status = AlarmStatus.ACKNOWLEDGED

        alarms.append(
            Alarm(
                alarm_id=f"ALM-{index:06d}",
                asset_id=event.asset_id,
                asset_name=event.spec.name,
                site=event.spec.site,
                unit=event.spec.unit,
                alarm_name=template.name,
                alarm_type=template.alarm_type,
                severity=severity,
                status=status,
                start_time=event.start_time,
                ack_time=ack_time,
                clear_time=clear_time,
                ack_delay_seconds=ack_delay,
                duration_seconds=duration,
                source_tag=f"{_slug(event.spec.name)}/{_slug(template.name)}",
                measured_value=value,
                limit_value=limit,
                unit_of_measure=template.unit_of_measure,
                description=template.description,
            )
        )
    return alarms


def build_dataset(seed: int) -> Dataset:
    """Build the full deterministic dataset for ``seed``."""
    rng = random.Random(seed)
    specs = ASSET_SPECS
    assets = _build_assets(specs, rng)
    asset_ids = [a.asset_id for a in assets]

    events: list[_Event] = []
    events += _background_events(specs, asset_ids, rng)
    events += _inject_flood(specs, asset_ids, rng)
    events += _inject_causal_pairs(specs, asset_ids, rng)
    events += _inject_chattering(specs, asset_ids, rng)
    events += _inject_stale_actives(specs, asset_ids, rng)
    events += _inject_east_actives(specs, asset_ids, rng)
    events += _inject_bfp101_recurrence(specs, asset_ids, rng)

    alarms = _finalise(events, rng)

    totals: dict[str, int] = {a.asset_id: 0 for a in assets}
    actives: dict[str, int] = {a.asset_id: 0 for a in assets}
    for alarm in alarms:
        totals[alarm.asset_id] += 1
        if alarm.status == AlarmStatus.ACTIVE:
            actives[alarm.asset_id] += 1
    for asset in assets:
        asset.alarm_count_total = totals[asset.asset_id]
        asset.alarm_count_active = actives[asset.asset_id]

    return Dataset(assets=assets, alarms=alarms, seed=seed)
