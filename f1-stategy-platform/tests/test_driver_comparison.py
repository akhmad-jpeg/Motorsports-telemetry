import sys
import json
import tempfile
import unittest
import datetime
import joblib
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd
from sklearn.linear_model import LinearRegression

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import driver_comparison as dc
from dashboard import app


def _make_model(intercept, age_slope, tracks, tyres):
    """A linear model with a known intercept and tyre-age slope."""
    feature_names = (['tyre_age']
                     + [f'tyre_{t}' for t in tyres]
                     + [f'track_{k}' for k in tracks])
    rows = []
    for age in range(0, 30):
        for t in tyres:
            for k in tracks:
                row = {'tyre_age': age}
                row.update({f'tyre_{tt}': 1 if tt == t else 0 for tt in tyres})
                row.update({f'track_{kk}': 1 if kk == k else 0 for kk in tracks})
                rows.append(row)
    X = pd.DataFrame(rows)[feature_names]
    y = intercept + age_slope * X['tyre_age'].values
    return LinearRegression().fit(X, y), feature_names


def _write_driver(root, code, name, intercept, age_slope, tracks, tyres, laps=200, year=None):
    """Write a per-driver model; with year set, write the
    per-driver-per-year model into <code>/<year>/ instead."""
    ddir = root / code
    if year is not None:
        ddir = ddir / str(year)
    ddir.mkdir(parents=True, exist_ok=True)
    model, feats = _make_model(intercept, age_slope, tracks, tyres)
    joblib.dump(model, ddir / 'best_model.pkl')
    joblib.dump(feats, ddir / 'feature_names.pkl')
    info = {
        'driver': {'code': code, 'name': name},
        'best_model': 'LinearRegression',
        'metrics': {'within_track': {'mae': 0.4}},
        'training_samples': laps,
        'clean_laps': laps,
        'features': feats,
        'coverage': {'tracks': sorted(tracks), 'tyres': sorted(tyres)},
        'tyre_age_coefficient': age_slope,
        'fuel_burn_rate': min(0.0, age_slope),
    }
    if year is not None:
        info['year'] = year
    (ddir / 'model_info.json').write_text(json.dumps(info), encoding='utf-8')


class DriverComparisonTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        # A is 2 s/lap faster than B on every shared track/tyre/age.
        _write_driver(self.root, 'AAA', 'Alice', 90.0, 0.05,
                      ['Spa', 'Monaco'], ['Soft', 'Medium'])
        _write_driver(self.root, 'BBB', 'Bob', 92.0, 0.05,
                      ['Spa', 'Monaco', 'Imola'], ['Soft', 'Medium', 'Hard'])

    def tearDown(self):
        self._tmp.cleanup()

    def test_list_driver_models(self):
        drivers = dc.list_driver_models(self.root)
        self.assertEqual([d['code'] for d in drivers], ['AAA', 'BBB'])
        self.assertEqual(drivers[0]['name'], 'Alice')
        self.assertEqual(drivers[0]['laps'], 200)
        self.assertEqual(drivers[0]['tracks'], ['Monaco', 'Spa'])
        self.assertEqual(drivers[1]['tracks'], ['Imola', 'Monaco', 'Spa'])

    def test_compare_uses_only_shared_coverage(self):
        """Tracks/tyres only one driver covers must be excluded."""
        result = dc.compare_drivers('AAA', 'BBB', models_dir=self.root)
        self.assertEqual(result['shared']['tracks'], ['Monaco', 'Spa'])
        self.assertEqual(result['shared']['tyres'], ['Medium', 'Soft'])
        self.assertEqual([t['track'] for t in result['per_track']], ['Monaco', 'Spa'])
        # Imola is only in Bob's model — never compared.
        self.assertNotIn('Imola', [t['track'] for t in result['per_track']])
        # Hard is only in Bob's model — never compared.
        self.assertNotIn('Hard', [t['tyre'] for t in result['per_track'][0]['tyres']])

    def test_delta_sign_and_magnitude(self):
        """Alice is 2 s faster on every input: delta (A - B) == -2 always."""
        result = dc.compare_drivers('AAA', 'BBB', models_dir=self.root)
        for track in result['per_track']:
            self.assertAlmostEqual(track['avg_delta'], -2.0, places=6)
            for tyre in track['tyres']:
                for row in tyre['rows']:
                    self.assertAlmostEqual(row['delta'], -2.0, places=6)
                    self.assertAlmostEqual(row['driver_a'], row['driver_b'] - 2.0, places=6)
        s = result['summary']
        self.assertEqual(s['faster_code'], 'AAA')
        self.assertEqual(s['faster_name'], 'Alice')
        self.assertAlmostEqual(s['avg_delta'], -2.0, places=6)

    def test_reverse_order_flips_sign(self):
        result = dc.compare_drivers('BBB', 'AAA', models_dir=self.root)
        self.assertEqual(result['summary']['faster_code'], 'AAA')
        self.assertAlmostEqual(result['summary']['avg_delta'], 2.0, places=6)

    def test_same_driver_rejected(self):
        with self.assertRaises(ValueError):
            dc.compare_drivers('AAA', 'AAA', models_dir=self.root)

    def test_missing_driver_raises(self):
        with self.assertRaises(FileNotFoundError):
            dc.compare_drivers('AAA', 'ZZZ', models_dir=self.root)

    def test_empty_models_dir(self):
        with tempfile.TemporaryDirectory() as empty:
            self.assertEqual(dc.list_driver_models(Path(empty)), [])

    def test_list_driver_models_exposes_years(self):
        """Year subdirs (with a trained model) surface in each driver's years."""
        _write_driver(self.root, 'AAA', 'Alice', 90.0, 0.05,
                      ['Spa'], ['Soft'], laps=200, year=2021)
        _write_driver(self.root, 'AAA', 'Alice', 90.5, 0.05,
                      ['Spa'], ['Soft'], laps=200, year=2020)
        # BBB has only the aggregate model -> no years.
        drivers = {d['code']: d for d in dc.list_driver_models(self.root)}
        self.assertEqual(drivers['AAA']['years'], [2020, 2021])
        self.assertEqual(drivers['BBB']['years'], [])

    def test_load_driver_model_year_then_aggregate_fallback(self):
        """Requesting a year uses that model; missing year falls back to aggregate."""
        _write_driver(self.root, 'AAA', 'Alice', 91.0, 0.05,
                      ['Spa'], ['Soft'], laps=200, year=2021)
        model, feats, info, used_year = dc.load_driver_model('AAA', year=2021,
                                                             models_dir=self.root)
        self.assertEqual(used_year, 2021)
        self.assertEqual(info['year'], 2021)
        # BBB has no year model: requesting 2021 falls back to aggregate.
        _, _, info_b, used_b = dc.load_driver_model('BBB', year=2021,
                                                    models_dir=self.root)
        self.assertIsNone(used_b)
        self.assertNotIn('year', info_b)

    def test_compare_with_year_uses_same_season_models(self):
        """Aggregate says Alice 2s faster; the 2021 models say 1s."""
        _write_driver(self.root, 'AAA', 'Alice', 90.0, 0.05,
                      ['Spa', 'Monaco'], ['Soft', 'Medium'], laps=200, year=2021)
        _write_driver(self.root, 'BBB', 'Bob', 91.0, 0.05,
                      ['Spa', 'Monaco', 'Imola'], ['Soft', 'Medium', 'Hard'],
                      laps=200, year=2021)
        result = dc.compare_drivers('AAA', 'BBB', year=2021, models_dir=self.root)
        self.assertEqual(result['summary']['year_used'], 2021)
        self.assertEqual(result['driver_a']['year'], 2021)
        self.assertEqual(result['driver_b']['year'], 2021)
        self.assertAlmostEqual(result['summary']['avg_delta'], -1.0, places=6)

    def test_compare_year_falls_back_when_driver_has_no_season(self):
        """Only Alice has a 2021 model: Bob falls back to aggregate."""
        _write_driver(self.root, 'AAA', 'Alice', 91.0, 0.05,
                      ['Spa', 'Monaco'], ['Soft', 'Medium'], laps=200, year=2021)
        # Bob's aggregate is 92.0 (2s slower than Alice's aggregate 90.0,
        # 1s slower than her 2021 model) -- fallback picks the aggregate.
        result = dc.compare_drivers('AAA', 'BBB', year=2021, models_dir=self.root)
        self.assertIsNone(result['summary']['year_used'])
        self.assertEqual(result['driver_a']['year'], 2021)
        self.assertIsNone(result['driver_b']['year'])
        self.assertAlmostEqual(result['summary']['avg_delta'], -1.0, places=6)


