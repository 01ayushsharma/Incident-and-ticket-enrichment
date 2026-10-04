---
doc_id: TG-203
title: Troubleshooting Guide - Rotating Equipment High Vibration
doc_type: troubleshooting_guide
revision: 6
effective_date: 2026-02-10
owner: Reliability Engineering
applies_to_asset_types: [pump, compressor, fan, motor]
applies_to_alarms: [High Vibration, Bearing Temperature High]
sites: [NorthPlant, SouthPlant, EastRefinery]
tags: [vibration, bearing, alignment, imbalance, iso-10816, spectrum]
---

# Troubleshooting Guide: Rotating Equipment High Vibration

## Symptom

Overall vibration has exceeded the alarm threshold. Thresholds follow
ISO 10816 zone boundaries and vary by machine class; typical alarm values
in this plant are 7.1 mm/s for feedwater pumps, 6.4 mm/s for compressors
and 9.0 mm/s for cooling tower fans.

## The key diagnostic principle

An overall vibration number tells you *that* something changed. Only the
spectrum tells you *what* changed. Do not plan intervention on the overall
number alone; take a spectrum and compare it against the last route
measurement.

## Frequency signatures

| Dominant frequency | Indicates | Confirming evidence |
| --- | --- | --- |
| 1x running speed | Imbalance | Radial, steady phase, rises with speed squared |
| 2x running speed | Misalignment | Strong axial component, phase shift across coupling |
| Bearing defect frequencies with sidebands | Bearing wear | Rising bearing temperature, metallic content in grease |
| Vane pass frequency | Hydraulic excitation or impeller damage | Correlates with flow, not speed |
| Broadband, no clear peak | Cavitation or looseness | Check suction conditions and foundation bolts |
| Sub-synchronous | Oil whirl or rotor instability | Compressors and high-speed machines; escalate immediately |

## Diagnostic sequence

### Step 1 - Establish the rate of change

Pull the trend over the last 30 days.

- **Step change:** suspect an event. Something was hit, a coupling moved, a
  bolt loosened, or debris entered the machine.
- **Gradual rise over weeks:** suspect degradation. Bearings, alignment
  drift, or progressive fouling.
- **Correlates with process rate:** suspect a hydraulic or aerodynamic
  cause rather than a mechanical one.

### Step 2 - Trend bearing temperature alongside vibration

A joint rise in vibration and bearing temperature is the clearest
indication of bearing degradation and justifies planning a replacement. A
vibration rise with flat bearing temperature points away from bearings and
toward imbalance, misalignment or a process excitation.

### Step 3 - Check the easy mechanical causes

Before planning an overhaul, rule out the inexpensive findings:

1. **Foundation bolt torque.** Loose hold-down bolts produce looseness
   signatures and are a ten-minute check.
2. **Soft foot.** A machine that does not sit flat will not stay aligned.
   Check with feeler gauges or by loosening each foot in turn.
3. **Coupling condition.** Worn elastomeric elements produce 1x and 2x
   components.
4. **Debris on fan blades or impellers.** On cooling tower fans this is the
   single most common cause of an imbalance signature.

### Step 4 - Alignment

If the signature points at misalignment, take a laser alignment reading.
Plant tolerance is 0.05 mm parallel offset. Findings of 0.3 mm and above
have been recorded on machines that had drifted following foundation
settlement or soft foot.

## Chattering vibration alarms

Repeated short-lived vibration alarms that clear within a few minutes are
usually a threshold problem rather than a machine problem. Cooling tower
fans are particularly prone to this because wind loading produces transient
excursions.

Where an alarm recurs more than five times in 90 days with a median
duration below five minutes, it is a **chattering alarm** and should be
handled under the rationalization process in AP-001 by applying an on-delay
or deadband, not by continued acknowledgement.

## Escalation thresholds

| Overall vibration | Action |
| --- | --- |
| Alarm limit to 1.3x alarm | Monitor, take spectrum, plan inspection |
| 1.3x to trip minus 15 percent | Plan transfer to standby within the shift |
| Above that | Transfer now; do not run to trip |
| Sub-synchronous on a compressor | Stop and escalate immediately |

## Related documents

- OP-114 Boiler Feedwater Pump Operating Procedure
- TG-302 Compressor Lube Oil System Low Pressure
- AP-001 Alarm Philosophy
- ESC-010 Incident Escalation and Priority Matrix
