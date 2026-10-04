"""Generate the mock ticketing system's historical ticket corpus.

Run this to regenerate ``test-data/seed_tickets.json``::

    python scripts/generate_ticket_seed.py

Why a generated fixture rather than a shared import: the ticketing system and
the alarm system are *separate source systems*. Having ``ticketing_api``
import ``alarm_api``'s catalog at runtime would couple two services that are
independent in the architecture, so the coupling is confined to this
build-time script and the services exchange a plain JSON file instead.

The resolution notes written here are reused as part of the RAG corpus - see
``scripts/export_resolution_notes.py`` - which is what lets the copilot cite
"how we fixed this last time" alongside the formal procedures.
"""

from __future__ import annotations

import json
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services"))

from alarm_api.domain.catalog import ASSET_SPECS, TEMPLATES_BY_TYPE  # noqa: E402

OUTPUT = ROOT / "test-data" / "seed_tickets.json"

SEED = 8812
DATA_NOW = datetime(2026, 9, 30, tzinfo=UTC)

ENGINEERS = (
    "a.okafor",
    "r.bhattacharya",
    "m.lindqvist",
    "j.tanaka",
    "s.oyelaran",
    "p.novak",
    "l.fernandes",
    "d.mcallister",
    "n.haddad",
    "k.wijeratne",
)

