---
doc_id: SAF-020
title: Safety Instruction - Boiler Drum Level
doc_type: safety_instruction
revision: 11
effective_date: 2026-05-01
owner: Process Safety
applies_to_asset_types: [boiler, pump]
applies_to_assets: [Boiler Drum 101, Boiler Feed Pump 101, Boiler Feed Pump 102, Stripper Reboiler 601]
applies_to_alarms: [Drum Level Low, Drum Level High, Flame Failure, Tube Metal Temperature High]
sites: [NorthPlant, EastRefinery]
tags: [safety, boiler, drum-level, sil, trip, dry-out]
---

# Safety Instruction: Boiler Drum Level

## Status of this document

This is a **safety instruction**, not guidance. The actions specified here
are mandatory. Where this document conflicts with an operating procedure or
with a recommendation from any advisory system, this document governs.

## 1. The hazard

Loss of drum level uncovers the generating tubes. Uncovered tubes overheat
within minutes, and the failure mode is tube rupture with release of
saturated steam into the furnace. This has the potential for fatality.

The hazard is time-critical. At full firing rate with total loss of
feedwater, the interval between the low alarm and tube dry-out is
approximately **four minutes**.

## 2. Protection layers

| Layer | Setpoint | Action |
| --- | --- | --- |
| Low alarm | -150 mm | Operator action |
| Low-low trip (SIL 2) | -250 mm | Automatic fuel trip |
| High alarm | +150 mm | Operator action |
| High-high trip (SIL 2) | +250 mm | Automatic fuel trip |

The low-low and high-high trips are Safety Instrumented Functions. They
must not be bypassed, inhibited or suppressed under any circumstances
without a formal override permit authorised by the Process Safety engineer.

## 3. Mandatory response to Drum Level Low

Execute in this order. Do not pause to diagnose before step 3.

1. **Confirm the level** against a second transmitter and the gauge glass.
   Three-element control means a single failed transmitter can drive the
   level down while indicating normally.
2. **Confirm feedwater flow.** Check the duty feedwater pump is running and
   developing pressure.
3. **If level is still falling, reduce firing rate.** This extends the time
   available and reduces the heat flux on the tubes. Do this before
   completing any further diagnosis.
4. **Start the standby feedwater pump** if the duty pump has tripped or is
   not developing pressure.
5. **If level reaches -220 mm and is still falling, trip the boiler
   manually.** Do not wait for the automatic trip.

Never restore feedwater rapidly to a drum that has been uncovered. Thermal
shock on hot tubes can cause immediate failure. Restore level gradually
under the supervision of the shift supervisor.

## 4. Mandatory response to Drum Level High

1. Confirm the level against a second indication.
2. Reduce feedwater flow.
3. Check for a control valve passing or stuck open.
4. Carryover of water into the superheater damages the turbine. If level
   exceeds +220 mm, trip the boiler manually.

## 5. Interaction with feedwater pump alarms

A Drum Level Low alarm that follows a feedwater pump alarm is not an
independent event. The typical sequence observed in this plant is:

> Feed pump High Discharge Temperature or Low Suction Pressure
> then feed pump trip or manual transfer
> then Drum Level Low within 10 to 15 minutes

Any feedwater pump alarm on a boiler in service must therefore be treated
as a precursor to a drum level event, and the standby pump's availability
must be confirmed immediately, not at the point the level alarm arrives.

## 6. Prohibited actions

- Do not suppress a drum level alarm.
- Do not place drum level control in manual without the shift supervisor's
  authorisation.
- Do not silence a Flame Failure alarm and restart without a full furnace
  purge.
- Do not defer investigation of a recurring drum level alarm on the grounds
  that the trip will catch it. The trip is a protection layer, not an
  operating control.

## 7. Reporting

Every drum level excursion beyond alarm limits is reportable as a minimum
P2 incident under ESC-010, regardless of whether the level recovered.
Excursions reaching the trip setpoint are P1 and require Process Safety
notification the same day.

## Related documents

- OP-114 Boiler Feedwater Pump Operating Procedure
- ESC-010 Incident Escalation and Priority Matrix
- AP-001 Alarm Philosophy
