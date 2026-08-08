"""Shared synthetic fuel-load feature for F1 2018 Legacy telemetry.

The Legacy UDP packet format does not provide fuel mass.  Every component must
therefore derive the same estimated value instead of treating it as telemetry.
"""

STARTING_FUEL_KG = 110.0
FUEL_BURN_PER_LAP_KG = 2.0


def estimate_fuel_load(lap_number: int) -> float:
    """Return estimated fuel mass for a zero-based-or-later lap number.

    Lap 0 represents the start-of-session estimate (110 kg). Lap 1 is 108 kg.
    Values are clamped at zero because the estimate must never become negative.
    """
    if isinstance(lap_number, bool) or int(lap_number) != lap_number:
        raise ValueError("lap_number must be a whole number")

    lap_number = int(lap_number)
    if lap_number < 0:
        raise ValueError("lap_number must be non-negative")

    return max(0.0, STARTING_FUEL_KG - (lap_number * FUEL_BURN_PER_LAP_KG))