# Root cause -> (what was found, what was done, how long it took in hours).
RESOLUTIONS: dict[str, tuple[str, str, float]] = {
    "Degraded mechanical seal": (
        "Seal faces showed circumferential scoring and the flush line orifice was "
        "partially blocked with scale.",
        "Replaced the cartridge seal, cleaned the API Plan 11 flush orifice and "
        "re-established flush flow. Discharge temperature returned to 71 degC.",
        6.5,
    ),
    "Recirculation line fouling": (
        "Minimum-flow recirculation orifice was fouled, holding the pump below "
        "its minimum continuous stable flow at low plant rates.",
        "Isolated and cleaned the recirculation orifice, then verified minimum "
        "flow at 30 percent plant rate.",
        4.0,
    ),
    "Cooling water flow loss": (
        "Cooling water isolation valve to the seal cooler had been left 60 percent "
        "closed after the previous outage.",
        "Reopened and car-sealed the cooling water isolation valve, and added the "
        "valve to the post-outage line-up checklist.",
        1.5,
    ),
    "Suction strainer blockage": (
        "Temporary start-up strainer had been left in place and was 70 percent "
        "blinded with weld slag.",
        "Removed the temporary strainer, flushed the suction line and confirmed "
        "suction pressure recovered to 2.4 barg.",
        5.0,
    ),
    "Upstream level drop": (
        "Deaerator level controller was cycling and periodically drove the level "
        "below the pump's NPSH-required margin.",
        "Retuned the level controller and raised the low-level alarm setpoint to "
        "give the operator earlier warning.",
        3.0,
    ),
    "Closed or throttled suction valve": (
        "Suction valve was throttled to 40 percent following a manual line-up error.",
        "Fully opened the suction valve and car-sealed it open. Toolbox talk "
        "delivered on suction valve line-up.",
        1.0,
    ),
    "Bearing wear": (
        "Vibration spectrum showed a clear bearing outer-race defect frequency with "
        "sidebands; grease sample confirmed metallic content.",
        "Replaced both radial bearings, re-greased to the OEM schedule and "
        "re-baselined the vibration route. Overall level fell from 9.2 to 2.8 mm/s.",
        12.0,
    ),
    "Shaft misalignment": (
        "Laser alignment found 0.42 mm parallel offset, well outside the 0.05 mm "
        "tolerance, caused by soft foot on the driver.",
        "Shimmed the driver feet to remove soft foot and realigned to within "
        "0.03 mm. Vibration returned to baseline.",
        8.0,
    ),
    "Impeller imbalance": (
        "Impeller had lost a balance weight and showed erosion on two vanes.",
        "Replaced the impeller with a spare, dynamically balanced to ISO G2.5.",
        16.0,
    ),
    "Bearing degradation": (
        "Thrust bearing babbitt showed wiping consistent with a transient loss of "
        "oil film during the previous trip.",
        "Replaced the thrust bearing pads and verified oil film pressure during "
        "a controlled restart.",
        18.0,
    ),
    "Lube oil pump degradation": (
        "Main lube oil pump internal clearances had opened up, reducing header "
        "pressure at rated speed.",
        "Overhauled the lube oil pump and verified the standby pump auto-start at "
        "the 1.2 barg setpoint.",
        9.0,
    ),
    "Filter differential high": (
        "Lube oil filter differential had reached 1.8 bar against a 1.0 bar "
        "changeover limit; the duty filter had not been swapped on schedule.",
        "Performed an online filter changeover and reinstated the PM task that had "
        "been deferred twice.",
        2.0,
    ),
    "Oil level low": (
        "Reservoir level was below the sight glass minimum due to a slow drain-line weep.",
        "Topped up the reservoir, repaired the drain line fitting and added a weekly level check.",
        3.5,
    ),
    "Anti-surge valve slow response": (
        "Anti-surge valve stroke time measured 4.8 s against a 2.0 s requirement; "
        "the volume booster was undersized after a previous positioner change.",
        "Fitted the correct volume booster and re-stroked the valve to 1.7 s. "
        "Surge margin verified on a controlled rate change.",
        10.0,
    ),
    "Discharge restriction": (
        "Downstream block valve had drifted closed on loss of instrument air to its actuator.",
        "Restored instrument air, reopened the block valve and added a low-air "
        "alarm on that header.",
        4.5,
    ),
    "Suction flow loss": (
        "Upstream knockout drum level control failed high and restricted suction "
        "flow to the machine.",
        "Recalibrated the level transmitter and restored normal suction flow.",
        5.5,
    ),
    "Cooling fan fouling": (
        "Motor cooling fan cowl was packed with process dust, reducing airflow by "
        "an estimated 60 percent.",
        "Cleaned the cowl and fan, and added a quarterly cleaning task to the PM "
        "schedule. Winding temperature dropped 22 degC.",
        2.5,
    ),
    "Sustained overload": (
        "Driven pump was running out on its curve after a downstream control valve "
        "was left in manual at 100 percent.",
        "Returned the control valve to automatic and confirmed motor current back "
        "within nameplate.",
        1.5,
    ),
    "Ambient temperature excursion": (
        "Local ambient reached 48 degC during a heatwave with the switchroom HVAC "
        "running degraded.",
        "Restored HVAC capacity and derated the machine until ambient recovered.",
        7.0,
    ),
    "Phase imbalance": (
        "One supply termination at the MCC had loosened, producing a 4.1 percent "
        "current imbalance.",
        "Re-torqued all three terminations to specification and thermographed the "
        "cubicle to confirm.",
        3.0,
    ),
    "Driven equipment binding": (
        "Pump wear rings had closed up after running dry briefly during the previous start.",
        "Replaced the wear rings and revised the start-up procedure to require "
        "confirmed suction flow before energising.",
        14.0,
    ),
    "Instrument air supply": (
        "Instrument air header pressure sagged below 5.0 barg when the standby "
        "compressor failed to auto-start.",
        "Repaired the auto-start circuit and function-tested the changeover.",
        4.0,
    ),
    "Positioner calibration drift": (
        "Valve positioner zero had drifted, producing a persistent 6 percent position deviation.",
        "Recalibrated the positioner and verified stroke at 0, 50 and 100 percent.",
        2.0,
    ),
    "Stem friction": (
        "Valve stem packing had been over-tightened at the last repack, causing stick-slip.",
        "Adjusted packing gland torque to specification and confirmed smooth travel.",
        3.0,
    ),
    "Feedwater flow loss": (
        "Standby feed pump failed to auto-start when the duty pump tripped on overload.",
        "Repaired the auto-start permissive and function-tested the changeover under load.",
        6.0,
    ),
    "Level transmitter drift": (
        "Drum level transmitter reference leg had partially drained, biasing the "
        "reading 80 mm high.",
        "Refilled and re-established the reference leg, then cross-checked against "
        "the gauge glass.",
        3.5,
    ),
    "Feed pump trip": (
        "Feed pump tripped on high bearing temperature, taking drum level with it.",
        "Addressed the bearing fault and restored the pump; drum level control "
        "returned to automatic.",
        8.5,
    ),
    "Intercooler fouling": (
        "Intercooler tube bundle was fouled on the cooling water side, raising "
        "interstage temperature by 18 degC.",
        "Chemically cleaned the bundle and restored design approach temperature.",
        11.0,
    ),
    "Tube-side fouling": (
        "Exchanger tube side was fouled with scale, driving differential pressure to 2.6 bar.",
        "Hydroblasted the tube side and restored differential pressure to 0.9 bar.",
        13.0,
    ),
    "Desiccant saturation": (
        "Desiccant had reached end of life and was no longer achieving the outlet "
        "dewpoint specification.",
        "Replaced both desiccant beds and verified -45 degC outlet dewpoint.",
        7.5,
    ),
}

GENERIC_RESOLUTION = (
    "Inspection confirmed the alarm was genuine and traceable to the condition described above.",
    "Corrected the condition, verified the process variable returned inside its "
    "normal operating envelope, and monitored for one full shift before closing.",
    5.0,
)

STATUS_WEIGHTS = (
    ("closed", 58),
    ("resolved", 22),
    ("in_progress", 11),
    ("open", 9),
)

