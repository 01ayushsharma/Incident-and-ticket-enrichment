---
doc_id: TG-301
title: Troubleshooting Guide - Compressor Surge
doc_type: troubleshooting_guide
revision: 4
effective_date: 2025-12-05
owner: Rotating Equipment Engineering
applies_to_asset_types: [compressor]
applies_to_alarms: [Surge Detected, High Discharge Pressure, Interstage Temperature High]
sites: [SouthPlant, EastRefinery]
units: [Unit 3, Unit 4, Unit 6]
tags: [compressor, surge, anti-surge, recycle, discharge-pressure]
---

# Troubleshooting Guide: Compressor Surge

## Symptom

The compressor operating point has crossed the surge line, producing a
rapid flow reversal. Surge presents as violent axial thrust reversal,
audible pulsation and a sudden drop in discharge flow.

## Why this matters

Surge is a machine-damaging event, not a process upset. Each surge cycle
loads the thrust bearing in the reverse direction. A handful of cycles can
wipe a thrust bearing; sustained surge will destroy the rotor.

Treat any confirmed surge as a **P1 incident**.

## Immediate actions

1. **Open recycle.** Increasing recycle flow moves the operating point to
   the right of the surge line. This is the only action that stops surge
   directly.
2. Reduce speed if recycle alone does not clear it.
3. If surge persists for more than a few cycles, trip the machine. A
   controlled stop is cheaper than a rotor.

## Root cause analysis

Surge means the operating point moved left. Either flow fell or discharge
resistance rose.

### Cause 1 - Anti-surge valve did not respond

The anti-surge valve is the protection of last resort and its response time
is the thing most often found deficient.

- Measure stroke time. Requirement is 2.0 seconds full travel; findings of
  4 to 5 seconds have been recorded following positioner changes where the
  volume booster was not correctly re-sized.
- Check the valve actually reaches full travel, not just that it received
  the signal.
- Verify the anti-surge controller's surge line is still correct for the
  current gas composition. A changed molecular weight moves the surge line.

**This is the most common finding.** After any work on the anti-surge
valve, stroke time must be re-measured and recorded.

### Cause 2 - Discharge restriction

A rising discharge pressure pushes the operating point left.

- Check for a downstream block valve that has drifted or been closed.
- Check the aftercooler and interstage coolers for fouling; a fouled cooler
  raises discharge pressure and interstage temperature together.
- A simultaneous High Discharge Pressure alarm preceding the surge by a few
  minutes is the classic signature of this cause.

### Cause 3 - Suction flow loss

- Check upstream vessel level control. A knockout drum that floods
  restricts suction flow.
- Check the suction strainer and any suction throttling valve.

## Correlation with other alarms

Surge rarely arrives alone. The alarm sequence carries diagnostic
information:

| Preceding alarm | Typical lag | Implies |
| --- | --- | --- |
| High Discharge Pressure | 3 to 10 minutes | Discharge restriction or cooler fouling |
| Interstage Temperature High | 5 to 20 minutes | Intercooler fouling |
| Lube Oil Pressure Low | any | Machine protection issue; stop, do not diagnose surge first |

When reviewing a surge event, always pull the alarm list for the 30 minutes
preceding it. The precursor alarm usually identifies the cause faster than
inspecting the machine.

## After a surge event

1. Check thrust bearing temperature and axial position against the
   pre-event baseline.
2. Take a vibration spectrum and look for sub-synchronous content.
3. Review the anti-surge valve stroke record.
4. Do not return to service without establishing why the protection did not
   prevent the event.

## Related documents

- TG-302 Compressor Lube Oil System Low Pressure
- TG-203 Rotating Equipment High Vibration
- MNT-030 Heat Exchanger and Cooler Fouling Maintenance Guide
- ESC-010 Incident Escalation and Priority Matrix
