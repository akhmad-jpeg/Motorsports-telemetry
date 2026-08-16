import sys
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from dashboard import app


class DashboardApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.client.testing = True

    def test_index_route(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)

    @patch('dashboard.get_db_connection')
    def test_get_sessions_api(self, mock_db):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            {'session_id': 1, 'track_name': 'Spa', 'session_type': 'Race', 'weather': 'Clear', 'date': None, 'total_laps': 10, 'fastest_lap': 81.2}
        ]

        response = self.client.get('/api/sessions')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['track_name'], 'Spa')

    @patch('dashboard.get_db_connection')
    def test_get_sessions_pagination_params(self, mock_db):
        """The sessions endpoint takes limit/offset and clamps limit to 500."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []

        response = self.client.get('/api/sessions?limit=10&offset=5')
        self.assertEqual(response.status_code, 200)
        sql, params = mock_cursor.execute.call_args[0]
        self.assertIn('LIMIT %s OFFSET %s', sql)
        self.assertEqual(params, (10, 5))

        # Clamped: a huge limit becomes 500, not an unbounded query.
        mock_cursor.execute.reset_mock()
        response = self.client.get('/api/sessions?limit=9999')
        self.assertEqual(response.status_code, 200)
        _, params = mock_cursor.execute.call_args[0]
        self.assertEqual(params[0], 500)

    @patch('dashboard.get_db_connection')
    def test_get_sessions_default_limit(self, mock_db):
        """No params keeps the historical 50-row default."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []

        response = self.client.get('/api/sessions')
        self.assertEqual(response.status_code, 200)
        _, params = mock_cursor.execute.call_args[0]
        self.assertEqual(params, (50, 0))

    def test_predict_options_when_no_model(self):
        with patch('dashboard.feature_names', []):
            response = self.client.get('/api/predict/options')
            self.assertEqual(response.status_code, 500)

    def test_predict_options_with_mocked_features(self):
        mock_features = ['tyre_age', 'fuel_load', 'tyre_Soft', 'tyre_Medium', 'track_Spa', 'track_Monaco']
        with patch('dashboard.feature_names', mock_features):
            response = self.client.get('/api/predict/options')
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertIn('tyres', data)
            self.assertIn('tracks', data)
            self.assertEqual(len(data['tracks']), 2)


    @patch('dashboard.get_db_connection')
    def test_session_laps_api_excludes_zero_ms_laps(self, mock_db):
        """The laps endpoint must filter in-progress (0 ms) laps, matching
        the sessions / tyre-degradation / latest-lap endpoints.
        """
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            {'lap_number': 1, 'lap_time': 95.0, 'tyre_compound': 'Soft',
             'tyre_age': 1, 'fuel_load': 108.0, 'is_valid': 1,
             'has_pit_stop': 0}
        ]

        response = self.client.get('/api/session/1/laps')
        self.assertEqual(response.status_code, 200)

        sql = mock_cursor.execute.call_args[0][0]
        self.assertIn('lap_time_ms > 0', sql,
                      "laps endpoint must exclude 0 ms in-progress laps")
        # Params: only the session_id is bound
        self.assertEqual(mock_cursor.execute.call_args[0][1], (1,))

    @patch('dashboard.get_db_connection')
    def test_get_tyre_degradation_api(self, mock_db):
        """Tyre-degradation returns fuel-adjusted stint deltas and must not
        split stints on spurious (sub-15s) pit events.
        """
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        # One clean stint with a pure fuel trend: times fall 0.5 s/lap,
        # zero wear.  Raw lap times span 1.5 s -- the deltas must not.
        mock_cursor.fetchall.return_value = [
            {'lap_number': 1, 'lap_time': 92.0, 'avg_lap_time': 92.0,
             'tyre_compound': 'Soft', 'tyre_age': 3, 'is_valid': 1,
             'has_pit_stop': 0},
            {'lap_number': 2, 'lap_time': 91.5, 'avg_lap_time': 91.5,
             'tyre_compound': 'Soft', 'tyre_age': 4, 'is_valid': 1,
             'has_pit_stop': 0},
            {'lap_number': 3, 'lap_time': 91.0, 'avg_lap_time': 91.0,
             'tyre_compound': 'Soft', 'tyre_age': 5, 'is_valid': 1,
             'has_pit_stop': 0},
            {'lap_number': 4, 'lap_time': 90.5, 'avg_lap_time': 90.5,
             'tyre_compound': 'Soft', 'tyre_age': 6, 'is_valid': 1,
             'has_pit_stop': 0},
        ]

        response = self.client.get('/api/session/1/tyre-degradation')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(len(data), 4)
        self.assertEqual(data[0]['tyre_compound'], 'Soft')
        # Fuel trend removed: every delta is ~0 despite raw times dropping.
        for row in data:
            self.assertLess(abs(row['stint_delta']), 1e-6)
            self.assertEqual(row['stint_number'], 1)

        sql = mock_cursor.execute.call_args[0][0]
        self.assertIn('duration_sec IS NULL OR se.duration_sec >= 15', sql,
                      "spurious (2.3s) pit events must not split stints, "
                      "but unknown-duration real pits must")

    @patch('dashboard.get_db_connection')
    def test_get_latest_lap_api(self, mock_db):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {
            'lap_time': 81.25,
            'lap_number': 5,
            'tyre_compound': 'Soft',
            'tyre_age': 5,
            'track_name': 'Spa'
        }

        response = self.client.get('/api/latest-lap')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data['track_name'], 'Spa')
        self.assertEqual(data['lap_number'], 5)


