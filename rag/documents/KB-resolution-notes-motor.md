---
doc_id: KB-MOTOR
title: Historical Resolution Notes - Motor
doc_type: resolution_notes
revision: 1
effective_date: 2026-09-30
owner: Maintenance Knowledge Base
applies_to_asset_types: [motor]
applies_to_alarms: [Bearing Temperature High, Insulation Resistance Low, Motor Overload Trip, Motor Winding Temperature High, Phase Imbalance]
sites: [EastRefinery]
tags: [resolution-notes, history, motor, root-cause]
source: generated from resolved tickets by scripts/export_resolution_notes.py
---

# Historical Resolution Notes: Motor

Drawn from 39 resolved tickets across 1 site(s). Each section is a failure mode that has actually occurred on this class of asset, with what was found and what fixed it.

Median time to resolve across these cases: 4.8 hours.

## Bearing Temperature High - Lubrication degradation

Occurred 5 time(s) on this asset class. Tickets: INC-1020, INC-1088, INC-1176, INC-1184, INC-1229.

**What was found.** Inspection confirmed the alarm was genuine and traceable to the condition described above.

**What resolved it.** Corrected the condition, verified the process variable returned inside its normal operating envelope, and monitored for one full shift before closing.

**Typical effort.** 3.5 to 6.9 hours (5 recorded).

Recorded instances:

- `INC-1020` 2025-06-03 - Crude Charge Motor 501 (EastRefinery / Unit 5), priority P2
- `INC-1088` 2025-10-26 - Crude Charge Motor 501 (EastRefinery / Unit 5), priority P3
- `INC-1176` 2026-04-26 - Reflux Pump Motor 502 (EastRefinery / Unit 5), priority P4

## Insulation Resistance Low - Winding insulation ageing

Occurred 5 time(s) on this asset class. Tickets: INC-1124, INC-1126, INC-1149, INC-1170, INC-1206.

**What was found.** Inspection confirmed the alarm was genuine and traceable to the condition described above.

**What resolved it.** Corrected the condition, verified the process variable returned inside its normal operating envelope, and monitored for one full shift before closing.

**Typical effort.** 4.2 to 7.3 hours (5 recorded).

Recorded instances:

- `INC-1124` 2026-01-05 - Vacuum Tower Motor 503 (EastRefinery / Unit 5), priority P4
- `INC-1126` 2026-01-08 - Crude Charge Motor 501 (EastRefinery / Unit 5), priority P3
- `INC-1149` 2026-02-20 - Reflux Pump Motor 502 (EastRefinery / Unit 5), priority P4

## Motor Overload Trip - Phase imbalance

Occurred 5 time(s) on this asset class. Tickets: INC-1008, INC-1199, INC-1210, INC-1224, INC-1272.

**What was found.** One supply termination at the MCC had loosened, producing a 4.1 percent current imbalance.

**What resolved it.** Re-torqued all three terminations to specification and thermographed the cubicle to confirm.

**Typical effort.** 2.1 to 4.3 hours (5 recorded).

Recorded instances:

- `INC-1008` 2025-05-07 - Crude Charge Motor 501 (EastRefinery / Unit 5), priority P1
- `INC-1199` 2026-05-30 - Reflux Pump Motor 502 (EastRefinery / Unit 5), priority P1
- `INC-1210` 2026-06-10 - Vacuum Tower Motor 503 (EastRefinery / Unit 5), priority P1

## Phase Imbalance - Supply quality

Occurred 5 time(s) on this asset class. Tickets: INC-1005, INC-1121, INC-1236, INC-1247, INC-1263.

**What was found.** Inspection confirmed the alarm was genuine and traceable to the condition described above.

**What resolved it.** Corrected the condition, verified the process variable returned inside its normal operating envelope, and monitored for one full shift before closing.

**Typical effort.** 3.5 to 6.0 hours (5 recorded).

Recorded instances:

- `INC-1005` 2025-04-30 - Vacuum Tower Motor 503 (EastRefinery / Unit 5), priority P4
- `INC-1121` 2026-01-03 - Crude Charge Motor 501 (EastRefinery / Unit 5), priority P2
- `INC-1236` 2026-07-21 - Vacuum Tower Motor 503 (EastRefinery / Unit 5), priority P4

## Motor Winding Temperature High - Ambient temperature excursion

Occurred 4 time(s) on this asset class. Tickets: INC-1010, INC-1021, INC-1115, INC-1129.

**What was found.** Local ambient reached 48 degC during a heatwave with the switchroom HVAC running degraded.

**What resolved it.** Restored HVAC capacity and derated the machine until ambient recovered.

**Typical effort.** 7.7 to 10.3 hours (4 recorded).

Recorded instances:

- `INC-1010` 2025-05-10 - Crude Charge Motor 501 (EastRefinery / Unit 5), priority P2
- `INC-1021` 2025-06-06 - Vacuum Tower Motor 503 (EastRefinery / Unit 5), priority P2
- `INC-1115` 2025-12-25 - Crude Charge Motor 501 (EastRefinery / Unit 5), priority P3

