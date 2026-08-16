import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from fuel_estimation import estimate_fuel_load


class FuelEstimationTests(unittest.TestCase):
    def test_expected_lap_values(self):
        self.assertEqual(estimate_fuel_load(0), 110.0)
        self.assertEqual(estimate_fuel_load(1), 108.0)
        self.assertEqual(estimate_fuel_load(55), 0.0)
        self.assertEqual(estimate_fuel_load(80), 0.0)

    def test_rejects_invalid_lap_numbers(self):
        with self.assertRaises(ValueError):
            estimate_fuel_load(-1)
        with self.assertRaises(ValueError):
            estimate_fuel_load(1.5)


if __name__ == "__main__":
    unittest.main()
