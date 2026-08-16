"""
analyze_performance must never treat 0 ms in-progress laps as real data.

The capture loop inserts a lap at 0 ms when it starts; only update_lap_time()
fills in the real time on completion.  If capture stops mid-lap, a 0 ms row
remains — MIN(lap_time_ms) over such rows used to report a 0.000 s "fastest
lap".  These tests pin the SQL filters that keep 0 ms rows out of the
fastest-lap / average / consistency computations.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from analyze_performance import get_session_summary, get_tyre_degradation, get_lap_consistency


class AnalyzePerformanceQueryTests(unittest.TestCase):

    def _query_captor(self, rows):
        """Patch pd.read_sql, recording the SQL it was given."""
        captured = {}

        def fake_read_sql(query, conn, params=None):
            captured['query'] = query
            captured['params'] = params
            return rows

        return patch('analyze_performance.pd.read_sql',
                     side_effect=fake_read_sql), captured

    def test_session_summary_excludes_zero_ms_laps(self):
        df = pd.DataFrame([{
            'session_id': 1, 'track_name': 'Spa', 'date': None,
            'total_laps': 1, 'fastest_lap': None, 'avg_lap_time': None,
            'valid_laps': 0, 'invalid_laps': 1,
        }])
        patcher, captured = self._query_captor(df)
        with patcher:
            get_session_summary(MagicMock())
        self.assertIn('lap_time_ms > 0', captured['query'])
        # Both MIN and AVG must be guarded, not just the fastest lap
        # (the query also has 2 CASE WHENs for the is_valid lap counts)
        self.assertEqual(captured['query'].count('CASE WHEN l.lap_time_ms > 0'), 2)

    def test_tyre_degradation_excludes_zero_ms_laps(self):
        df = pd.DataFrame(
            columns=['lap_number', 'lap_time', 'tyre_compound',
                     'tyre_age', 'is_valid', 'has_pit_stop'])
        patcher, captured = self._query_captor(df)
        with patcher:
            get_tyre_degradation(MagicMock(), 1)
        self.assertIn('lap_time_ms > 0', captured['query'])
        self.assertIn('duration_sec IS NULL OR se.duration_sec >= 15',
                      captured['query'],
                      "spurious pit events must not split stints, but "
                      "unknown-duration real pits must")
        self.assertEqual(captured['params'], (1,))

    def test_tyre_degradation_aggregates_detrended_deltas(self):
        # One stint, pure fuel trend (no wear): times fall 0.5 s/lap.
        rows = pd.DataFrame([
            {'lap_number': n, 'lap_time': 92.0 - 0.5 * (n - 1),
             'tyre_compound': 'Medium', 'tyre_age': n + 2,
             'is_valid': 1, 'has_pit_stop': 0}
            for n in range(1, 5)
        ])
        patcher, _ = self._query_captor(rows)
        with patcher:
            df = get_tyre_degradation(MagicMock(), 1)
        self.assertEqual(list(df.columns),
                         ['tyre_compound', 'tyre_age', 'avg_delta', 'num_laps'])
        # Fuel trend must NOT show up as degradation: avg_delta ~ 0.
        self.assertLess(df['avg_delta'].abs().max(), 1e-6)
        self.assertEqual(df['num_laps'].sum(), 4)

    def test_lap_consistency_excludes_zero_ms_laps(self):
        df = pd.DataFrame(
            columns=['lap_number', 'lap_time', 'tyre_compound', 'tyre_age', 'is_valid'])
        patcher, captured = self._query_captor(df)
        with patcher:
            get_lap_consistency(MagicMock(), 1)
        self.assertIn('lap_time_ms > 0', captured['query'])
        self.assertEqual(captured['params'], (1,))


if __name__ == "__main__":
    unittest.main()
