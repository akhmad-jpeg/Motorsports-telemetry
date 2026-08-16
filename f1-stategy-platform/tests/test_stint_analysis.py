"""stint_analysis must produce fuel-adjusted degradation deltas.

The core contract: within one stint, lap times fall as fuel burns, which
masks tyre wear.  detrend_laps removes each stint's own linear trend, so
the fuel slope disappears while genuine non-linear wear (a cliff at high
age) survives as positive deltas.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from stint_analysis import detrend_laps, segment_stints


def lap(num, time, compound='Medium', age=None, valid=True, pit=0):
    return {
        'lap_number': num,
        'lap_time': time,
        'tyre_compound': compound,
        'tyre_age': age,
        'is_valid': 1 if valid else 0,
        'has_pit_stop': pit,
    }


class StintSegmentationTests(unittest.TestCase):

    def test_compound_change_starts_new_stint(self):
        laps = [
            lap(1, 90.0, 'Soft', 1),
            lap(2, 89.0, 'Soft', 2),
            lap(3, 88.0, 'Medium', 1),   # compound change -> new stint
            lap(4, 87.0, 'Medium', 2),
        ]
        stints = segment_stints(laps)
        self.assertEqual(len(stints), 2)
        self.assertEqual(stints[0]['compound'], 'Soft')
        self.assertEqual(stints[1]['compound'], 'Medium')
        self.assertEqual([l['lap_number'] for l in stints[1]['laps']], [3, 4])

    def test_pit_stop_starts_new_stint_on_next_lap(self):
        laps = [
            lap(1, 90.0, 'Soft', 1),
            lap(2, 88.0, 'Soft', 2),
            lap(3, 110.0, 'Soft', 3, pit=1),   # in-lap
            lap(4, 91.0, 'Soft', 1),            # out-lap -> new stint
            lap(5, 89.0, 'Soft', 2),
        ]
        stints = segment_stints(laps)
        self.assertEqual(len(stints), 2)
        self.assertEqual(stints[0]['laps'][-1]['lap_number'], 3)
        self.assertEqual(stints[1]['laps'][0]['lap_number'], 4)

    def test_age_reset_starts_new_stint(self):
        laps = [
            lap(1, 90.0, 'Soft', 5),
            lap(2, 89.0, 'Soft', 6),
            lap(3, 88.0, 'Soft', 1),   # age dropped -> new stint
        ]
        stints = segment_stints(laps)
        self.assertEqual(len(stints), 2)


class FuelAdjustmentTests(unittest.TestCase):

    def test_fuel_trend_is_removed(self):
        # A clean fuel trend: times fall 0.5 s/lap, no wear at all.
        laps = [
            lap(n, 90.0 - 0.5 * (n - 1), age=n)
            for n in range(3, 8)   # ages 3..7 (warm-up laps excluded from fit)
        ]
        out = detrend_laps(laps)
        deltas = [l['stint_delta'] for l in out]
        # The raw times span 2.0 s; the deltas must be ~0 (fit is exact).
        self.assertLess(max(abs(d) for d in deltas), 1e-6)

    def test_tyre_cliff_survives_detrending(self):
        # Fuel trend (-0.5 s/lap) PLUS a cliff after age 20 (+0.3 s/lap).
        laps = []
        for n in range(3, 26):
            time = 90.0 - 0.5 * (n - 1)
            if n > 20:
                time += 0.3 * (n - 20)
            laps.append(lap(n, time, age=n))
        out = detrend_laps(laps)
        by_age = {l['tyre_age']: l['stint_delta'] for l in out}
        # The single fitted line is a compromise across the bend, so early
        # laps sit near zero while cliff laps are clearly more positive.
        self.assertLess(by_age[5], 0.5)
        self.assertGreater(by_age[25], by_age[5] + 0.5)

    def test_cold_tyre_spike_is_visible_not_absorbed(self):
        # Warm-up lap at age 1 is slow; steady fuel trend afterwards.
        laps = [lap(1, 93.0, age=1), lap(2, 90.0, age=2)]
        laps += [lap(n, 89.5 - 0.5 * (n - 3), age=n) for n in range(3, 10)]
        out = detrend_laps(laps)
        by_age = {l['tyre_age']: l['stint_delta'] for l in out}
        self.assertGreater(by_age[1], 1.0)          # spike survives
        self.assertLess(abs(by_age[6]), 1e-6)       # steady state ~0


class PitLapExclusionTests(unittest.TestCase):

    def test_in_lap_and_out_lap_have_no_delta(self):
        laps = [
            lap(1, 90.0, age=1), lap(2, 88.0, age=2), lap(3, 86.0, age=3),
            lap(4, 105.0, age=4, pit=1),            # in-lap
            lap(5, 89.0, age=1),                    # out-lap (new stint)
            lap(6, 86.5, age=2), lap(7, 86.0, age=3),
        ]
        out = detrend_laps(laps)
        by_num = {l['lap_number']: l for l in out}
        self.assertIsNone(by_num[4]['stint_delta'])   # in-lap
        self.assertIsNone(by_num[5]['stint_delta'])   # out-lap
        self.assertIsNotNone(by_num[3]['stint_delta'])
        self.assertIsNotNone(by_num[6]['stint_delta'])

    def test_short_stint_falls_back_to_median_delta(self):
        # Two-lap stint: no trend fit possible, deltas split around median.
        laps = [lap(1, 90.0, age=5), lap(2, 92.0, age=6)]
        out = detrend_laps(laps)
        deltas = sorted(l['stint_delta'] for l in out)
        self.assertAlmostEqual(deltas[0], -1.0)
        self.assertAlmostEqual(deltas[1], 1.0)

    def test_single_lap_stint_has_no_delta(self):
        out = detrend_laps([lap(1, 90.0, age=3)])
        self.assertIsNone(out[0]['stint_delta'])

    def test_invalid_laps_do_not_shape_the_fit(self):
        # A wild invalid lap must not pull the fitted trend.
        laps = [
            lap(1, 90.0, age=3), lap(2, 89.5, age=4),
            lap(3, 89.0, age=5), lap(4, 88.5, age=6),
            lap(5, 120.0, age=7, valid=False),
        ]
        out = detrend_laps(laps)
        # Fit on laps 1-4 (collinear, slope -0.5) -> the invalid lap's
        # delta is huge while the valid trend laps sit exactly on zero.
        by_num = {l['lap_number']: l for l in out}
        self.assertGreater(by_num[5]['stint_delta'], 20.0)
        self.assertLess(abs(by_num[4]['stint_delta']), 1e-6)


if __name__ == "__main__":
    unittest.main()
