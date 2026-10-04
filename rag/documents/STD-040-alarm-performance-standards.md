---
doc_id: STD-040
title: Alarm Performance Standards and KPI Definitions
doc_type: engineering_standard
revision: 5
effective_date: 2026-01-01
owner: Process Control Engineering
applies_to_asset_types: [pump, compressor, motor, valve, boiler, heat_exchanger, fan, vessel, dryer]
sites: [NorthPlant, SouthPlant, EastRefinery]
tags: [kpi, eemua-191, metrics, flood-index, nuisance, response-efficiency]
---

# Alarm Performance Standards and KPI Definitions

## 1. Purpose

Defines the metrics used to assess alarm system performance, how each is
calculated, and the thresholds that trigger intervention. These definitions
are the authority for any reported figure; a number quoted without
reference to the definition here is not comparable.

## 2. Core metrics

### 2.1 Alarm count

Total alarm occurrences in scope and period. The denominator for most other
metrics. Counts occurrences, not distinct alarm types.

### 2.2 Recurring rate

    (total occurrences - distinct asset+alarm pairs) / total occurrences

The share of occurrences that repeat something already seen. A rate above
0.7 means the console is dominated by a small number of repeating alarms
and rationalization will have high leverage.

### 2.3 Average acknowledgement delay

Mean interval from alarm onset to operator acknowledgement, over
acknowledged alarms only. Unacknowledged alarms are excluded rather than
counted as infinite, so this metric must always be read alongside the
standing alarm count.

Target: below 600 seconds. Above 900 seconds indicates either operator
overload or alarms the operator has learned to ignore.

### 2.4 Operator response efficiency

    count(acknowledged within 600s) / count(acknowledged)

Expressed as a ratio. Target above 0.85. This metric is sensitive to alarm
flooding: efficiency collapses during floods because the operator is
queueing, not ignoring.

### 2.5 Alarm flood index

    alarms occurring inside flood conditions / total alarms

Flood conditions are defined in AP-001 as more than 10 alarms in a
10-minute rolling window. EEMUA 191 recommends below 0.01. Above 0.05
indicates the alarm system is materially failing during upsets, which is
precisely when it is needed.

### 2.6 Critical alarm density

    critical alarms / (assets in scope x days in period)

Normalises critical alarm load by plant size and period so that units of
different size can be compared. A rising density on a stable plant
indicates either genuine degradation or severity inflation during
configuration changes.

### 2.7 Nuisance alarm score

    (0.4 x suppressed + 0.4 x chattering + 0.2 x repeats) / total alarms

A composite of the three nuisance signatures, where chattering means a
duration below 300 seconds. Ranges 0 to 1. Above 0.3 indicates a console
where a substantial fraction of alarms carry no actionable information.

### 2.8 Suppression candidate rate

    count(suppressed or duration below 300s) / total alarms

The share of alarms that are already suppressed or behave as chattering.
Used to size a rationalization programme before it starts.

### 2.9 Mean time to resolve

Mean of (clear time minus onset) over cleared alarms. Distinct from
acknowledgement delay: acknowledgement measures attention, resolution
measures effectiveness.

## 3. Reporting periods

| Metric | Period | Audience |
| --- | --- | --- |
| Alarm count, rate | Daily | Shift supervisor |
| Response efficiency, ack delay | Weekly | Operations manager |
| Flood index, nuisance score | Monthly | Process Control Engineering |
| Critical density, recurring rate | Quarterly | Site leadership |

## 4. Interpreting a metric against a benchmark

Two cautions apply to every figure above.

**Scope matters more than the number.** A flood index computed across a
whole site averages away a single badly performing console. Always compute
per console or per unit before drawing a conclusion.

**Period matters.** A 90-day window smooths out a bad week. When
investigating a specific degradation, compute over the period in question
and compare against the equivalent earlier period, not against the annual
average.

## Related documents

- AP-001 Alarm Philosophy
- ESC-010 Incident Escalation and Priority Matrix
