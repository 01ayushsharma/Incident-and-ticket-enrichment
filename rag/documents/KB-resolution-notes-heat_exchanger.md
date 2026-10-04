---
doc_id: KB-HEATEX
title: Historical Resolution Notes - Heat Exchanger
doc_type: resolution_notes
revision: 1
effective_date: 2026-09-30
owner: Maintenance Knowledge Base
applies_to_asset_types: [heat_exchanger]
applies_to_alarms: [High Differential Pressure, Outlet Temperature High, Tube Leak Suspected]
sites: [EastRefinery, NorthPlant, SouthPlant]
tags: [resolution-notes, history, heat_exchanger, root-cause]
source: generated from resolved tickets by scripts/export_resolution_notes.py
---

# Historical Resolution Notes: Heat Exchanger

Drawn from 8 resolved tickets across 3 site(s). Each section is a failure mode that has actually occurred on this class of asset, with what was found and what fixed it.

Median time to resolve across these cases: 7.3 hours.

## Outlet Temperature High - Cooling medium flow loss

Occurred 4 time(s) on this asset class. Tickets: INC-1158, INC-1194, INC-1203, INC-1265.

**What was found.** Inspection confirmed the alarm was genuine and traceable to the condition described above.

**What resolved it.** Corrected the condition, verified the process variable returned inside its normal operating envelope, and monitored for one full shift before closing.

**Typical effort.** 3.1 to 7.3 hours (4 recorded).

Recorded instances:

- `INC-1158` 2026-03-18 - Feedwater Heat Exchanger 101 (NorthPlant / Unit 1), priority P2
- `INC-1194` 2026-05-24 - Reactor Effluent Exchanger 601 (EastRefinery / Unit 6), priority P3
- `INC-1203` 2026-06-04 - Process Gas Cooler 401 (SouthPlant / Unit 4), priority P3

## High Differential Pressure - Tube-side fouling

Occurred 2 time(s) on this asset class. Tickets: INC-1155, INC-1248.

**What was found.** Exchanger tube side was fouled with scale, driving differential pressure to 2.6 bar.

**What resolved it.** Hydroblasted the tube side and restored differential pressure to 0.9 bar.

**Typical effort.** 10.7 to 19.5 hours (2 recorded).

Recorded instances:

- `INC-1155` 2026-03-10 - Feedwater Heat Exchanger 101 (NorthPlant / Unit 1), priority P3
- `INC-1248` 2026-08-03 - Process Gas Cooler 401 (SouthPlant / Unit 4), priority P4

## Outlet Temperature High - Fouling

Occurred 1 time(s) on this asset class. Tickets: INC-1059.

**What was found.** Inspection confirmed the alarm was genuine and traceable to the condition described above.

**What resolved it.** Corrected the condition, verified the process variable returned inside its normal operating envelope, and monitored for one full shift before closing.

**Typical effort.** 4.0 to 4.0 hours (1 recorded).

## Tube Leak Suspected - Thermal cycling fatigue

Occurred 1 time(s) on this asset class. Tickets: INC-1233.

**What was found.** Inspection confirmed the alarm was genuine and traceable to the condition described above.

**What resolved it.** Corrected the condition, verified the process variable returned inside its normal operating envelope, and monitored for one full shift before closing.

**Typical effort.** 7.3 to 7.3 hours (1 recorded).
