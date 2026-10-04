---
doc_id: KB-COMPRE
title: Historical Resolution Notes - Compressor
doc_type: resolution_notes
revision: 1
effective_date: 2026-09-30
owner: Maintenance Knowledge Base
applies_to_asset_types: [compressor]
applies_to_alarms: [High Discharge Pressure, High Vibration, Interstage Temperature High, Lube Oil Pressure Low, Surge Detected]
sites: [EastRefinery, SouthPlant]
tags: [resolution-notes, history, compressor, root-cause]
source: generated from resolved tickets by scripts/export_resolution_notes.py
---

# Historical Resolution Notes: Compressor

Drawn from 49 resolved tickets across 2 site(s). Each section is a failure mode that has actually occurred on this class of asset, with what was found and what fixed it.

Median time to resolve across these cases: 6.5 hours.

## High Discharge Pressure - Downstream valve closure

Occurred 6 time(s) on this asset class. Tickets: INC-1016, INC-1017, INC-1040, INC-1120, INC-1228, INC-1230.

**What was found.** Inspection confirmed the alarm was genuine and traceable to the condition described above.

**What resolved it.** Corrected the condition, verified the process variable returned inside its normal operating envelope, and monitored for one full shift before closing.

**Typical effort.** 4.2 to 7.4 hours (6 recorded).

Recorded instances:

- `INC-1016` 2025-05-24 - Recycle Gas Compressor 601 (EastRefinery / Unit 6), priority P3
- `INC-1017` 2025-05-25 - Recycle Gas Compressor 601 (EastRefinery / Unit 6), priority P2
- `INC-1040` 2025-07-21 - Centrifugal Compressor 401 (SouthPlant / Unit 4), priority P2

## High Discharge Pressure - Cooler fouling

Occurred 5 time(s) on this asset class. Tickets: INC-1013, INC-1029, INC-1169, INC-1181, INC-1195.

**What was found.** Inspection confirmed the alarm was genuine and traceable to the condition described above.

**What resolved it.** Corrected the condition, verified the process variable returned inside its normal operating envelope, and monitored for one full shift before closing.

**Typical effort.** 4.5 to 7.3 hours (5 recorded).

Recorded instances:

- `INC-1013` 2025-05-17 - Reciprocating Compressor 301 (SouthPlant / Unit 3), priority P4
- `INC-1029` 2025-07-05 - Reciprocating Compressor 302 (SouthPlant / Unit 3), priority P3
- `INC-1169` 2026-04-03 - Reciprocating Compressor 301 (SouthPlant / Unit 3), priority P2

## High Vibration - Bearing degradation

Occurred 5 time(s) on this asset class. Tickets: INC-1050, INC-1144, INC-1146, INC-1214, INC-1245.

**What was found.** Thrust bearing babbitt showed wiping consistent with a transient loss of oil film during the previous trip.

**What resolved it.** Replaced the thrust bearing pads and verified oil film pressure during a controlled restart.

**Typical effort.** 12.9 to 26.8 hours (5 recorded).

Recorded instances:

- `INC-1050` 2025-08-15 - Reciprocating Compressor 302 (SouthPlant / Unit 3), priority P2
- `INC-1144` 2026-02-07 - Recycle Gas Compressor 601 (EastRefinery / Unit 6), priority P1
- `INC-1146` 2026-02-11 - Centrifugal Compressor 401 (SouthPlant / Unit 4), priority P3

## Interstage Temperature High - Valve leakage

Occurred 5 time(s) on this asset class. Tickets: INC-1033, INC-1038, INC-1070, INC-1082, INC-1087.

**What was found.** Inspection confirmed the alarm was genuine and traceable to the condition described above.

**What resolved it.** Corrected the condition, verified the process variable returned inside its normal operating envelope, and monitored for one full shift before closing.

**Typical effort.** 3.2 to 6.7 hours (5 recorded).

Recorded instances:

- `INC-1033` 2025-07-14 - Reciprocating Compressor 301 (SouthPlant / Unit 3), priority P4
- `INC-1038` 2025-07-20 - Recycle Gas Compressor 601 (EastRefinery / Unit 6), priority P4
- `INC-1070` 2025-09-23 - Reciprocating Compressor 301 (SouthPlant / Unit 3), priority P4

## Surge Detected - Anti-surge valve slow response

Occurred 5 time(s) on this asset class. Tickets: INC-1058, INC-1162, INC-1198, INC-1255, INC-1262.

**What was found.** Anti-surge valve stroke time measured 4.8 s against a 2.0 s requirement; the volume booster was undersized after a previous positioner change.

**What resolved it.** Fitted the correct volume booster and re-stroked the valve to 1.7 s. Surge margin verified on a controlled rate change.

**Typical effort.** 6.5 to 13.4 hours (5 recorded).

Recorded instances:

- `INC-1058` 2025-08-29 - Reciprocating Compressor 302 (SouthPlant / Unit 3), priority P2
- `INC-1162` 2026-03-24 - Reciprocating Compressor 301 (SouthPlant / Unit 3), priority P2
- `INC-1198` 2026-05-29 - Recycle Gas Compressor 601 (EastRefinery / Unit 6), priority P3

## High Vibration - Rotor imbalance

Occurred 4 time(s) on this asset class. Tickets: INC-1025, INC-1110, INC-1225, INC-1264.

