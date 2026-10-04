---
doc_id: ESC-010
title: Incident Escalation and Priority Matrix
doc_type: escalation_procedure
revision: 8
effective_date: 2026-02-01
owner: Operations Support
applies_to_asset_types: [pump, compressor, motor, valve, boiler, heat_exchanger, fan, vessel, dryer]
sites: [NorthPlant, SouthPlant, EastRefinery]
tags: [escalation, priority, incident, ticket, sla, on-call]
---

# Incident Escalation and Priority Matrix

## 1. Purpose

Defines how an alarm becomes an incident ticket, how that ticket is
prioritised, and who is engaged at each level.

## 2. When to raise an incident

Raise an incident ticket when any of the following is true:

- A critical or high severity alarm has not cleared within its response
  expectation.
- An alarm has recurred more than five times on one asset within 90 days
  (see AP-001 section 6.1).
- Equipment has been transferred to standby because of an abnormal
  condition.
- A safety function has actuated.
- A condition requires work that cannot be completed by the operating team.

Do **not** raise an incident for a single low or medium alarm that cleared
normally. That creates ticket noise and buries the incidents that matter.

## 3. Priority matrix

Priority combines alarm severity with asset criticality. Severity describes
the condition; criticality describes what depends on the equipment.

| | Low criticality | Medium criticality | High criticality | Critical asset |
| --- | --- | --- | --- | --- |
| **Critical alarm** | P2 | P2 | P1 | P1 |
| **High alarm** | P3 | P2 | P2 | P1 |
| **Medium alarm** | P4 | P3 | P3 | P2 |
| **Low alarm** | P4 | P4 | P3 | P3 |

### Modifiers

Raise the priority by one band if any apply:

- The alarm is part of a safety function.
- There is no available standby for the affected asset.
- The condition has recurred more than five times in 90 days.
- The alarm occurred inside an alarm flood window.

Lower by one band if:

- The asset is already isolated for maintenance.
- A compensating measure is documented and in place.

## 4. Response and resolution targets

| Priority | Acknowledge | Engage | Target resolution |
| --- | --- | --- | --- |
| P1 | 15 minutes | Immediately, including out of hours | 8 hours |
| P2 | 1 hour | Same shift | 24 hours |
| P3 | 4 hours | Next working day | 5 working days |
| P4 | 1 working day | Next planned window | 30 days |

## 5. Escalation path

1. **Control room operator** — first response, containment, transfer to
   standby.
2. **Shift supervisor** — engaged for all P1 and P2 within the
   acknowledgement window.
3. **Discipline engineer** (rotating, electrical, process control as
   appropriate) — engaged for P1 immediately, P2 same shift.
4. **Operations manager** — engaged for any P1 not resolved within 4 hours,
   and for any safety function actuation.
5. **Plant manager** — engaged for any P1 not resolved within 8 hours, or
   where production loss exceeds the site threshold.

Out of hours, engage via the on-call rota. P1 justifies a call-out; P2 does
not unless the shift supervisor judges the condition to be deteriorating.

## 6. What an incident ticket must contain

A ticket raised from an alarm is only useful if it carries enough context
for the next person. It must include:

1. **The alarm** — id, name, asset, severity, timestamp.
2. **The asset** — name, tag, criticality, site and unit.
3. **Why it matters** — the consequence of not acting.
4. **What has already been done** — containment actions taken by the
   operating team.
5. **Evidence** — measured value against limit, recurrence count over 90
   days, and any correlated alarms.
6. **Recommended actions** — with the procedure reference they came from.
7. **Similar past incidents** — ticket references and their root causes.

A ticket that says only "High vibration on pump" restarts the
investigation from zero and wastes the responder's first hour.

## 7. Linking correlated assets

Where alarm correlation shows other assets involved in the same event,
check for existing open tickets against those assets before raising a new
one. Two tickets describing one event fragment the investigation.

If a related open ticket exists, link to it rather than duplicating.

## 8. Approval for ticket creation

Automated systems, including the incident copilot, may **draft** an
incident but must not create one without explicit human confirmation. The
confirming person is accountable for the content of the ticket, so the
draft must be presented in full and be editable before approval.

## Related documents

- AP-001 Alarm Philosophy
- SAF-020 Boiler Drum Level Safety Instruction
- STD-040 Alarm Performance Standards and KPI Definitions
