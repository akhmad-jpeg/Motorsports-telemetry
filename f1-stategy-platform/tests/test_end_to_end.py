import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from dashboard import app
from feature_pipeline import preprocess_laps_dataframe, construct_prediction_input
from fuel_estimation import estimate_fuel_load
from capture_telemetry import parse_legacy_packet


class EndToEndPipelineTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.client.testing = True

    def test_fuel_estimation_formula(self):
        # Lap 1: max(0, 110 - 2) = 108.0 kg
        self.assertEqual(estimate_fuel_load(1), 108.0)
        # Lap 55: max(0, 110 - 110) = 0.0 kg
        self.assertEqual(estimate_fuel_load(55), 0.0)
        # Lap 60: max(0, 110 - 120) = 0.0 kg (non-negative)
        self.assertEqual(estimate_fuel_load(60), 0.0)

    def test_feature_pipeline_consistency(self):
        df = pd.DataFrame([
            {'lap_time': 90.0, 'lap_number': 10, 'tyre_compound': 'Soft', 'track_name': 'Sakhir'},
            {'lap_time': 89.5, 'lap_number': 11, 'tyre_compound': 'Medium', 'track_name': 'Sakhir'}
        ])
        processed = preprocess_laps_dataframe(df)
        # No synthetic fuel feature (collinear with tyre_age), no lap_number
        self.assertNotIn('fuel_load', processed.columns)
        self.assertNotIn('lap_number', processed.columns)
        self.assertIn('tyre_Soft', processed.columns)
        self.assertIn('track_Sakhir', processed.columns)

    @patch('dashboard.get_db_connection')
    def test_dashboard_full_api_chain(self, mock_db):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        # Mock sessions API
        mock_cursor.fetchall.return_value = [
            {'session_id': 10, 'track_name': 'Sakhir', 'session_type': 'Race', 'weather': 'Clear', 'date': None, 'total_laps': 57, 'fastest_lap': 92.6}
        ]
        resp_sessions = self.client.get('/api/sessions')
        self.assertEqual(resp_sessions.status_code, 200)

        # Mock laps API
        mock_cursor.fetchall.return_value = [
            {'lap_number': 1, 'lap_time': 95.0, 'tyre_compound': 'Soft', 'tyre_age': 1, 'fuel_load': 108.0, 'is_valid': 1}
        ]
        resp_laps = self.client.get('/api/session/10/laps')
        self.assertEqual(resp_laps.status_code, 200)

        # Mock tyre degradation API
        mock_cursor.fetchall.return_value = [
            {'tyre_compound': 'Soft', 'tyre_age': 1, 'avg_lap_time': 95.0}
        ]
        resp_deg = self.client.get('/api/session/10/tyre-degradation')
        self.assertEqual(resp_deg.status_code, 200)


if __name__ == "__main__":
    unittest.main()
