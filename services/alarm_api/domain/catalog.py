"""Static plant catalog: the assets and the alarm templates that apply to them.

Kept separate from :mod:`alarm_api.domain.seed` so that the *shape* of the
plant is reviewable as data, while the generator stays pure logic. The named
assets here are load-bearing - the Postman chaining collection searches for
"Boiler Feed Pump 101", "Boiler Feed Pump 102", "compressor" and "motor"
(the latter scoped to Unit 5) and asserts a non-empty result each time.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from alarm_api.schemas import AlarmType, Criticality


@dataclass(frozen=True)
class AssetSpec:
    name: str
    asset_type: str
    site: str
    unit: str
    criticality: Criticality
    manufacturer: str
    model_number: str


@dataclass(frozen=True)
class AlarmTemplate:
    """A kind of alarm that a class of asset can raise."""

    name: str
    alarm_type: AlarmType
    # Relative weights over (low, medium, high, critical).
    severity_weights: tuple[int, int, int, int]
    unit_of_measure: str | None
    limit_value: float | None
    # Typical overshoot as a fraction of the limit, used to synthesise a value.
    overshoot: float = 0.12
    description: str = ""
    # Mean hours between occurrences on a given asset. Lower = chattier.
    mean_interval_hours: float = 96.0
    causes: tuple[str, ...] = field(default_factory=tuple)


SITES: dict[str, list[str]] = {
    "NorthPlant": ["Unit 1", "Unit 2"],
    "SouthPlant": ["Unit 3", "Unit 4"],
    "EastRefinery": ["Unit 5", "Unit 6"],
}


ASSET_SPECS: tuple[AssetSpec, ...] = (
    # ---- NorthPlant / Unit 1 - boiler feedwater train ---------------------
    AssetSpec(
        "Boiler Feed Pump 101",
        "pump",
        "NorthPlant",
        "Unit 1",
        Criticality.CRITICAL,
        "Sulzer",
        "HPT-4200",
    ),
    AssetSpec(
        "Boiler Feed Pump 102",
        "pump",
        "NorthPlant",
        "Unit 1",
        Criticality.HIGH,
        "Sulzer",
        "HPT-4200",
    ),
    AssetSpec(
        "Boiler Drum 101",
        "boiler",
        "NorthPlant",
        "Unit 1",
        Criticality.CRITICAL,
        "Babcock",
        "BD-900",
    ),
    AssetSpec(
        "Deaerator Level Valve 101",
        "valve",
        "NorthPlant",
        "Unit 1",
        Criticality.MEDIUM,
        "Fisher",
        "ED-6in",
    ),
    AssetSpec(
        "Feedwater Heat Exchanger 101",
        "heat_exchanger",
        "NorthPlant",
        "Unit 1",
        Criticality.MEDIUM,
        "Alfa Laval",
        "M15-BFG",
    ),
    # ---- NorthPlant / Unit 2 - cooling water ------------------------------
    AssetSpec(
        "Condensate Pump 201",
        "pump",
        "NorthPlant",
        "Unit 2",
        Criticality.HIGH,
        "Grundfos",
        "NK-200",
    ),
    AssetSpec(
        "Circulating Water Pump 202",
        "pump",
        "NorthPlant",
        "Unit 2",
        Criticality.HIGH,
        "Grundfos",
        "NK-300",
    ),
    AssetSpec(
        "Cooling Tower Fan 201",
        "fan",
        "NorthPlant",
        "Unit 2",
        Criticality.MEDIUM,
        "Howden",
        "CTF-28",
    ),
    AssetSpec(
        "Cooling Tower Fan 202",
        "fan",
        "NorthPlant",
        "Unit 2",
        Criticality.MEDIUM,
        "Howden",
        "CTF-28",
    ),
    AssetSpec(
        "Makeup Water Valve 201",
        "valve",
        "NorthPlant",
        "Unit 2",
        Criticality.LOW,
        "Fisher",
        "ED-4in",
    ),
    # ---- SouthPlant / Unit 3 - instrument air -----------------------------
    AssetSpec(
        "Reciprocating Compressor 301",
        "compressor",
        "SouthPlant",
        "Unit 3",
        Criticality.CRITICAL,
        "Ariel",
        "JGK-4",
    ),
    AssetSpec(
        "Reciprocating Compressor 302",
        "compressor",
        "SouthPlant",
        "Unit 3",
        Criticality.HIGH,
        "Ariel",
        "JGK-4",
    ),
    AssetSpec(
        "Compressor Lube Oil Pump 301",
        "pump",
        "SouthPlant",
        "Unit 3",
        Criticality.HIGH,
        "Viking",
        "LO-75",
    ),
    AssetSpec(
        "Air Dryer Skid 301",
        "dryer",
        "SouthPlant",
        "Unit 3",
        Criticality.MEDIUM,
        "Atlas Copco",
        "BD-1200",
    ),
    # ---- SouthPlant / Unit 4 - process gas --------------------------------
    AssetSpec(
        "Centrifugal Compressor 401",
        "compressor",
        "SouthPlant",
        "Unit 4",
        Criticality.CRITICAL,
        "Elliott",
        "38M9",
    ),
    AssetSpec(
        "Process Gas Cooler 401",
        "heat_exchanger",
        "SouthPlant",
        "Unit 4",
        Criticality.MEDIUM,
        "Alfa Laval",
        "M30-FG",
    ),
    AssetSpec(
        "Knockout Drum 401",
        "vessel",
        "SouthPlant",
        "Unit 4",
        Criticality.MEDIUM,
        "Chart",
        "KD-1500",
    ),
    AssetSpec(
        "Flare Header Valve 401",
        "valve",
        "SouthPlant",
        "Unit 4",
        Criticality.HIGH,
        "Emerson",
        "FH-12in",
    ),
    # ---- EastRefinery / Unit 5 - crude unit rotating equipment ------------
    AssetSpec(
        "Crude Charge Motor 501",
        "motor",
        "EastRefinery",
        "Unit 5",
        Criticality.CRITICAL,
        "ABB",
        "M3BP-450",
    ),
    AssetSpec(
        "Reflux Pump Motor 502",
        "motor",
        "EastRefinery",
        "Unit 5",
        Criticality.HIGH,
        "ABB",
        "M3BP-315",
    ),
    AssetSpec(
        "Vacuum Tower Motor 503",
        "motor",
        "EastRefinery",
        "Unit 5",
        Criticality.HIGH,
        "Siemens",
        "1LE1-355",
    ),
    AssetSpec(
        "Induced Draft Fan Motor 504",
        "motor",
        "EastRefinery",
        "Unit 5",
        Criticality.MEDIUM,
        "Siemens",
        "1LE1-280",
    ),
    AssetSpec(
        "Crude Charge Pump 501",
        "pump",
        "EastRefinery",
        "Unit 5",
        Criticality.CRITICAL,
        "Flowserve",
        "HPX-8",
    ),
    # ---- EastRefinery / Unit 6 - hydrotreater -----------------------------
    AssetSpec(
        "Hydrotreater Feed Pump 601",
        "pump",
        "EastRefinery",
        "Unit 6",
        Criticality.CRITICAL,
        "Flowserve",
        "HPX-6",
    ),
    AssetSpec(
        "Recycle Gas Compressor 601",
        "compressor",
        "EastRefinery",
        "Unit 6",
        Criticality.CRITICAL,
        "Elliott",
        "29M7",
    ),
    AssetSpec(
        "Reactor Effluent Exchanger 601",
        "heat_exchanger",
        "EastRefinery",
        "Unit 6",
        Criticality.HIGH,
        "Koch",
        "REX-2200",
    ),
    AssetSpec(
        "Stripper Reboiler 601",
        "boiler",
        "EastRefinery",
        "Unit 6",
        Criticality.HIGH,
        "Babcock",
        "SR-450",
    ),
    AssetSpec(
        "Safety Shutdown Valve 601",
        "valve",
        "EastRefinery",
        "Unit 6",
        Criticality.CRITICAL,
        "Emerson",
        "SSV-10in",
    ),
)


_PUMP = (
    AlarmTemplate(
        "High Discharge Temperature",
        AlarmType.PROCESS,
        (3, 6, 3, 1),
        "degC",
        95.0,
        0.14,
        "Pump discharge temperature above the configured high limit.",
        mean_interval_hours=70.0,
        causes=(
            "Degraded mechanical seal",
            "Recirculation line fouling",
            "Cooling water flow loss",
        ),
    ),
    AlarmTemplate(
        "Low Suction Pressure",
        AlarmType.PROCESS,
        (3, 6, 3, 1),
        "barg",
        1.8,
        -0.22,
        "Suction pressure below the low limit; cavitation risk.",
        mean_interval_hours=88.0,
        causes=(
            "Suction strainer blockage",
            "Upstream level drop",
            "Closed or throttled suction valve",
        ),
    ),
    AlarmTemplate(
        "High Vibration",
        AlarmType.DEVICE,
        (2, 6, 4, 1),
        "mm/s",
        7.1,
        0.28,
        "Overall vibration above ISO 10816 zone C threshold.",
        mean_interval_hours=110.0,
        causes=("Bearing wear", "Shaft misalignment", "Impeller imbalance"),
    ),
    AlarmTemplate(
        "Seal Leak Detected",
        AlarmType.DEVICE,
        (3, 5, 2, 1),
        None,
        None,
        0.0,
        "Mechanical seal leak detection switch tripped.",
        mean_interval_hours=210.0,
        causes=("Seal face wear", "Flush plan starvation"),
    ),
    AlarmTemplate(
        "Motor Overload",
        AlarmType.DEVICE,
        (2, 5, 3, 1),
        "A",
        210.0,
        0.15,
        "Driver current above the overload setpoint.",
        mean_interval_hours=180.0,
        causes=("Process upset", "Mechanical binding"),
    ),
)

_COMPRESSOR = (
    AlarmTemplate(
        "Surge Detected",
        AlarmType.PROCESS,
        (1, 3, 4, 3),
        "kg/h",
        18500.0,
        -0.19,
        "Compressor operating point crossed the surge line.",
        mean_interval_hours=96.0,
        causes=("Anti-surge valve slow response", "Discharge restriction", "Suction flow loss"),
    ),
    AlarmTemplate(
        "High Discharge Pressure",
        AlarmType.PROCESS,
        (2, 5, 3, 1),
        "barg",
        42.0,
        0.11,
        "Discharge pressure above the high limit.",
        mean_interval_hours=84.0,
        causes=("Downstream valve closure", "Cooler fouling"),
    ),
    AlarmTemplate(
        "Lube Oil Pressure Low",
        AlarmType.SAFETY,
        (1, 2, 4, 4),
        "barg",
        1.4,
        -0.26,
        "Lube oil header pressure below the trip-adjacent low limit.",
        mean_interval_hours=150.0,
        causes=("Lube oil pump degradation", "Filter differential high", "Oil level low"),
    ),
    AlarmTemplate(
        "High Vibration",
        AlarmType.DEVICE,
        (2, 5, 4, 1),
        "mm/s",
        6.4,
        0.3,
        "Radial vibration above alarm threshold.",
        mean_interval_hours=120.0,
        causes=("Rotor imbalance", "Bearing degradation", "Coupling wear"),
    ),
    AlarmTemplate(
        "Interstage Temperature High",
        AlarmType.PROCESS,
        (3, 5, 2, 1),
        "degC",
        135.0,
        0.13,
        "Interstage gas temperature above the high limit.",
        mean_interval_hours=100.0,
        causes=("Intercooler fouling", "Valve leakage"),
    ),
)

_MOTOR = (
    AlarmTemplate(
        "Motor Winding Temperature High",
        AlarmType.DEVICE,
        (2, 5, 4, 1),
        "degC",
        130.0,
        0.12,
        "Stator winding RTD above the high limit.",
        mean_interval_hours=64.0,
        causes=("Cooling fan fouling", "Sustained overload", "Ambient temperature excursion"),
    ),
    AlarmTemplate(
        "Motor Overload Trip",
        AlarmType.SAFETY,
        (0, 2, 4, 4),
        "A",
        480.0,
        0.18,
        "Thermal overload relay tripped the motor.",
        mean_interval_hours=190.0,
        causes=(
            "Driven equipment binding",
            "Phase imbalance",
            "Sustained winding temperature excursion",
        ),
    ),
    AlarmTemplate(
        "Bearing Temperature High",
        AlarmType.DEVICE,
        (2, 6, 3, 1),
        "degC",
        90.0,
        0.15,
        "Motor bearing temperature above the high limit.",
        mean_interval_hours=105.0,
        causes=("Lubrication degradation", "Bearing wear", "Misalignment"),
    ),
    AlarmTemplate(
        "Phase Imbalance",
        AlarmType.DEVICE,
        (4, 5, 2, 0),
        "%",
        3.0,
        0.4,
        "Supply phase current imbalance above threshold.",
        mean_interval_hours=240.0,
        causes=("Supply quality", "Loose termination"),
    ),
    AlarmTemplate(
        "Insulation Resistance Low",
        AlarmType.DIAGNOSTIC,
        (4, 4, 2, 0),
        "MOhm",
        5.0,
        -0.3,
        "Online insulation resistance below the advisory limit.",
        mean_interval_hours=300.0,
        causes=("Moisture ingress", "Winding insulation ageing"),
    ),
)

_VALVE = (
    AlarmTemplate(
        "Valve Position Deviation",
        AlarmType.DEVICE,
        (5, 4, 2, 0),
        "%",
        5.0,
        0.6,
        "Valve position deviates from the commanded setpoint.",
        mean_interval_hours=72.0,
        causes=("Actuator air supply", "Positioner calibration drift", "Stem friction"),
    ),
    AlarmTemplate(
        "Valve Stuck",
        AlarmType.DEVICE,
        (1, 4, 4, 2),
        None,
        None,
        0.0,
        "Valve failed to reach the commanded position within the travel time.",
        mean_interval_hours=260.0,
        causes=("Stem galling", "Loss of instrument air"),
    ),
    AlarmTemplate(
        "Instrument Air Pressure Low",
        AlarmType.SAFETY,
        (1, 3, 4, 3),
        "barg",
        5.5,
        -0.2,
        "Instrument air supply below the low limit.",
        mean_interval_hours=170.0,
        causes=("Air compressor trip", "Header leak"),
    ),
)

_BOILER = (
    AlarmTemplate(
        "Drum Level Low",
        AlarmType.SAFETY,
        (0, 2, 4, 5),
        "mm",
        -150.0,
        -0.25,
        "Steam drum level below the low-low approach.",
        mean_interval_hours=130.0,
        causes=("Feedwater flow loss", "Level transmitter drift", "Feed pump trip"),
    ),
    AlarmTemplate(
        "Drum Level High",
        AlarmType.PROCESS,
        (2, 5, 3, 1),
        "mm",
        150.0,
        0.22,
        "Steam drum level above the high limit.",
        mean_interval_hours=140.0,
        causes=("Feed control valve overshoot", "Swell on load change"),
    ),
    AlarmTemplate(
        "Flame Failure",
        AlarmType.SAFETY,
        (0, 0, 2, 8),
        None,
        None,
        0.0,
        "Burner flame scanner lost flame signal.",
        mean_interval_hours=420.0,
        causes=("Fuel gas pressure excursion", "Scanner fouling"),
    ),
    AlarmTemplate(
        "Tube Metal Temperature High",
        AlarmType.PROCESS,
        (2, 4, 3, 1),
        "degC",
        520.0,
        0.09,
        "Superheater tube metal temperature above the high limit.",
        mean_interval_hours=160.0,
        causes=("Localised fouling", "Steam flow maldistribution"),
    ),
)

_HEAT_EXCHANGER = (
    AlarmTemplate(
        "High Differential Pressure",
        AlarmType.PROCESS,
        (3, 5, 2, 0),
        "bar",
        2.2,
        0.25,
        "Shell-side differential pressure above the fouling limit.",
        mean_interval_hours=190.0,
        causes=("Tube-side fouling", "Partial blockage"),
    ),
    AlarmTemplate(
        "Outlet Temperature High",
        AlarmType.PROCESS,
        (3, 5, 2, 0),
        "degC",
        78.0,
        0.14,
        "Process outlet temperature above the high limit.",
        mean_interval_hours=150.0,
        causes=("Cooling medium flow loss", "Fouling"),
    ),
    AlarmTemplate(
        "Tube Leak Suspected",
        AlarmType.DIAGNOSTIC,
        (2, 4, 3, 1),
        None,
        None,
        0.0,
        "Conductivity shift consistent with a tube leak.",
        mean_interval_hours=520.0,
        causes=("Tube corrosion", "Thermal cycling fatigue"),
    ),
)

_FAN = (
    AlarmTemplate(
        "High Vibration",
        AlarmType.DEVICE,
        (3, 5, 2, 0),
        "mm/s",
        9.0,
        0.24,
        "Fan vibration above the alarm threshold.",
        mean_interval_hours=80.0,
        causes=("Blade fouling", "Bearing wear", "Imbalance from debris"),
    ),
    AlarmTemplate(
        "Motor Overload",
        AlarmType.DEVICE,
        (3, 5, 2, 0),
        "A",
        96.0,
        0.16,
        "Fan motor current above the overload setpoint.",
        mean_interval_hours=150.0,
        causes=("Damper malposition", "Bearing drag"),
    ),
    AlarmTemplate(
        "Gearbox Oil Temperature High",
        AlarmType.DEVICE,
        (3, 5, 2, 0),
        "degC",
        85.0,
        0.13,
        "Gearbox oil temperature above the high limit.",
        mean_interval_hours=170.0,
        causes=("Oil degradation", "Cooler fouling"),
    ),
)

_VESSEL = (
    AlarmTemplate(
        "High Level",
        AlarmType.PROCESS,
        (3, 5, 2, 0),
        "%",
        85.0,
        0.1,
        "Vessel level above the high limit.",
        mean_interval_hours=90.0,
        causes=("Drain valve restriction", "Upstream carryover"),
    ),
    AlarmTemplate(
        "High High Level Trip",
        AlarmType.SAFETY,
        (0, 1, 3, 6),
        "%",
        95.0,
        0.05,
        "Vessel level reached the trip setpoint.",
        mean_interval_hours=380.0,
        causes=("Level control failure", "Sustained carryover"),
    ),
)

_DRYER = (
    AlarmTemplate(
        "Dewpoint High",
        AlarmType.PROCESS,
        (4, 4, 2, 0),
        "degC",
        -40.0,
        0.3,
        "Outlet dewpoint above the specification limit.",
        mean_interval_hours=120.0,
        causes=("Desiccant saturation", "Regeneration cycle fault"),
    ),
    AlarmTemplate(
        "Regeneration Cycle Fault",
        AlarmType.SYSTEM,
        (4, 4, 2, 0),
        None,
        None,
        0.0,
        "Dryer failed to complete a regeneration cycle.",
        mean_interval_hours=200.0,
        causes=("Switching valve fault", "Heater element failure"),
    ),
)

TEMPLATES_BY_TYPE: dict[str, tuple[AlarmTemplate, ...]] = {
    "pump": _PUMP,
    "compressor": _COMPRESSOR,
    "motor": _MOTOR,
    "valve": _VALVE,
    "boiler": _BOILER,
    "heat_exchanger": _HEAT_EXCHANGER,
    "fan": _FAN,
    "vessel": _VESSEL,
    "dryer": _DRYER,
}

# Ordered pairs that the correlation endpoint should be able to surface:
# (leading alarm name, trailing alarm name, typical lag in minutes). The seed
# generator injects these on top of the random background so that correlation
# returns something meaningful rather than noise.
CAUSAL_PAIRS: tuple[tuple[str, str, int], ...] = (
    ("Motor Winding Temperature High", "Motor Overload Trip", 7),
    ("Lube Oil Pressure Low", "High Vibration", 4),
    ("High Discharge Pressure", "Surge Detected", 6),
    ("Low Suction Pressure", "High Discharge Temperature", 9),
    ("Instrument Air Pressure Low", "Valve Position Deviation", 3),
    ("Drum Level Low", "High Discharge Temperature", 11),
)