**What was found.** Inspection confirmed the alarm was genuine and traceable to the condition described above.

**What resolved it.** Corrected the condition, verified the process variable returned inside its normal operating envelope, and monitored for one full shift before closing.

**Typical effort.** 5.4 to 6.8 hours (4 recorded).

Recorded instances:

- `INC-1025` 2025-06-24 - Reciprocating Compressor 301 (SouthPlant / Unit 3), priority P3
- `INC-1110` 2025-12-19 - Recycle Gas Compressor 601 (EastRefinery / Unit 6), priority P3
- `INC-1225` 2026-07-03 - Recycle Gas Compressor 601 (EastRefinery / Unit 6), priority P2

## Interstage Temperature High - Intercooler fouling

Occurred 4 time(s) on this asset class. Tickets: INC-1012, INC-1157, INC-1187, INC-1208.

**What was found.** Intercooler tube bundle was fouled on the cooling water side, raising interstage temperature by 18 degC.

**What resolved it.** Chemically cleaned the bundle and restored design approach temperature.

**Typical effort.** 7.5 to 11.8 hours (4 recorded).

Recorded instances:

- `INC-1012` 2025-05-13 - Recycle Gas Compressor 601 (EastRefinery / Unit 6), priority P3
- `INC-1157` 2026-03-14 - Reciprocating Compressor 301 (SouthPlant / Unit 3), priority P3
- `INC-1187` 2026-05-06 - Reciprocating Compressor 302 (SouthPlant / Unit 3), priority P3

## Lube Oil Pressure Low - Filter differential high

Occurred 4 time(s) on this asset class. Tickets: INC-1028, INC-1107, INC-1135, INC-1216.

**What was found.** Lube oil filter differential had reached 1.8 bar against a 1.0 bar changeover limit; the duty filter had not been swapped on schedule.

**What resolved it.** Performed an online filter changeover and reinstated the PM task that had been deferred twice.

**Typical effort.** 1.5 to 2.5 hours (4 recorded).

Recorded instances:

- `INC-1028` 2025-07-01 - Reciprocating Compressor 301 (SouthPlant / Unit 3), priority P4
- `INC-1107` 2025-12-16 - Reciprocating Compressor 301 (SouthPlant / Unit 3), priority P1
- `INC-1135` 2026-01-25 - Recycle Gas Compressor 601 (EastRefinery / Unit 6), priority P1

## Lube Oil Pressure Low - Lube oil pump degradation

Occurred 4 time(s) on this asset class. Tickets: INC-1018, INC-1137, INC-1142, INC-1192.

**What was found.** Main lube oil pump internal clearances had opened up, reducing header pressure at rated speed.

**What resolved it.** Overhauled the lube oil pump and verified the standby pump auto-start at the 1.2 barg setpoint.

**Typical effort.** 7.1 to 13.1 hours (4 recorded).

Recorded instances:

- `INC-1018` 2025-05-28 - Reciprocating Compressor 301 (SouthPlant / Unit 3), priority P1
- `INC-1137` 2026-02-02 - Reciprocating Compressor 302 (SouthPlant / Unit 3), priority P1
- `INC-1142` 2026-02-06 - Centrifugal Compressor 401 (SouthPlant / Unit 4), priority P4

## Surge Detected - Suction flow loss

Occurred 3 time(s) on this asset class. Tickets: INC-1138, INC-1222, INC-1260.

**What was found.** Upstream knockout drum level control failed high and restricted suction flow to the machine.

**What resolved it.** Recalibrated the level transmitter and restored normal suction flow.

**Typical effort.** 3.9 to 6.3 hours (3 recorded).

Recorded instances:

- `INC-1138` 2026-02-03 - Centrifugal Compressor 401 (SouthPlant / Unit 4), priority P4
- `INC-1222` 2026-06-27 - Centrifugal Compressor 401 (SouthPlant / Unit 4), priority P3
- `INC-1260` 2026-08-26 - Recycle Gas Compressor 601 (EastRefinery / Unit 6), priority P1

## Lube Oil Pressure Low - Oil level low

Occurred 2 time(s) on this asset class. Tickets: INC-1127, INC-1165.

**What was found.** Reservoir level was below the sight glass minimum due to a slow drain-line weep.

**What resolved it.** Topped up the reservoir, repaired the drain line fitting and added a weekly level check.

**Typical effort.** 3.1 to 4.6 hours (2 recorded).

Recorded instances:

- `INC-1127` 2026-01-09 - Reciprocating Compressor 301 (SouthPlant / Unit 3), priority P2
- `INC-1165` 2026-03-30 - Recycle Gas Compressor 601 (EastRefinery / Unit 6), priority P1

## Surge Detected - Discharge restriction

Occurred 2 time(s) on this asset class. Tickets: INC-1054, INC-1186.

**What was found.** Downstream block valve had drifted closed on loss of instrument air to its actuator.

**What resolved it.** Restored instrument air, reopened the block valve and added a low-air alarm on that header.

**Typical effort.** 3.0 to 6.5 hours (2 recorded).

Recorded instances:

- `INC-1054` 2025-08-20 - Reciprocating Compressor 301 (SouthPlant / Unit 3), priority P4
- `INC-1186` 2026-05-05 - Centrifugal Compressor 401 (SouthPlant / Unit 4), priority P3
