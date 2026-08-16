import sys
import unittest
import pandas as pd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from feature_pipeline import (
    preprocess_laps_dataframe,
    construct_prediction_input,
    covered_tracks,
    covered_tyres,
    validate_model_inputs,
)


class FeaturePipelineTests(unittest.TestCase):
    def test_preprocess_laps_dataframe(self):
        raw_df = pd.DataFrame([
            {'lap_time': 80.5, 'lap_number': 1, 'tyre_age': 1, 'tyre_compound': 'Soft', 'track_name': 'Spa'},
            {'lap_time': 81.2, 'lap_number': 2, 'tyre_age': 2, 'tyre_compound': 'Medium', 'track_name': 'spa'}
        ])

        encoded = preprocess_laps_dataframe(raw_df)

        # The synthetic fuel feature was removed: it is perfectly collinear
        # with tyre_age inside a stint (fuel_load = 110 - 2*lap_number).
        self.assertNotIn('fuel_load', encoded.columns)
        self.assertNotIn('lap_number', encoded.columns)
        self.assertIn('tyre_age', encoded.columns)
        self.assertIn('tyre_Soft', encoded.columns)
        self.assertIn('tyre_Medium', encoded.columns)
        self.assertIn('track_Spa', encoded.columns)

    def test_construct_prediction_input(self):
        feature_names = ['tyre_age', 'tyre_Soft', 'tyre_Medium', 'track_Spa']
        input_df = construct_prediction_input(
            tyre_age=3,
            lap_number=5,
            tyre_compound='Soft',
            track_name='Spa',
            feature_names=feature_names
        )

        self.assertEqual(list(input_df.columns), feature_names)
        self.assertEqual(input_df.loc[0, 'tyre_age'], 3)
        self.assertEqual(input_df.loc[0, 'tyre_Soft'], 1)
        self.assertEqual(input_df.loc[0, 'tyre_Medium'], 0)
        self.assertNotIn('fuel_load', input_df.columns)

    def test_covered_tracks_and_tyres(self):
        feature_names = ['tyre_age', 'tyre_Soft', 'tyre_Medium', 'track_Spa', 'track_Monaco']
        self.assertEqual(covered_tracks(feature_names), ['Monaco', 'Spa'])
        self.assertEqual(covered_tyres(feature_names), ['Medium', 'Soft'])

    def test_validate_model_inputs(self):
        feature_names = ['tyre_age', 'tyre_Soft', 'track_Spa']
        # Covered inputs pass without raising
        validate_model_inputs('Soft', 'Spa', feature_names)

        # Unseen track raises with a clear message listing coverage
        with self.assertRaises(ValueError) as ctx_track:
            validate_model_inputs('Soft', 'Monaco', feature_names)
        self.assertIn('Monaco', str(ctx_track.exception))
        self.assertIn('Spa', str(ctx_track.exception))

        # Unseen tyre raises with a clear message listing coverage
        with self.assertRaises(ValueError) as ctx_tyre:
            validate_model_inputs('Hard', 'Spa', feature_names)
        self.assertIn('Hard', str(ctx_tyre.exception))
        self.assertIn('Soft', str(ctx_tyre.exception))

    def test_track_casing_is_normalised_like_training(self):
        # Sessions API returns raw FastF1 casing; the model is trained on the
        # title-cased form.  Both must resolve to the same feature.
        feature_names = ['tyre_age', 'tyre_Soft', 'track_Circuit De Barcelona-Catalunya']
        validate_model_inputs('Soft', 'Circuit de Barcelona-Catalunya', feature_names)

        inp = construct_prediction_input(
            tyre_age=2, lap_number=10, tyre_compound='Soft',
            track_name='Circuit de Barcelona-Catalunya',
            feature_names=feature_names)
        self.assertEqual(inp.loc[0, 'track_Circuit De Barcelona-Catalunya'], 1)


if __name__ == "__main__":
    unittest.main()