class SignificanceTests(unittest.TestCase):
    """The compare payload labels the headline gap so it is not over-read
    when the models' noise (~1 s) exceeds the gap itself."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        # A is 2 s/lap faster than B on every shared input.
        _write_driver(self.root, 'AAA', 'Alice', 90.0, 0.05,
                      ['Spa', 'Monaco'], ['Soft', 'Medium'])
        _write_driver(self.root, 'BBB', 'Bob', 92.0, 0.05,
                      ['Spa', 'Monaco', 'Imola'], ['Soft', 'Medium', 'Hard'])

    def tearDown(self):
        self._tmp.cleanup()

    def _sig(self, *deltas):
        return dc._significance(list(deltas))

    def test_perfectly_consistent_gap_is_significant(self):
        sig = self._sig(-2.0, -2.0)
        self.assertEqual(sig['label'], 'significant')
        self.assertEqual(sig['p_value'], 0.0)
        self.assertEqual(sig['delta_std'], 0.0)

    def test_large_consistent_gap_is_significant(self):
        # ~1 s gap with small spread across 6 tracks -> p < 0.05
        sig = self._sig(1.0, 1.1, 0.9, 1.0, 1.0, 1.2)
        self.assertEqual(sig['label'], 'significant')
        self.assertLess(sig['p_value'], 0.05)

    def test_small_noisy_gap_is_inconclusive(self):
        # Mirrors the real 2021 HAM-vs-VER case: mean gap ~0.13 s with a
        # ~0.85 s spread across 19 tracks -> |t| << 2 -> p ~ 0.5 -> the
        # gap is indistinguishable from the between-track noise.
        deltas = [0.192 + (i % 5 - 2) * 0.6 for i in range(19)]
        sig = dc._significance(deltas)
        self.assertEqual(sig['label'], 'inconclusive')
        self.assertGreaterEqual(sig['p_value'], 0.20)
        self.assertIsNotNone(sig['t_statistic'])

    def test_fewer_than_two_tracks_is_insufficient(self):
        sig = self._sig(0.5)
        self.assertEqual(sig['label'], 'insufficient')
        self.assertIsNone(sig['p_value'])
        sig0 = self._sig()
        self.assertEqual(sig0['label'], 'insufficient')

    def test_zero_gap_is_not_significant(self):
        sig = self._sig(0.0, 0.0)
        self.assertEqual(sig['label'], 'inconclusive')

    def test_compare_payload_includes_significance(self):
        """AAA is 2 s faster on every shared input -> perfect consistency."""
        result = dc.compare_drivers('AAA', 'BBB', models_dir=self.root)
        sig = result['summary']['significance']
        self.assertEqual(sig['label'], 'significant')
        self.assertEqual(sig['n'], 2)
        self.assertAlmostEqual(sig['delta_mean'], -2.0, places=4)


class RaceComparisonApiTests(unittest.TestCase):
    """DB-driven race comparison endpoints: season -> track -> drivers -> laps."""

    def setUp(self):
        self.client = app.test_client()
        self.client.testing = True
        patcher = patch('dashboard.get_db_connection')
        self.mock_db = patcher.start()
        self.addCleanup(patcher.stop)
        self.conn = MagicMock()
        self.cursor = MagicMock()
        self.mock_db.return_value = self.conn
        self.conn.cursor.return_value = self.cursor

    def test_years(self):
        self.cursor.fetchall.return_value = [{'year': 2024}, {'year': 2023}]
        resp = self.client.get('/api/comparison/years')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()['years'], [2024, 2023])
        sql = self.cursor.execute.call_args[0][0]
        self.assertIn('DISTINCT YEAR(s.date)', sql)

    def test_tracks_requires_year(self):
        resp = self.client.get('/api/comparison/tracks')
        self.assertEqual(resp.status_code, 400)

    def test_tracks(self):
        self.cursor.fetchall.return_value = [{'track_name': 'Monza'}, {'track_name': 'Spa'}]  
        resp = self.client.get('/api/comparison/tracks?year=2024')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()['tracks'], ['Monza', 'Spa'])
        self.assertEqual(self.cursor.execute.call_args[0][1], (2024,))

    def test_drivers(self):
        rows = [
            {'driver_code': 'VER', 'driver_name': 'Max Verstappen', 'session_id': 10,
             'session_type': 'Race', 'date': datetime.date(2024, 9, 1), 'laps': 53},
            {'driver_code': 'LEC', 'driver_name': 'Charles Leclerc', 'session_id': 11,
             'session_type': 'Race', 'date': datetime.date(2024, 9, 1), 'laps': 53},
        ]
        self.cursor.fetchall.return_value = rows
        resp = self.client.get('/api/comparison/drivers?year=2024&track=Monza')
        self.assertEqual(resp.status_code, 200)
        drivers = resp.get_json()['drivers']
        self.assertEqual([d['code'] for d in drivers], ['LEC', 'VER'])
        self.assertEqual(drivers[1]['date'], '2024-09-01')

    def test_drivers_requires_params(self):
        resp = self.client.get('/api/comparison/drivers?year=2024')
        self.assertEqual(resp.status_code, 400)

    def test_drivers_duplicate_sessions_pick_best(self):
        """Two sessions for one driver on the same track/year: most laps wins."""
        rows = [
            {'driver_code': 'VER', 'driver_name': 'Max Verstappen', 'session_id': 5,
             'session_type': 'Race', 'date': datetime.date(2024, 9, 1), 'laps': 30},
            {'driver_code': 'VER', 'driver_name': 'Max Verstappen', 'session_id': 6,
             'session_type': 'Race', 'date': datetime.date(2024, 9, 1), 'laps': 53},
        ]
        self.cursor.fetchall.return_value = rows
        resp = self.client.get('/api/comparison/drivers?year=2024&track=Monza')
        drivers = resp.get_json()['drivers']
        self.assertEqual(len(drivers), 1)
        self.assertEqual(drivers[0]['session_id'], 6)

    def test_race(self):
        sessions = [
            {'driver_code': 'VER', 'driver_name': 'Max Verstappen', 'session_id': 10,
             'session_type': 'Race', 'date': datetime.date(2024, 9, 1), 'laps': 53},
            {'driver_code': 'LEC', 'driver_name': 'Charles Leclerc', 'session_id': 11,
             'session_type': 'Race', 'date': datetime.date(2024, 9, 1), 'laps': 53},
        ]
        laps_ver = [
            {'lap_id': 100, 'lap_number': 1, 'lap_time': 81.5, 'tyre_compound': 'Soft',
             'tyre_age': 1, 'is_valid': 1, 'has_pit_stop': 0},
            {'lap_id': 101, 'lap_number': 2, 'lap_time': 80.9, 'tyre_compound': 'Soft',
             'tyre_age': 2, 'is_valid': 1, 'has_pit_stop': 0},
        ]
        laps_lec = [
            {'lap_id': 200, 'lap_number': 1, 'lap_time': 82.0, 'tyre_compound': 'Soft',
             'tyre_age': 1, 'is_valid': 1, 'has_pit_stop': 0},
        ]
        # Telemetry aggregates: only VER lap 1 (lap_id 100) has rows.
        tel_ver = [
            {'lap_id': 100, 'avg_speed': 289.2, 'top_speed': 312.0,
             'avg_gear': 7.8, 'avg_rpm': 10843.5},
        ]
        self.cursor.fetchall.side_effect = [sessions, laps_ver, tel_ver, laps_lec, []]
        resp = self.client.get('/api/comparison/race?year=2024&track=Monza&drivers=VER,LEC')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(sorted(data['drivers'].keys()), ['LEC', 'VER'])
        ver_lap1 = data['drivers']['VER']['laps'][0]
        self.assertEqual(ver_lap1['lap_time'], 81.5)
        self.assertIs(ver_lap1['is_valid'], True)
        # Telemetry attached to the lap that has rows, with lap_id not leaked.
        self.assertNotIn('lap_id', ver_lap1)
        self.assertEqual(ver_lap1['telemetry']['avg_speed'], 289)
        self.assertEqual(ver_lap1['telemetry']['top_speed'], 312)
        self.assertEqual(ver_lap1['telemetry']['avg_gear'], 7.8)
        self.assertEqual(ver_lap1['telemetry']['avg_rpm'], 10844)
        # Laps without telemetry rows carry no 'telemetry' key.
        self.assertNotIn('telemetry', data['drivers']['VER']['laps'][1])
        self.assertNotIn('telemetry', data['drivers']['LEC']['laps'][0])
        self.assertEqual(data['track'], 'Monza')
        self.assertNotIn('missing', data)

    def test_race_missing_driver(self):
        sessions = [{'driver_code': 'VER', 'driver_name': 'Max Verstappen', 'session_id': 10,
                     'session_type': 'Race', 'date': datetime.date(2024, 9, 1), 'laps': 53}]
        laps = [{'lap_id': 100, 'lap_number': 1, 'lap_time': 81.5, 'tyre_compound': 'Soft',
                 'tyre_age': 1, 'is_valid': 1, 'has_pit_stop': 0}]
        self.cursor.fetchall.side_effect = [sessions, laps, []]
        resp = self.client.get('/api/comparison/race?year=2024&track=Monza&drivers=VER,ZZZ')
        data = resp.get_json()
        self.assertEqual(data['missing'], ['ZZZ'])
        self.assertIn('VER', data['drivers'])
        self.assertNotIn('telemetry', data['drivers']['VER']['laps'][0])

    def test_race_requires_params(self):
        resp = self.client.get('/api/comparison/race?year=2024&track=Monza')
        self.assertEqual(resp.status_code, 400)


class DriverComparisonApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.client.testing = True

    @patch('dashboard.driver_comparison.list_driver_models')
    def test_api_drivers_lists_models(self, mock_list):
        mock_list.return_value = [
            {'code': 'AAA', 'name': 'Alice', 'laps': 200, 'tracks': ['Spa'], 'tyres': ['Soft']}
        ]
        resp = self.client.get('/api/drivers')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()[0]['code'], 'AAA')

    @patch('dashboard.driver_comparison.compare_drivers')
    def test_api_drivers_compare(self, mock_compare):
        mock_compare.return_value = {
            'summary': {'faster_code': 'AAA',
                        'significance': {'label': 'significant', 'p_value': 0.01}},
            'per_track': []}
        resp = self.client.get('/api/drivers/compare?driver_a=AAA&driver_b=BBB')
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body['summary']['faster_code'], 'AAA')
        # Significance verdict passes through to the UI untouched.
        self.assertEqual(body['summary']['significance']['label'], 'significant')
        self.assertEqual(mock_compare.call_args[0][0:2], ('AAA', 'BBB'))
        # No year requested -> compare with aggregate models.
        self.assertIsNone(mock_compare.call_args[1].get('year'))

    @patch('dashboard.driver_comparison.compare_drivers')
    def test_api_drivers_compare_with_year(self, mock_compare):
        mock_compare.return_value = {'summary': {'faster_code': 'AAA', 'year_used': 2021},
                                     'per_track': []}
        resp = self.client.get('/api/drivers/compare?driver_a=AAA&driver_b=BBB&year=2021')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(mock_compare.call_args[1]['year'], 2021)
        self.assertEqual(resp.get_json()['summary']['year_used'], 2021)

    @patch('dashboard.driver_comparison.compare_drivers')
    def test_api_drivers_compare_rejects_bad_year(self, mock_compare):
        resp = self.client.get('/api/drivers/compare?driver_a=AAA&driver_b=BBB&year=abc')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('year', resp.get_json()['error'])
        mock_compare.assert_not_called()

    def test_api_drivers_compare_requires_params(self):
        resp = self.client.get('/api/drivers/compare')
        self.assertEqual(resp.status_code, 400)

    @patch('dashboard.driver_comparison.compare_drivers')
    def test_api_drivers_compare_missing_model_404(self, mock_compare):
        mock_compare.side_effect = FileNotFoundError('No per-driver model for ZZZ')
        resp = self.client.get('/api/drivers/compare?driver_a=AAA&driver_b=ZZZ')
        self.assertEqual(resp.status_code, 404)
        self.assertIn('ZZZ', resp.get_json()['error'])


if __name__ == "__main__":
    unittest.main()