class StrategyFuelNeutralityTests(unittest.TestCase):
    """The stay-out vs pit comparison must not credit the fuel-burn effect
    that the model bakes into tyre_age.

    The model's tyre_age coefficient conflates fuel burn (laps genuinely get
    faster as the car lightens) with tyre wear.  Both scenarios burn the same
    fuel over the remaining race laps, so crediting the stay-out scenario's
    higher ages with it hands it a phantom |fuel_rate| * laps_rem * cur_age
    seconds of advantage — the old advisor therefore ALWAYS said "Stay Out".
    The dashboard detrends every scenario by the fuel-burn rate before
    comparing; these tests prove the phantom is gone and that pitting becomes
    a real option when the model genuinely shows wear.
    """

    COMPOUNDS = ('Soft', 'Medium', 'Hard')
    TRACK = 'Spa'

    def setUp(self):
        self.client = app.test_client()
        self.client.testing = True

    def _install_model(self, age_slope, fuel_burn_rate, intercept=90.0):
        """Inject a synthetic linear model with a known age slope."""
        import numpy as np
        import pandas as pd
        from sklearn.linear_model import LinearRegression

        feature_names = (['tyre_age']
                         + [f'tyre_{c}' for c in StrategyFuelNeutralityTests.COMPOUNDS]
                         + [f'track_{StrategyFuelNeutralityTests.TRACK}'])
        rows = []
        for age in range(0, 60):
            for c in StrategyFuelNeutralityTests.COMPOUNDS:
                row = {'tyre_age': age}
                row.update({f'tyre_{cc}': 1 if cc == c else 0
                            for cc in StrategyFuelNeutralityTests.COMPOUNDS})
                row[f'track_{StrategyFuelNeutralityTests.TRACK}'] = 1
                rows.append(row)
        X = pd.DataFrame(rows)[feature_names]
        y = intercept + age_slope * X['tyre_age'].values
        model = LinearRegression().fit(X, y)

        patch('dashboard.model', model).start()
        patch('dashboard.feature_names', feature_names).start()
        patch('dashboard.fuel_burn_rate', fuel_burn_rate).start()
        self.addCleanup(patch.stopall)

    def _analyze(self, cur_age):
        return self.client.post('/api/strategy/analyze', json={
            'current_lap': 10,
            'total_laps': 40,   # 30 laps remaining
            'current_tyre': 'Medium',
            'current_age': cur_age,
            'track': self.TRACK,
            'event_type': 'None',
        })

    def _totals(self, data):
        totals = {s['option']: s['total_time'] for s in data['strategies']}
        stay = next(v for k, v in totals.items() if k.startswith('Stay'))
        pit  = next(v for k, v in totals.items() if k.startswith('Pit'))
        return stay, pit

    def test_fuel_phantom_does_not_grow_with_age(self):
        """Fuel-only model: stay-vs-pit gap must be the pit loss at ANY age.

        Without detrending, a fuel-only model (age slope -0.06) makes the
        stay-out option look better by 0.06 * laps_rem * cur_age — 63 s at
        age 35 — which is why the old advisor always said Stay Out.  With the
        fuel-burn rate removed, the gap is exactly the pit loss at every age.
        """
        self._install_model(age_slope=-0.06, fuel_burn_rate=-0.06)

        for cur_age in (5, 20, 35):
            data = self._analyze(cur_age).get_json()
            stay, pit = self._totals(data)
            gap = stay - pit
            self.assertAlmostEqual(gap, -25.0, delta=1e-6,
                                   msg=f"age {cur_age}: stay-pit gap {gap:.2f}s "
                                       f"should be the -25s pit loss, not the "
                                       f"fuel phantom")
            self.assertTrue(data['recommendation']['action'].startswith('Stay'))

    def test_wear_model_pits_at_high_age(self):
        """A model that genuinely shows wear (positive age slope) must make
        pitting the recommendation once the degradation cost exceeds the pit
        loss — proving the comparison logic itself is not stuck on Stay Out.
        """
        self._install_model(age_slope=+0.15, fuel_burn_rate=0.0)

        # Fresh tyres, low age: degradation is cheap — stay out.
        data = self._analyze(cur_age=2).get_json()
        self.assertTrue(data['recommendation']['action'].startswith('Stay'),
                        data['recommendation'])

        # Old tyres, 30 laps left: wear cost (0.15 * 30 * 30 = 135 s) dwarfs
        # the 25 s pit loss — pitting must be recommended.
        data = self._analyze(cur_age=30).get_json()
        self.assertTrue(data['recommendation']['action'].startswith('Pit'),
                        data['recommendation'])
        stay, pit = self._totals(data)
        self.assertLess(pit, stay)

    def test_flat_model_stays_out_with_honest_reason(self):
        """When the model shows no wear (the real 2024 dataset), the advisor
        still recommends Stay Out — correctly — but the reason must explain
        the fuel-neutral comparison instead of blindly claiming the strategy
        is fastest.
        """
        self._install_model(age_slope=0.0, fuel_burn_rate=0.0)
        data = self._analyze(cur_age=30).get_json()
        self.assertTrue(data['recommendation']['action'].startswith('Stay'))
        self.assertIn('Fuel-neutral', data['recommendation']['reason'])


if __name__ == "__main__":
    unittest.main()
