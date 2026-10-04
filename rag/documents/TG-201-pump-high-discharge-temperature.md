---
doc_id: TG-201
title: Troubleshooting Guide - Pump High Discharge Temperature
doc_type: troubleshooting_guide
revision: 7
effective_date: 2026-01-15
owner: Rotating Equipment Engineering
applies_to_asset_types: [pump]
applies_to_alarms: [High Discharge Temperature]
sites: [NorthPlant, SouthPlant, EastRefinery]
tags: [pump, temperature, seal, cooling-water, minimum-flow, recirculation]
---

# Troubleshooting Guide: Pump High Discharge Temperature

## Symptom

Pump discharge temperature has risen above the configured high alarm limit
(typically 95 degC on feedwater service, 85 degC on hydrocarbon service)
while the pump remains running.

## Why this matters

Discharge temperature is a proxy for energy that is going into the fluid
rather than into head. A sustained rise means the pump is doing work it is
not delivering, which almost always ends in seal failure, bearing damage or
vapour lock. On critical service it is a leading indicator, not a nuisance.

## Immediate actions

1. **Confirm the reading.** Compare against the local gauge or a second
   indication before intervening. A failed RTD presents identically to a
   genuine excursion.
2. **Check flow against minimum continuous stable flow.** If the pump is
   below minimum flow, the recirculation line should have opened. Verify it
   has.
3. **Do not deadhead.** If discharge is restricted, open a flow path before
   doing anything else.

## Diagnostic sequence

### Step 1 - Is the pump below minimum flow?

Compare current flow against the machine's minimum continuous stable flow
from its datasheet. Below that point, most of the absorbed power becomes
heat.

- Recirculation valve commanded open but flow not increasing: suspect a
  fouled or blocked recirculation orifice.
- Recirculation valve not commanded open: check the flow transmitter and
  the valve's auto logic.

**Typical finding:** a fouled minimum-flow orifice holding the pump below
minimum flow at low plant rates. Isolate and clean the orifice.

### Step 2 - Is cooling available?

Check cooling water flow and supply temperature to the seal cooler or
jacket.

- Cooling water isolation valves are frequently found throttled or closed
  after an outage. Verify position **locally**, not from the DCS.
- Check the cooler for fouling if flow is present but the approach
  temperature has widened.

**Typical finding:** a cooling water isolation valve left partially closed
following maintenance. Reopen, car-seal, and add the valve to the
post-outage line-up checklist.

### Step 3 - Is the seal degraded?

A degraded mechanical seal generates local heat and will show as a
discharge temperature rise before it shows as a visible leak.

- Check seal flush flow and the flush plan orifice.
- Inspect the seal drain for evidence of weeping.
- Check whether seal face temperature, where instrumented, is rising faster
  than discharge temperature.

**Typical finding:** circumferential scoring on the seal faces combined
with a partially blocked API Plan 11 flush orifice. Replace the cartridge
seal and restore flush flow.

### Step 4 - Is the process itself hotter?

Rule out a genuine upstream temperature rise before attributing the alarm
to the machine. Check suction temperature; if suction has risen by a
similar amount, the pump is not the cause.

## Decision guide

| Observation | Most likely cause | Action |
| --- | --- | --- |
| Low flow, recirc commanded open, no flow increase | Fouled recirculation orifice | Clean orifice |
| Normal flow, cooling water flow zero or low | Cooling isolation valve closed | Restore cooling |
| Normal flow and cooling, seal drain weeping | Seal degradation | Replace seal |
| Suction temperature risen equally | Upstream process change | No pump action |
| Step change with no process change | Instrument fault | Verify transmitter |

## Escalation

- Above 105 degC on critical service, transfer to standby and stop the
  machine.
- If the same asset raises this alarm more than five times in 90 days,
  escalate to an engineering review under AP-001 section 6 rather than
  continuing to acknowledge it.

## Typical resolution times

| Cause | Typical time to resolve |
| --- | --- |
| Cooling water valve position | 1 to 2 hours |
| Recirculation orifice cleaning | 4 to 6 hours |
| Mechanical seal replacement | 6 to 12 hours |

## Related documents

- OP-114 Boiler Feedwater Pump Operating Procedure
- TG-202 Pump Low Suction Pressure and Cavitation
- MNT-030 Heat Exchanger and Cooler Fouling Maintenance Guide
- AP-001 Alarm Philosophy
