---
doc_id: KB-PUMP
title: Historical Resolution Notes - Pump
doc_type: resolution_notes
revision: 1
effective_date: 2026-09-30
owner: Maintenance Knowledge Base
applies_to_asset_types: [pump]
applies_to_alarms: [High Discharge Temperature, High Vibration, Low Suction Pressure, Motor Overload, Seal Leak Detected]
sites: [EastRefinery, NorthPlant, SouthPlant]
tags: [resolution-notes, history, pump, root-cause]
source: generated from resolved tickets by scripts/export_resolution_notes.py
---

# Historical Resolution Notes: Pump

Drawn from 76 resolved tickets across 3 site(s). Each section is a failure mode that has actually occurred on this class of asset, with what was found and what fixed it.

Median time to resolve across these cases: 5.7 hours.

## Low Suction Pressure - Upstream level drop

Occurred 10 time(s) on this asset class. Tickets: INC-1014, INC-1047, INC-1051, INC-1106, INC-1117, INC-1183 and others.

**What was found.** Deaerator level controller was cycling and periodically drove the level below the pump's NPSH-required margin.

**What resolved it.** Retuned the level controller and raised the low-level alarm setpoint to give the operator earlier warning.

**Typical effort.** 2.4 to 4.4 hours (10 recorded).

Recorded instances:

- `INC-1014` 2025-05-18 - Hydrotreater Feed Pump 601 (EastRefinery / Unit 6), priority P4
- `INC-1047` 2025-08-10 - Crude Charge Pump 501 (EastRefinery / Unit 5), priority P2
- `INC-1051` 2025-08-17 - Crude Charge Pump 501 (EastRefinery / Unit 5), priority P3

## Motor Overload - Mechanical binding

Occurred 9 time(s) on this asset class. Tickets: INC-1045, INC-1077, INC-1093, INC-1098, INC-1104, INC-1128 and others.

**What was found.** Inspection confirmed the alarm was genuine and traceable to the condition described above.

**What resolved it.** Corrected the condition, verified the process variable returned inside its normal operating envelope, and monitored for one full shift before closing.

**Typical effort.** 3.1 to 7.2 hours (9 recorded).

Recorded instances:

- `INC-1045` 2025-08-03 - Circulating Water Pump 202 (NorthPlant / Unit 2), priority P2
- `INC-1077` 2025-10-05 - Condensate Pump 201 (NorthPlant / Unit 2), priority P2
- `INC-1093` 2025-11-09 - Circulating Water Pump 202 (NorthPlant / Unit 2), priority P2

## High Discharge Temperature - Recirculation line fouling

Occurred 7 time(s) on this asset class. Tickets: INC-1034, INC-1044, INC-1079, INC-1161, INC-1201, INC-1219 and others.

**What was found.** Minimum-flow recirculation orifice was fouled, holding the pump below its minimum continuous stable flow at low plant rates.

**What resolved it.** Isolated and cleaned the recirculation orifice, then verified minimum flow at 30 percent plant rate.

**Typical effort.** 2.4 to 5.9 hours (7 recorded).

Recorded instances:

- `INC-1034` 2025-07-15 - Hydrotreater Feed Pump 601 (EastRefinery / Unit 6), priority P4
- `INC-1044` 2025-07-29 - Circulating Water Pump 202 (NorthPlant / Unit 2), priority P3
- `INC-1079` 2025-10-07 - Crude Charge Pump 501 (EastRefinery / Unit 5), priority P3

## Seal Leak Detected - Seal face wear

Occurred 7 time(s) on this asset class. Tickets: INC-1007, INC-1130, INC-1134, INC-1160, INC-1163, INC-1188 and others.

**What was found.** Inspection confirmed the alarm was genuine and traceable to the condition described above.

**What resolved it.** Corrected the condition, verified the process variable returned inside its normal operating envelope, and monitored for one full shift before closing.

**Typical effort.** 3.6 to 7.3 hours (7 recorded).

