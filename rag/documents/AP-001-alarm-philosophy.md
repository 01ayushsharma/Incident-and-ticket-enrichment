---
doc_id: AP-001
title: Alarm Philosophy
doc_type: alarm_philosophy
revision: 9
effective_date: 2026-01-01
owner: Process Control Engineering
applies_to_asset_types: [pump, compressor, motor, valve, boiler, heat_exchanger, fan, vessel, dryer]
sites: [NorthPlant, SouthPlant, EastRefinery]
tags: [alarm-philosophy, severity, rationalization, flood, eemua-191, suppression]
---

# Alarm Philosophy

## 1. Purpose

This document defines what an alarm is for, how severity is assigned, and
the criteria under which an alarm is reviewed or removed. It governs alarm
configuration across all three sites and is the reference for any
rationalization activity.

## 2. What an alarm is

An alarm is a request for operator action. If there is no action an
operator can usefully take, the condition is not an alarm; it is an event,
a status, or a maintenance notification.

Three tests every alarm must pass:

1. **Actionable.** There is a defined operator response.
2. **Timely.** There is enough time to act before consequence.
3. **Unique.** It is not a duplicate of another alarm covering the same
   condition.

An alarm that fails any of these is a candidate for removal.

## 3. Severity assignment

Severity reflects the consequence of not responding, combined with the time
available.

| Severity | Consequence if unaddressed | Response expectation |
| --- | --- | --- |
| Critical | Safety, environmental or major equipment loss | Immediate; interrupt other work |
| High | Significant production loss or equipment damage | Within 10 minutes |
| Medium | Efficiency loss or progressive degradation | Within the shift |
| Low | Advisory; condition worth knowing | Before end of shift |

Severity is a property of the condition, not of the asset. A critical asset
does not automatically raise critical alarms. Asset criticality is applied
separately when prioritising incidents; see ESC-010.

## 4. Alarm performance targets

Targets follow EEMUA 191 and are assessed per operator console.

| Metric | Target | Intervention threshold |
| --- | --- | --- |
| Average alarm rate | Below 6 per hour | Above 12 per hour |
| Peak alarm rate | Below 60 per hour | Above 120 per hour |
| Alarms in flood conditions | Below 1 percent of total | Above 5 percent |
| Standing alarms at shift handover | Below 10 | Above 30 |
| Distribution (low/medium/high/critical) | 80 / 15 / 4 / 1 | Materially heavier than target |

## 5. Alarm floods

A flood exists when more than **10 alarms occur within a 10-minute rolling
window** on one console. In a flood the operator cannot process alarms as
fast as they arrive, so effectively none of them is being actioned.

Flood analysis is performed monthly. Each flood window is reviewed for its
dominant alarm; a single alarm contributing more than 30 percent of a flood
is an automatic rationalization candidate.

## 6. Rationalization criteria

An alarm becomes a rationalization candidate when any of the following
holds.

### 6.1 Recurring

More than **five occurrences of the same alarm on the same asset within 90
days**. Recurrence indicates either an unresolved underlying condition or a
setpoint that does not reflect normal operation.

Action: raise an engineering review. Do not continue to acknowledge a
recurring alarm indefinitely — repeated acknowledgement without resolution
is the failure mode this criterion exists to catch.

### 6.2 Chattering

Recurring, with a **median duration below five minutes**. The condition is
crossing and re-crossing the threshold rather than persisting.

Action: apply an on-delay or a deadband. Chattering alarms are a
configuration defect, not an equipment defect, and should be corrected
rather than investigated as process events.

### 6.3 Stale

An alarm that has remained **active for more than three hours** without
being cleared. A standing alarm carries no information: it is part of the
background and will be ignored when it matters.

Action: either resolve the underlying condition or reassess the setpoint.
Suppression is acceptable only with documented justification and an expiry
date.

### 6.4 Consequential

An alarm that reliably follows another alarm and adds no new information.
Where alarm B follows alarm A within a short lag with high confidence, B is
a candidate for suppression while A is active.

## 7. Suppression

Suppression is permitted only where:

1. The justification is documented against a specific rationalization
   candidate.
2. An expiry date is set, not exceeding 90 days.
3. The suppression is visible to the operator.

Blanket or indefinite suppression is not permitted under any circumstances.

## 8. Review cycle

- Monthly: alarm rate, flood analysis, standing alarm count.
- Quarterly: rationalization candidate list and closure of prior actions.
- Annually: full philosophy review and severity distribution audit.

## Related documents

- STD-040 Alarm Performance Standards and KPI Definitions
- ESC-010 Incident Escalation and Priority Matrix
- TG-203 Rotating Equipment High Vibration