## Phase Imbalance - Loose termination

Occurred 4 time(s) on this asset class. Tickets: INC-1001, INC-1015, INC-1039, INC-1094.

**What was found.** Inspection confirmed the alarm was genuine and traceable to the condition described above.

**What resolved it.** Corrected the condition, verified the process variable returned inside its normal operating envelope, and monitored for one full shift before closing.

**Typical effort.** 3.1 to 7.4 hours (4 recorded).

Recorded instances:

- `INC-1001` 2025-04-28 - Crude Charge Motor 501 (EastRefinery / Unit 5), priority P4
- `INC-1015` 2025-05-23 - Reflux Pump Motor 502 (EastRefinery / Unit 5), priority P4
- `INC-1039` 2025-07-21 - Crude Charge Motor 501 (EastRefinery / Unit 5), priority P2

## Bearing Temperature High - Misalignment

Occurred 3 time(s) on this asset class. Tickets: INC-1042, INC-1078, INC-1180.

**What was found.** Inspection confirmed the alarm was genuine and traceable to the condition described above.

**What resolved it.** Corrected the condition, verified the process variable returned inside its normal operating envelope, and monitored for one full shift before closing.

**Typical effort.** 4.5 to 7.0 hours (3 recorded).

Recorded instances:

- `INC-1042` 2025-07-24 - Induced Draft Fan Motor 504 (EastRefinery / Unit 5), priority P4
- `INC-1078` 2025-10-06 - Vacuum Tower Motor 503 (EastRefinery / Unit 5), priority P3
- `INC-1180` 2026-05-01 - Vacuum Tower Motor 503 (EastRefinery / Unit 5), priority P2

## Motor Overload Trip - Driven equipment binding

Occurred 2 time(s) on this asset class. Tickets: INC-1049, INC-1164.

**What was found.** Pump wear rings had closed up after running dry briefly during the previous start.

**What resolved it.** Replaced the wear rings and revised the start-up procedure to require confirmed suction flow before energising.

**Typical effort.** 13.0 to 20.4 hours (2 recorded).

Recorded instances:

- `INC-1049` 2025-08-11 - Crude Charge Motor 501 (EastRefinery / Unit 5), priority P1
- `INC-1164` 2026-03-26 - Induced Draft Fan Motor 504 (EastRefinery / Unit 5), priority P1

## Motor Winding Temperature High - Cooling fan fouling

Occurred 2 time(s) on this asset class. Tickets: INC-1147, INC-1237.

**What was found.** Motor cooling fan cowl was packed with process dust, reducing airflow by an estimated 60 percent.

**What resolved it.** Cleaned the cowl and fan, and added a quarterly cleaning task to the PM schedule. Winding temperature dropped 22 degC.

**Typical effort.** 2.1 to 2.1 hours (2 recorded).

Recorded instances:

- `INC-1147` 2026-02-15 - Reflux Pump Motor 502 (EastRefinery / Unit 5), priority P3
- `INC-1237` 2026-07-21 - Reflux Pump Motor 502 (EastRefinery / Unit 5), priority P3

## Bearing Temperature High - Bearing wear

Occurred 1 time(s) on this asset class. Tickets: INC-1141.

**What was found.** Vibration spectrum showed a clear bearing outer-race defect frequency with sidebands; grease sample confirmed metallic content.

**What resolved it.** Replaced both radial bearings, re-greased to the OEM schedule and re-baselined the vibration route. Overall level fell from 9.2 to 2.8 mm/s.

**Typical effort.** 13.6 to 13.6 hours (1 recorded).

## Insulation Resistance Low - Moisture ingress

Occurred 1 time(s) on this asset class. Tickets: INC-1193.

**What was found.** Inspection confirmed the alarm was genuine and traceable to the condition described above.

**What resolved it.** Corrected the condition, verified the process variable returned inside its normal operating envelope, and monitored for one full shift before closing.

**Typical effort.** 7.1 to 7.1 hours (1 recorded).

## Motor Overload Trip - Sustained winding temperature excursion

Occurred 1 time(s) on this asset class. Tickets: INC-1268.

**What was found.** Inspection confirmed the alarm was genuine and traceable to the condition described above.

**What resolved it.** Corrected the condition, verified the process variable returned inside its normal operating envelope, and monitored for one full shift before closing.

**Typical effort.** 6.4 to 6.4 hours (1 recorded).

## Motor Winding Temperature High - Sustained overload

Occurred 1 time(s) on this asset class. Tickets: INC-1204.

**What was found.** Driven pump was running out on its curve after a downstream control valve was left in manual at 100 percent.

**What resolved it.** Returned the control valve to automatic and confirmed motor current back within nameplate.

**Typical effort.** 1.1 to 1.1 hours (1 recorded).
