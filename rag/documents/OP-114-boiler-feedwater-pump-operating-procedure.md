---
doc_id: OP-114
title: Boiler Feedwater Pump Operating Procedure
doc_type: operating_procedure
revision: 4
effective_date: 2026-03-01
owner: Rotating Equipment Engineering
applies_to_asset_types: [pump]
applies_to_assets: [Boiler Feed Pump 101, Boiler Feed Pump 102]
applies_to_alarms: [High Discharge Temperature, Low Suction Pressure, High Vibration, Seal Leak Detected]
sites: [NorthPlant]
units: [Unit 1]
tags: [boiler, feedwater, pump, startup, shutdown, npsh, minimum-flow]
---

# Boiler Feedwater Pump Operating Procedure

## 1. Scope

This procedure covers normal operation, start-up, shutdown and abnormal
condition response for the boiler feedwater pumps in NorthPlant Unit 1
(Boiler Feed Pump 101 and Boiler Feed Pump 102). Both machines are Sulzer
HPT-4200 multistage centrifugal pumps supplying Boiler Drum 101.

Boiler Feed Pump 101 is the duty machine and is classified **critical**.
Boiler Feed Pump 102 is the installed standby. Loss of both machines
requires an immediate controlled boiler shutdown under SAF-020.

## 2. Normal operating envelope

| Parameter | Normal | Alarm limit | Trip |
| --- | --- | --- | --- |
| Suction pressure | 2.2 to 3.4 barg | Low at 1.8 barg | 1.2 barg |
| Discharge temperature | 62 to 78 degC | High at 95 degC | 110 degC |
| Overall vibration | below 4.5 mm/s | High at 7.1 mm/s | 11.0 mm/s |
| Motor current | 140 to 185 A | High at 210 A | 240 A |
| Minimum continuous stable flow | 145 m3/h | — | — |

Operating below minimum continuous stable flow is the single most common
cause of accelerated wear on these machines. The recirculation valve must
open automatically below 160 m3/h; confirm it has done so whenever plant
rate drops below 40 percent.

## 3. Start-up

1. Confirm the suction valve is fully open and car-sealed. A throttled
   suction valve is a recurring cause of low suction pressure alarms on
   these pumps; it must be verified visually, not from the DCS indication
   alone.
2. Confirm deaerator level is above 55 percent, giving adequate NPSH
   available.
3. Confirm the suction strainer differential pressure is below 0.3 bar.
4. Establish seal flush flow and confirm the API Plan 11 flush orifice is
   passing. Loss of flush is the dominant cause of seal degradation.
5. Open the minimum-flow recirculation valve before starting.
6. Start the motor and confirm discharge pressure develops within 15
   seconds. If it does not, stop immediately and investigate for loss of
   prime.
7. Ramp to duty flow and confirm the recirculation valve closes as flow
   exceeds 160 m3/h.

**Never start a feedwater pump against a closed discharge with the
recirculation valve also closed.** Deadheading these machines raises
discharge temperature above 110 degC within roughly 90 seconds.

## 4. Abnormal condition response

### 4.1 Low suction pressure

Low suction pressure indicates the pump is at risk of cavitation, which
causes rapid and irreversible impeller damage.

1. Reduce flow demand immediately to lower NPSH required.
2. Check deaerator level and level control valve position.
3. Check suction strainer differential pressure.
4. Verify the suction valve position locally.
5. If suction pressure continues to fall below 1.4 barg, transfer to the
   standby pump and stop the affected machine.

Do not attempt to run through a sustained low suction pressure condition.
Cavitation damage accumulates in minutes, not hours.

### 4.2 High discharge temperature

Rising discharge temperature with stable flow usually indicates either loss
of cooling to the seal cooler or operation below minimum flow.

1. Confirm the minimum-flow recirculation line is open and passing.
2. Confirm cooling water flow and temperature to the seal cooler. The
   cooling water isolation valve has been found partially closed after
   outages on more than one occasion; verify its position locally.
3. Check seal flush flow.
4. If temperature exceeds 105 degC, transfer to the standby pump.

### 4.3 High vibration

1. Take a spectrum reading and compare with the last route measurement.
2. Trend bearing temperature alongside vibration. A joint rise indicates
   bearing degradation rather than a process excitation.
3. Check coupling alignment and foundation bolt torque if the rise is
   gradual over days.
4. If overall vibration exceeds 9 mm/s, plan a transfer to standby within
   the shift. Above 11 mm/s the machine trips.

### 4.4 Seal leak detected

1. Confirm the leak visually at the seal drain.
2. Assess rate. A weep is tolerable to the end of shift; a stream is not.
3. Confirm flush plan operation before assuming seal failure.
4. Transfer to standby and raise a work order for seal replacement.

## 5. Transfer to standby

1. Confirm Boiler Feed Pump 102 is available and its suction valve is open.
2. Start the standby pump and confirm it develops discharge pressure.
3. Confirm drum level control remains stable through the transfer.
4. Stop the duty pump only after the standby is carrying flow.
5. Leave the stopped machine's suction valve open and cooling water in
   service unless maintenance requires isolation.

## 6. Recurring degradation

Where the same alarm recurs on one machine more than five times in 90 days,
raise an engineering review rather than repeatedly acknowledging it. A
recurring high discharge temperature or low suction pressure pattern on a
critical feedwater pump is a leading indicator of seal or impeller
degradation and should be treated as a condition-based maintenance trigger
under MNT-030.

## 7. Related documents

- SAF-020 Boiler Drum Level Safety Instruction
- TG-201 Pump High Discharge Temperature Troubleshooting
- TG-202 Pump Low Suction Pressure and Cavitation
- TG-203 Rotating Equipment High Vibration
- AP-001 Alarm Philosophy
