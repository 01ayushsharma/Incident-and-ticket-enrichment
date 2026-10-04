---
doc_id: TG-202
title: Troubleshooting Guide - Pump Low Suction Pressure and Cavitation
doc_type: troubleshooting_guide
revision: 5
effective_date: 2025-11-20
owner: Rotating Equipment Engineering
applies_to_asset_types: [pump]
applies_to_alarms: [Low Suction Pressure]
sites: [NorthPlant, SouthPlant, EastRefinery]
tags: [pump, suction, npsh, cavitation, strainer, level]
---

# Troubleshooting Guide: Pump Low Suction Pressure and Cavitation

## Symptom

Suction pressure has fallen below the configured low alarm limit. On
feedwater service this is typically 1.8 barg with a trip at 1.2 barg.

## Why this matters

Low suction pressure reduces NPSH available. When NPSH available falls
below NPSH required, the fluid flashes at the impeller eye and collapses
against the vane surfaces. The resulting damage accumulates over **minutes**
and is not recoverable. This alarm is never a nuisance alarm on a
centrifugal pump.

Audible cavitation is often described as gravel passing through the casing.
If an operator reports that sound, treat the condition as confirmed
regardless of the transmitter reading.

## Immediate actions

1. **Reduce flow demand.** NPSH required rises with flow, so throttling
   back widens the margin immediately. This buys time; it is not a fix.
2. **Do not increase speed or flow** while investigating.
3. If suction pressure continues to fall toward the trip point, transfer to
   the standby machine and stop the affected pump.

## Diagnostic sequence

### Step 1 - Upstream level

Check the level in the suction vessel (deaerator, knockout drum, surge
drum).

- A falling level with normal control action suggests a loss of make-up.
- A cycling level suggests a badly tuned level controller periodically
  starving the pump. This is a common and easily missed cause: the alarm
  appears intermittent and correlates with controller cycles rather than
  with plant rate.

### Step 2 - Suction valve position

Verify the suction valve is fully open **locally**. Do not rely on DCS
indication or on the assumption that it has not been touched.

Line-up errors after maintenance are one of the two most frequent root
causes on this alarm. A valve throttled to 40 percent will pass enough flow
to look normal at low rate and starve the pump at high rate.

### Step 3 - Suction strainer

Check strainer differential pressure. Above roughly 0.5 bar the strainer is
restricting flow materially.

Pay particular attention after any commissioning or turnaround work:
temporary start-up strainers are routinely left in place and blind rapidly
with weld slag and debris. This has caused repeat events across several
units.

### Step 4 - Fluid temperature

If the fluid has become hotter, its vapour pressure has risen and NPSH
available has fallen even though suction pressure is unchanged. Check
suction temperature against the design case.

### Step 5 - Instrument integrity

Cross-check the suction pressure transmitter against a local gauge. An
impulse line that has drained or plugged will read low.

## Decision guide

| Observation | Most likely cause | Action |
| --- | --- | --- |
| Upstream level low or cycling | Level control problem | Retune or restore make-up |
| Valve found throttled locally | Line-up error | Open and car-seal |
| Strainer dP above 0.5 bar | Strainer blockage | Clean or remove temporary strainer |
| Suction temperature elevated | Reduced NPSH margin | Cool the fluid or reduce flow |
| Local gauge reads normal | Transmitter or impulse line fault | Recalibrate |

## Damage assessment after a cavitation event

If the pump ran in cavitation for more than a few minutes, do not simply
return it to service:

1. Trend vibration before and after the event. A step increase indicates
   impeller damage.
2. Check for a drop in developed head at the same flow.
3. Plan a borescope or strip inspection at the next opportunity.

## Escalation

- Sustained operation below the low alarm limit for more than 10 minutes
  warrants a P2 incident even if the pump is subsequently recovered.
- Repeat events on the same machine within 90 days indicate an unresolved
  systemic cause; escalate to engineering rather than repeating the field
  fix.

## Related documents

- OP-114 Boiler Feedwater Pump Operating Procedure
- TG-201 Pump High Discharge Temperature Troubleshooting
- ESC-010 Incident Escalation and Priority Matrix
