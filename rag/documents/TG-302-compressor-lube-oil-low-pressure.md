---
doc_id: TG-302
title: Troubleshooting Guide - Compressor Lube Oil Pressure Low
doc_type: troubleshooting_guide
revision: 3
effective_date: 2025-10-12
owner: Rotating Equipment Engineering
applies_to_asset_types: [compressor, pump]
applies_to_alarms: [Lube Oil Pressure Low, High Vibration, Bearing Temperature High]
sites: [SouthPlant, EastRefinery]
tags: [lube-oil, compressor, bearing, filter, standby-pump, trip]
---

# Troubleshooting Guide: Compressor Lube Oil Pressure Low

## Symptom

Lube oil header pressure has fallen below the low alarm limit, typically
1.4 barg with a trip at 1.0 barg.

## Why this matters

This is a **protection alarm, not a process alarm**. Below the trip
setpoint the hydrodynamic oil film collapses and the bearings contact the
journal. Damage begins in seconds and a wiped thrust bearing means a rotor
removal.

The correct instinct here is the opposite of most alarms: protect the
machine first, diagnose second.

## Immediate actions

1. **Confirm the standby lube oil pump has auto-started.** If it has not,
   start it manually. This is the single most important action.
2. **Check reservoir level.** A low reservoir explains everything else and
   is visible immediately.
3. If pressure continues to fall toward the trip setpoint with the standby
   running, **stop the machine in a controlled manner** rather than waiting
   for the trip.

Do not spend time confirming the transmitter before doing the above. A
false alarm costs a few minutes; a genuine one that was diagnosed instead
of acted on costs a rotor.

## Diagnostic sequence

### Step 1 - Filter differential pressure

The most common cause of a gradual pressure decay. Changeover limit is
typically 1.0 bar differential; findings of 1.8 bar have been recorded
where a planned filter change had been deferred more than once.

Perform an online filter changeover. Check the PM history: a deferred
filter task is a systemic finding, not a one-off.

### Step 2 - Reservoir level and oil condition

- Level below the sight glass minimum: look for a drain line weep or an
  external leak before topping up, or it will simply recur.
- Oil degraded, dark or with high water content: pressure falls as
  viscosity changes. Sample and test.

### Step 3 - Lube oil pump condition

If the filter is clean and the level is correct, the pump itself has lost
capacity. Internal clearances open with wear and header pressure falls at
rated speed. Confirm by comparing pump discharge pressure against its
performance curve at the current speed.

### Step 4 - Transmitter integrity

Only once the machine is protected, cross-check the header pressure
transmitter against the local gauge. An impulse line that has plugged will
read low and has caused unnecessary shutdowns.

## The vibration connection

Lube oil pressure low and high vibration are causally linked with a short
lag. Where lube oil pressure has dipped, expect a vibration rise within a
few minutes as the oil film thins. The observed median lag in this plant is
around four minutes.

Practical consequence: a vibration alarm arriving shortly after a lube oil
alarm is **not a second independent problem**. Do not investigate it
separately. Restore lube oil and the vibration will usually follow.

Conversely, a vibration rise with no preceding lube oil event points to a
mechanical cause and should be worked under TG-203.

## After a low lube oil event

1. Check thrust and radial bearing temperatures against the pre-event
   baseline.
2. Take a vibration spectrum and look for the sub-synchronous content that
   indicates oil whirl or bearing damage.
3. Sample the oil for metallic content.
4. Do not return to service until the standby pump auto-start has been
   function-tested.

## Related documents

- TG-301 Compressor Surge Troubleshooting
- TG-203 Rotating Equipment High Vibration
- ESC-010 Incident Escalation and Priority Matrix