Recorded instances:

- `INC-1007` 2025-05-01 - Condensate Pump 201 (NorthPlant / Unit 2), priority P2
- `INC-1130` 2026-01-14 - Compressor Lube Oil Pump 301 (SouthPlant / Unit 3), priority P4
- `INC-1134` 2026-01-20 - Hydrotreater Feed Pump 601 (EastRefinery / Unit 6), priority P2

## High Discharge Temperature - Degraded mechanical seal

Occurred 6 time(s) on this asset class. Tickets: INC-1002, INC-1046, INC-1084, INC-1096, INC-1212, INC-1271.

**What was found.** Seal faces showed circumferential scoring and the flush line orifice was partially blocked with scale.

**What resolved it.** Replaced the cartridge seal, cleaned the API Plan 11 flush orifice and re-established flush flow. Discharge temperature returned to 71 degC.

**Typical effort.** 6.3 to 8.9 hours (6 recorded).

Recorded instances:

- `INC-1002` 2025-04-28 - Boiler Feed Pump 101 (NorthPlant / Unit 1), priority P2
- `INC-1046` 2025-08-07 - Circulating Water Pump 202 (NorthPlant / Unit 2), priority P3
- `INC-1084` 2025-10-19 - Compressor Lube Oil Pump 301 (SouthPlant / Unit 3), priority P2

## High Vibration - Impeller imbalance

Occurred 6 time(s) on this asset class. Tickets: INC-1035, INC-1064, INC-1065, INC-1083, INC-1190, INC-1269.

**What was found.** Impeller had lost a balance weight and showed erosion on two vanes.

**What resolved it.** Replaced the impeller with a spare, dynamically balanced to ISO G2.5.

**Typical effort.** 12.2 to 23.6 hours (6 recorded).

Recorded instances:

- `INC-1035` 2025-07-17 - Compressor Lube Oil Pump 301 (SouthPlant / Unit 3), priority P2
- `INC-1064` 2025-09-17 - Crude Charge Pump 501 (EastRefinery / Unit 5), priority P2
- `INC-1065` 2025-09-17 - Boiler Feed Pump 101 (NorthPlant / Unit 1), priority P2

## High Vibration - Shaft misalignment

Occurred 6 time(s) on this asset class. Tickets: INC-1006, INC-1055, INC-1109, INC-1153, INC-1191, INC-1249.

**What was found.** Laser alignment found 0.42 mm parallel offset, well outside the 0.05 mm tolerance, caused by soft foot on the driver.

**What resolved it.** Shimmed the driver feet to remove soft foot and realigned to within 0.03 mm. Vibration returned to baseline.

**Typical effort.** 6.6 to 10.6 hours (6 recorded).

Recorded instances:

- `INC-1006` 2025-05-01 - Crude Charge Pump 501 (EastRefinery / Unit 5), priority P2
- `INC-1055` 2025-08-21 - Boiler Feed Pump 101 (NorthPlant / Unit 1), priority P2
- `INC-1109` 2025-12-18 - Circulating Water Pump 202 (NorthPlant / Unit 2), priority P2

## Seal Leak Detected - Flush plan starvation

Occurred 6 time(s) on this asset class. Tickets: INC-1030, INC-1067, INC-1095, INC-1152, INC-1207, INC-1253.

**What was found.** Inspection confirmed the alarm was genuine and traceable to the condition described above.

**What resolved it.** Corrected the condition, verified the process variable returned inside its normal operating envelope, and monitored for one full shift before closing.

**Typical effort.** 3.4 to 6.4 hours (6 recorded).

Recorded instances:

- `INC-1030` 2025-07-08 - Boiler Feed Pump 102 (NorthPlant / Unit 1), priority P2
- `INC-1067` 2025-09-19 - Boiler Feed Pump 101 (NorthPlant / Unit 1), priority P4
- `INC-1095` 2025-11-12 - Circulating Water Pump 202 (NorthPlant / Unit 2), priority P4

