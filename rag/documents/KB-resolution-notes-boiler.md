---
doc_id: KB-BOILER
title: Historical Resolution Notes - Boiler
doc_type: resolution_notes
revision: 1
effective_date: 2026-09-30
owner: Maintenance Knowledge Base
applies_to_asset_types: [boiler]
applies_to_alarms: [Drum Level High, Drum Level Low, Flame Failure, Tube Metal Temperature High]
sites: [EastRefinery, NorthPlant]
tags: [resolution-notes, history, boiler, root-cause]
source: generated from resolved tickets by scripts/export_resolution_notes.py
---

# Historical Resolution Notes: Boiler

Drawn from 17 resolved tickets across 2 site(s). Each section is a failure mode that has actually occurred on this class of asset, with what was found and what fixed it.

Median time to resolve across these cases: 5.6 hours.

## Drum Level High - Feed control valve overshoot

Occurred 3 time(s) on this asset class. Tickets: INC-1041, INC-1174, INC-1261.

**What was found.** Inspection confirmed the alarm was genuine and traceable to the condition described above.

**What resolved it.** Corrected the condition, verified the process variable returned inside its normal operating envelope, and monitored for one full shift before closing.

**Typical effort.** 3.3 to 5.9 hours (3 recorded).

Recorded instances:

- `INC-1041` 2025-07-21 - Boiler Drum 101 (NorthPlant / Unit 1), priority P3
- `INC-1174` 2026-04-17 - Stripper Reboiler 601 (EastRefinery / Unit 6), priority P3
- `INC-1261` 2026-08-27 - Boiler Drum 101 (NorthPlant / Unit 1), priority P4

## Drum Level Low - Feed pump trip

Occurred 3 time(s) on this asset class. Tickets: INC-1031, INC-1062, INC-1122.

**What was found.** Feed pump tripped on high bearing temperature, taking drum level with it.

**What resolved it.** Addressed the bearing fault and restored the pump; drum level control returned to automatic.

**Typical effort.** 5.9 to 10.6 hours (3 recorded).

Recorded instances:

- `INC-1031` 2025-07-09 - Boiler Drum 101 (NorthPlant / Unit 1), priority P1
- `INC-1062` 2025-09-12 - Boiler Drum 101 (NorthPlant / Unit 1), priority P1
- `INC-1122` 2026-01-05 - Stripper Reboiler 601 (EastRefinery / Unit 6), priority P2

## Flame Failure - Fuel gas pressure excursion

Occurred 3 time(s) on this asset class. Tickets: INC-1056, INC-1099, INC-1166.

**What was found.** Inspection confirmed the alarm was genuine and traceable to the condition described above.

**What resolved it.** Corrected the condition, verified the process variable returned inside its normal operating envelope, and monitored for one full shift before closing.

**Typical effort.** 5.3 to 6.9 hours (3 recorded).

Recorded instances:

- `INC-1056` 2025-08-28 - Stripper Reboiler 601 (EastRefinery / Unit 6), priority P1
- `INC-1099` 2025-11-23 - Boiler Drum 101 (NorthPlant / Unit 1), priority P1
- `INC-1166` 2026-04-01 - Boiler Drum 101 (NorthPlant / Unit 1), priority P1

## Tube Metal Temperature High - Steam flow maldistribution

Occurred 3 time(s) on this asset class. Tickets: INC-1053, INC-1066, INC-1123.

**What was found.** Inspection confirmed the alarm was genuine and traceable to the condition described above.

**What resolved it.** Corrected the condition, verified the process variable returned inside its normal operating envelope, and monitored for one full shift before closing.

**Typical effort.** 3.6 to 5.1 hours (3 recorded).

Recorded instances:

- `INC-1053` 2025-08-19 - Boiler Drum 101 (NorthPlant / Unit 1), priority P3
- `INC-1066` 2025-09-17 - Boiler Drum 101 (NorthPlant / Unit 1), priority P3
- `INC-1123` 2026-01-05 - Stripper Reboiler 601 (EastRefinery / Unit 6), priority P3

## Drum Level High - Swell on load change

Occurred 2 time(s) on this asset class. Tickets: INC-1061, INC-1221.

**What was found.** Inspection confirmed the alarm was genuine and traceable to the condition described above.

**What resolved it.** Corrected the condition, verified the process variable returned inside its normal operating envelope, and monitored for one full shift before closing.

**Typical effort.** 5.2 to 5.6 hours (2 recorded).

Recorded instances:

- `INC-1061` 2025-09-10 - Stripper Reboiler 601 (EastRefinery / Unit 6), priority P3
- `INC-1221` 2026-06-27 - Boiler Drum 101 (NorthPlant / Unit 1), priority P2

## Drum Level Low - Feedwater flow loss

Occurred 1 time(s) on this asset class. Tickets: INC-1235.

**What was found.** Standby feed pump failed to auto-start when the duty pump tripped on overload.

**What resolved it.** Repaired the auto-start permissive and function-tested the changeover under load.

**Typical effort.** 7.3 to 7.3 hours (1 recorded).

## Flame Failure - Scanner fouling

Occurred 1 time(s) on this asset class. Tickets: INC-1100.

**What was found.** Inspection confirmed the alarm was genuine and traceable to the condition described above.

**What resolved it.** Corrected the condition, verified the process variable returned inside its normal operating envelope, and monitored for one full shift before closing.

**Typical effort.** 6.9 to 6.9 hours (1 recorded).

## Tube Metal Temperature High - Localised fouling

Occurred 1 time(s) on this asset class. Tickets: INC-1218.

**What was found.** Inspection confirmed the alarm was genuine and traceable to the condition described above.

**What resolved it.** Corrected the condition, verified the process variable returned inside its normal operating envelope, and monitored for one full shift before closing.

**Typical effort.** 3.6 to 3.6 hours (1 recorded).