PRIORITY_BY_SEVERITY_INDEX = ("P4", "P3", "P2", "P1")


def _priority(rng: random.Random, weights: tuple[int, int, int, int]) -> str:
    index = rng.choices(range(4), weights=weights, k=1)[0]
    return PRIORITY_BY_SEVERITY_INDEX[index]


def build_tickets() -> list[dict]:
    rng = random.Random(SEED)
    asset_ids = {spec.name: f"AST-{i:04d}" for i, spec in enumerate(ASSET_SPECS, start=1)}

    tickets: list[dict] = []
    counter = 1000

    # Walk every (asset, alarm template) pair and raise a few historical
    # tickets against the ones that matter, so "find similar tickets" has
    # more than one candidate for any realistic query.
    for spec in ASSET_SPECS:
        templates = TEMPLATES_BY_TYPE.get(spec.asset_type, ())
        for template in templates:
            # Two to four historical tickets per alarm type on critical and
            # high-criticality assets, fewer elsewhere.
            volume = {"critical": 3, "high": 2, "medium": 1, "low": 1}[spec.criticality.value]
            if rng.random() < 0.25:
                volume += 1
            for _ in range(volume):
                counter += 1
                created = DATA_NOW - timedelta(days=rng.randint(5, 520), hours=rng.randint(0, 23))
                status = rng.choices(
                    [s for s, _ in STATUS_WEIGHTS], weights=[w for _, w in STATUS_WEIGHTS], k=1
                )[0]
                cause = rng.choice(template.causes) if template.causes else None
                finding, action, hours = (
                    RESOLUTIONS.get(cause, GENERIC_RESOLUTION) if cause else GENERIC_RESOLUTION
                )
                hours = round(hours * rng.uniform(0.6, 1.5), 1)

                resolved_at = None
                resolution = None
                root_cause = None
                if status in {"resolved", "closed"}:
                    resolved_at = (created + timedelta(hours=hours)).isoformat()
                    resolution = action
                    root_cause = cause or "Condition confirmed and corrected in the field"

                description = (
                    f"{template.description} Raised against {spec.name} "
                    f"({spec.site} / {spec.unit}). "
                    + (
                        f"Reading breached the configured limit of "
                        f"{template.limit_value} {template.unit_of_measure}. "
                        if template.limit_value is not None and template.unit_of_measure
                        else ""
                    )
                    + (
                        f"Field investigation found: {finding}"
                        if status in {"resolved", "closed"}
                        else "Field investigation is in progress."
                    )
                )

                tickets.append(
                    {
                        "key": f"INC-{counter}",
                        "title": f"{template.name} on {spec.name}",
                        "description": description,
                        "status": status,
                        "priority": _priority(rng, template.severity_weights),
                        "asset_id": asset_ids[spec.name],
                        "asset_name": spec.name,
                        "asset_type": spec.asset_type,
                        "site": spec.site,
                        "unit": spec.unit,
                        "alarm_name": template.name,
                        "alarm_type": template.alarm_type.value,
                        "labels": sorted(
                            {
                                spec.asset_type,
                                template.alarm_type.value,
                                spec.unit.lower().replace(" ", "-"),
                                spec.site.lower(),
                                "alarm-driven",
                            }
                        ),
                        "assignee": rng.choice(ENGINEERS),
                        "reporter": "alarm-copilot"
                        if rng.random() < 0.2
                        else rng.choice(ENGINEERS),
                        "created_at": created.isoformat(),
                        "updated_at": (
                            resolved_at
                            or (created + timedelta(hours=rng.uniform(1, 40))).isoformat()
                        ),
                        "resolved_at": resolved_at,
                        "root_cause": root_cause,
                        "resolution": resolution,
                        "time_to_resolve_hours": hours if resolved_at else None,
                        "comments": [],
                        "linked_alarm_ids": [],
                    }
                )

    tickets.sort(key=lambda t: t["created_at"])
    # Re-key in chronological order so INC numbers increase with time.
    for index, ticket in enumerate(tickets, start=1001):
        ticket["key"] = f"INC-{index}"
    return tickets


def main() -> None:
    tickets = build_tickets()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(
            {
                "generated_by": "scripts/generate_ticket_seed.py",
                "seed": SEED,
                "count": len(tickets),
                "tickets": tickets,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    statuses: dict[str, int] = {}
    for ticket in tickets:
        statuses[ticket["status"]] = statuses.get(ticket["status"], 0) + 1
    print(f"wrote {len(tickets)} tickets to {OUTPUT.relative_to(ROOT)}")
    print(f"  statuses: {statuses}")
    print(f"  distinct assets: {len({t['asset_id'] for t in tickets})}")
    print(f"  distinct alarm names: {len({t['alarm_name'] for t in tickets})}")


if __name__ == "__main__":
    main()
