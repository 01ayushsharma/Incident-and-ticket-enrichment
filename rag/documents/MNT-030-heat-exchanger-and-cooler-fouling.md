---
doc_id: MNT-030
title: Maintenance Guide - Heat Exchanger and Cooler Fouling
doc_type: maintenance_guide
revision: 4
effective_date: 2026-03-18
owner: Static Equipment Engineering
applies_to_asset_types: [heat_exchanger, compressor, pump]
applies_to_alarms: [High Differential Pressure, Outlet Temperature High, Interstage Temperature High, Tube Leak Suspected]
sites: [NorthPlant, SouthPlant, EastRefinery]
tags: [fouling, heat-exchanger, cooler, cleaning, differential-pressure, condition-based]
---

# Maintenance Guide: Heat Exchanger and Cooler Fouling

## 1. Scope

Covers condition assessment and cleaning intervention for shell-and-tube
exchangers, plate exchangers, compressor intercoolers and aftercoolers, and
pump seal coolers.

## 2. Recognising fouling

Fouling is progressive, so the diagnostic signal is the **trend**, not the
absolute value. Two indicators move together:

1. **Rising differential pressure** on the fouled side, as the flow path
   restricts.
2. **Widening approach temperature**, the gap between the process outlet
   and the cooling medium inlet, as heat transfer degrades.

A rise in one without the other usually points elsewhere:

| Observation | Indicates |
| --- | --- |
| dP rising, approach stable | Partial blockage or debris, not general fouling |
| Approach widening, dP stable | Loss of cooling medium flow, not fouling |
| Both rising steadily over weeks | Genuine fouling |
| Both step-changed | Valve position or flow diversion, check line-up first |

## 3. Condition-based intervention thresholds

| Service | Clean dP | Intervention dP | Clean approach | Intervention approach |
| --- | --- | --- | --- | --- |
| Shell-and-tube process cooler | 0.4 bar | 2.2 bar | 8 degC | 20 degC |
| Compressor intercooler | 0.3 bar | 1.5 bar | 10 degC | 22 degC |
| Pump seal cooler | 0.2 bar | 0.8 bar | 6 degC | 15 degC |
| Plate exchanger | 0.5 bar | 2.5 bar | 5 degC | 14 degC |

Clean values must be recorded after every cleaning. Without a current clean
baseline these thresholds cannot be applied, and this is the most common
reason condition-based intervention fails in practice.

## 4. Knock-on effects

Fouling rarely announces itself directly; it usually presents as an alarm
on connected rotating equipment.

- **Compressor intercooler fouling** raises interstage temperature and
  discharge pressure, which moves the operating point toward the surge
  line. A compressor that has begun surging at rates it previously handled
  should have its coolers checked before the anti-surge system is blamed.
- **Pump seal cooler fouling** raises pump discharge temperature and
  accelerates seal degradation. Where a pump repeatedly raises High
  Discharge Temperature and the seal has already been replaced once, check
  the cooler rather than replacing the seal again.
- **Process gas cooler fouling** raises downstream temperatures across the
  train and can present as several unrelated-looking alarms at once.

## 5. Cleaning methods

| Deposit | Method | Typical duration |
| --- | --- | --- |
| Soft scale, biological | Chemical circulation clean | 8 to 12 hours |
| Hard scale | Hydroblasting, tube side | 12 to 18 hours |
| Coke or polymer | Mechanical, tube bundle removal | 2 to 4 days |
| Plate exchanger, any | Strip, soak, inspect gaskets | 1 to 2 days |

## 6. After cleaning

1. Record the new clean dP and clean approach temperature. This becomes the
   baseline for the next cycle.
2. Confirm no tube leaks by pressure testing before returning to service.
3. Update the fouling rate estimate from the interval since last clean.
4. Where the fouling interval has shortened by more than 30 percent,
   investigate the cause rather than simply scheduling more frequent
   cleaning: it usually indicates a change in water treatment, process
   composition or flow velocity.

## 7. Tube leak suspicion

A conductivity shift on the cooling water side, or contamination detected
in the process stream, suggests a tube leak.

Do not continue to operate a suspected leaking exchanger on hydrocarbon
service. Isolate, confirm by pressure test, and plug or replace the
affected tubes.

## Related documents

- TG-201 Pump High Discharge Temperature Troubleshooting
- TG-301 Compressor Surge Troubleshooting
- ESC-010 Incident Escalation and Priority Matrix
