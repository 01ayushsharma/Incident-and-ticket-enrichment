---
doc_id: TG-401
title: Troubleshooting Guide - Motor Winding Temperature High and Overload Trip
doc_type: troubleshooting_guide
revision: 3
effective_date: 2026-04-02
owner: Electrical Engineering
applies_to_asset_types: [motor]
applies_to_alarms: [Motor Winding Temperature High, Motor Overload Trip, Bearing Temperature High, Phase Imbalance]
sites: [EastRefinery]
units: [Unit 5]
tags: [motor, winding, overload, cooling, phase-imbalance, insulation]
---

# Troubleshooting Guide: Motor Winding Temperature High and Overload Trip

## Symptom

A stator winding RTD has exceeded its high alarm limit (typically 130 degC
for Class F insulation with a Class B rise), or the thermal overload relay
has tripped the motor.

## The relationship between the two alarms

These two alarms are not independent. **Motor Winding Temperature High is
the precursor; Motor Overload Trip is the consequence.** In this plant the
median lag between them is around seven minutes on Unit 5 crude unit
motors.

That lag is the window in which the trip can be prevented. Treat a winding
temperature alarm on a critical motor as an actionable event, not as
information.

## Immediate actions

1. Check the load on the driven equipment. If it can be reduced, reduce it.
2. Confirm the cooling path is clear.
3. If winding temperature continues to climb at more than 1 degC per
   minute, prepare for a trip and start the standby if one exists.

## Diagnostic sequence

### Step 1 - Cooling path

This is the first check because it is the most common cause and the
cheapest to fix.

- Inspect the motor cooling fan cowl for accumulated process dust. On the
  crude unit this fouls rapidly and has been measured reducing airflow by
  around 60 percent.
- Confirm the fan itself is intact and turning.
- Check the air inlet is not obstructed by stored materials or scaffolding.

**Typical finding:** a cowl packed with dust. Cleaning it has produced
winding temperature drops of over 20 degC.

### Step 2 - Load

- Compare motor current against nameplate. Sustained operation above
  nameplate heats the windings regardless of cooling.
- Check whether the driven equipment has changed duty: a pump running out
  on its curve because a downstream control valve was left in manual at 100
  percent will overload its motor.
- Check for mechanical binding. A rising current with no process change
  suggests the driven machine, not the motor.

### Step 3 - Supply quality

- Measure the three phase currents. Imbalance above 2 percent produces
  disproportionate heating in one winding; above 4 percent it is a
  significant contributor.
- Inspect MCC terminations. A loose termination is a frequent cause and
  will usually show on a thermographic survey of the cubicle.

### Step 4 - Ambient

- Check local ambient temperature and switchroom HVAC status. During
  heatwaves with degraded HVAC, ambient has reached 48 degC and every
  machine in the room runs hotter.
- This is a plant-wide cause: if several motors alarm together, look here
  first rather than at any individual machine.

### Step 5 - Insulation condition

A gradual upward drift in winding temperature at constant load over months,
accompanied by falling online insulation resistance, indicates insulation
ageing or moisture ingress. This is a planning signal, not an immediate
action.

## Decision guide

| Observation | Most likely cause | Action |
| --- | --- | --- |
| Cowl fouled | Cooling loss | Clean cowl, add quarterly PM |
| Current above nameplate | Sustained overload | Reduce load |
| Current rising, process unchanged | Driven equipment binding | Inspect driven machine |
| Phase imbalance above 2 percent | Loose termination or supply | Re-torque, thermograph |
| Several motors affected together | Ambient or HVAC | Restore room cooling |
| Slow drift over months | Insulation ageing | Plan condition assessment |

## After an overload trip

1. Do not reset and restart repeatedly. Each restart attempt adds heat to
   an already hot winding.
2. Allow the winding to cool to below 90 degC before restarting.
3. Establish the cause before the second start. A second trip on the same
   cause risks permanent insulation damage.

## Related documents

- TG-203 Rotating Equipment High Vibration
- AP-001 Alarm Philosophy
- ESC-010 Incident Escalation and Priority Matrix