## High Discharge Temperature - Cooling water flow loss

Occurred 5 time(s) on this asset class. Tickets: INC-1022, INC-1131, INC-1172, INC-1185, INC-1240.

**What was found.** Cooling water isolation valve to the seal cooler had been left 60 percent closed after the previous outage.

**What resolved it.** Reopened and car-sealed the cooling water isolation valve, and added the valve to the post-outage line-up checklist.

**Typical effort.** 1.4 to 2.1 hours (5 recorded).

Recorded instances:

- `INC-1022` 2025-06-10 - Boiler Feed Pump 102 (NorthPlant / Unit 1), priority P4
- `INC-1131` 2026-01-15 - Boiler Feed Pump 101 (NorthPlant / Unit 1), priority P3
- `INC-1172` 2026-04-06 - Boiler Feed Pump 101 (NorthPlant / Unit 1), priority P3

## Low Suction Pressure - Suction strainer blockage

Occurred 5 time(s) on this asset class. Tickets: INC-1052, INC-1069, INC-1073, INC-1200, INC-1257.

**What was found.** Temporary start-up strainer had been left in place and was 70 percent blinded with weld slag.

**What resolved it.** Removed the temporary strainer, flushed the suction line and confirmed suction pressure recovered to 2.4 barg.

**Typical effort.** 4.6 to 6.2 hours (5 recorded).

Recorded instances:

- `INC-1052` 2025-08-18 - Hydrotreater Feed Pump 601 (EastRefinery / Unit 6), priority P4
- `INC-1069` 2025-09-21 - Boiler Feed Pump 102 (NorthPlant / Unit 1), priority P1
- `INC-1073` 2025-09-27 - Condensate Pump 201 (NorthPlant / Unit 2), priority P2

## Motor Overload - Process upset

Occurred 5 time(s) on this asset class. Tickets: INC-1075, INC-1111, INC-1125, INC-1196, INC-1238.

**What was found.** Inspection confirmed the alarm was genuine and traceable to the condition described above.

**What resolved it.** Corrected the condition, verified the process variable returned inside its normal operating envelope, and monitored for one full shift before closing.

**Typical effort.** 3.2 to 6.9 hours (5 recorded).

Recorded instances:

- `INC-1075` 2025-10-01 - Hydrotreater Feed Pump 601 (EastRefinery / Unit 6), priority P4
- `INC-1111` 2025-12-19 - Compressor Lube Oil Pump 301 (SouthPlant / Unit 3), priority P3
- `INC-1125` 2026-01-06 - Boiler Feed Pump 101 (NorthPlant / Unit 1), priority P3

## High Vibration - Bearing wear

Occurred 3 time(s) on this asset class. Tickets: INC-1048, INC-1132, INC-1246.

**What was found.** Vibration spectrum showed a clear bearing outer-race defect frequency with sidebands; grease sample confirmed metallic content.

**What resolved it.** Replaced both radial bearings, re-greased to the OEM schedule and re-baselined the vibration route. Overall level fell from 9.2 to 2.8 mm/s.

**Typical effort.** 8.5 to 17.9 hours (3 recorded).

Recorded instances:

- `INC-1048` 2025-08-11 - Hydrotreater Feed Pump 601 (EastRefinery / Unit 6), priority P3
- `INC-1132` 2026-01-18 - Condensate Pump 201 (NorthPlant / Unit 2), priority P3
- `INC-1246` 2026-08-01 - Hydrotreater Feed Pump 601 (EastRefinery / Unit 6), priority P4

## Low Suction Pressure - Closed or throttled suction valve

Occurred 1 time(s) on this asset class. Tickets: INC-1154.

**What was found.** Suction valve was throttled to 40 percent following a manual line-up error.

**What resolved it.** Fully opened the suction valve and car-sealed it open. Toolbox talk delivered on suction valve line-up.

**Typical effort.** 1.1 to 1.1 hours (1 recorded).
