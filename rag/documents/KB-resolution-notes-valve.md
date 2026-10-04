---
doc_id: KB-VALVE
title: Historical Resolution Notes - Valve
doc_type: resolution_notes
revision: 1
effective_date: 2026-09-30
owner: Maintenance Knowledge Base
applies_to_asset_types: [valve]
applies_to_alarms: [Instrument Air Pressure Low, Valve Position Deviation, Valve Stuck]
sites: [EastRefinery, NorthPlant, SouthPlant]
tags: [resolution-notes, history, valve, root-cause]
source: generated from resolved tickets by scripts/export_resolution_notes.py
---

# Historical Resolution Notes: Valve

Drawn from 25 resolved tickets across 3 site(s). Each section is a failure mode that has actually occurred on this class of asset, with what was found and what fixed it.

Median time to resolve across these cases: 4.7 hours.

## Instrument Air Pressure Low - Air compressor trip

Occurred 6 time(s) on this asset class. Tickets: INC-1003, INC-1114, INC-1119, INC-1156, INC-1189, INC-1209.

**What was found.** Inspection confirmed the alarm was genuine and traceable to the condition described above.

**What resolved it.** Corrected the condition, verified the process variable returned inside its normal operating envelope, and monitored for one full shift before closing.

**Typical effort.** 3.1 to 7.5 hours (6 recorded).

Recorded instances:

- `INC-1003` 2025-04-30 - Safety Shutdown Valve 601 (EastRefinery / Unit 6), priority P3
- `INC-1114` 2025-12-25 - Makeup Water Valve 201 (NorthPlant / Unit 2), priority P4
- `INC-1119` 2026-01-02 - Safety Shutdown Valve 601 (EastRefinery / Unit 6), priority P3

## Valve Stuck - Loss of instrument air

Occurred 5 time(s) on this asset class. Tickets: INC-1081, INC-1090, INC-1113, INC-1223, INC-1267.

**What was found.** Inspection confirmed the alarm was genuine and traceable to the condition described above.

**What resolved it.** Corrected the condition, verified the process variable returned inside its normal operating envelope, and monitored for one full shift before closing.

**Typical effort.** 4.5 to 6.1 hours (5 recorded).

Recorded instances:

- `INC-1081` 2025-10-16 - Safety Shutdown Valve 601 (EastRefinery / Unit 6), priority P3
- `INC-1090` 2025-11-02 - Safety Shutdown Valve 601 (EastRefinery / Unit 6), priority P3
- `INC-1113` 2025-12-22 - Makeup Water Valve 201 (NorthPlant / Unit 2), priority P3

## Instrument Air Pressure Low - Header leak

Occurred 3 time(s) on this asset class. Tickets: INC-1011, INC-1139, INC-1213.

**What was found.** Inspection confirmed the alarm was genuine and traceable to the condition described above.

**What resolved it.** Corrected the condition, verified the process variable returned inside its normal operating envelope, and monitored for one full shift before closing.

**Typical effort.** 4.0 to 5.6 hours (3 recorded).

Recorded instances:

- `INC-1011` 2025-05-11 - Flare Header Valve 401 (SouthPlant / Unit 4), priority P1
- `INC-1139` 2026-02-03 - Safety Shutdown Valve 601 (EastRefinery / Unit 6), priority P1
- `INC-1213` 2026-06-17 - Makeup Water Valve 201 (NorthPlant / Unit 2), priority P3

## Valve Position Deviation - Actuator air supply

Occurred 3 time(s) on this asset class. Tickets: INC-1102, INC-1168, INC-1217.

**What was found.** Inspection confirmed the alarm was genuine and traceable to the condition described above.

**What resolved it.** Corrected the condition, verified the process variable returned inside its normal operating envelope, and monitored for one full shift before closing.

**Typical effort.** 3.2 to 6.6 hours (3 recorded).

Recorded instances:

- `INC-1102` 2025-12-08 - Flare Header Valve 401 (SouthPlant / Unit 4), priority P4
- `INC-1168` 2026-04-02 - Safety Shutdown Valve 601 (EastRefinery / Unit 6), priority P4
- `INC-1217` 2026-06-20 - Safety Shutdown Valve 601 (EastRefinery / Unit 6), priority P4

## Valve Position Deviation - Positioner calibration drift

Occurred 3 time(s) on this asset class. Tickets: INC-1085, INC-1215, INC-1254.

**What was found.** Valve positioner zero had drifted, producing a persistent 6 percent position deviation.

**What resolved it.** Recalibrated the positioner and verified stroke at 0, 50 and 100 percent.

**Typical effort.** 1.2 to 2.2 hours (3 recorded).

Recorded instances:

- `INC-1085` 2025-10-19 - Makeup Water Valve 201 (NorthPlant / Unit 2), priority P3
- `INC-1215` 2026-06-18 - Flare Header Valve 401 (SouthPlant / Unit 4), priority P4
- `INC-1254` 2026-08-13 - Safety Shutdown Valve 601 (EastRefinery / Unit 6), priority P2

## Valve Stuck - Stem galling

Occurred 3 time(s) on this asset class. Tickets: INC-1068, INC-1091, INC-1092.

**What was found.** Inspection confirmed the alarm was genuine and traceable to the condition described above.

**What resolved it.** Corrected the condition, verified the process variable returned inside its normal operating envelope, and monitored for one full shift before closing.

**Typical effort.** 3.0 to 6.4 hours (3 recorded).

Recorded instances:

- `INC-1068` 2025-09-21 - Safety Shutdown Valve 601 (EastRefinery / Unit 6), priority P2
- `INC-1091` 2025-11-02 - Flare Header Valve 401 (SouthPlant / Unit 4), priority P3
- `INC-1092` 2025-11-04 - Flare Header Valve 401 (SouthPlant / Unit 4), priority P3

## Valve Position Deviation - Stem friction

Occurred 2 time(s) on this asset class. Tickets: INC-1071, INC-1205.

**What was found.** Valve stem packing had been over-tightened at the last repack, causing stick-slip.

**What resolved it.** Adjusted packing gland torque to specification and confirmed smooth travel.

**Typical effort.** 3.0 to 3.5 hours (2 recorded).

Recorded instances:

- `INC-1071` 2025-09-23 - Safety Shutdown Valve 601 (EastRefinery / Unit 6), priority P2
- `INC-1205` 2026-06-06 - Makeup Water Valve 201 (NorthPlant / Unit 2), priority P4
