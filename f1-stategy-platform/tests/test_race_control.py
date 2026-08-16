import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from import_f1_race import extract_race_control_events


class _FakeSession:
    """Minimal stand-in for a fastf1 Session exposing the two data sources."""

    def __init__(self, track_status=None, race_control_messages=None):
        self.track_status = track_status
        self.race_control_messages = race_control_messages


def _track_status(seconds, statuses, messages):
    return pd.DataFrame({
        "Time": pd.to_timedelta(seconds, unit="s"),
        "Status": statuses,
        "Message": messages,
    })


def _messages(seconds, texts):
    return pd.DataFrame({
        "Time": pd.to_timedelta(seconds, unit="s"),
        "Message": texts,
    })


class TrackStatusExtractionTests(unittest.TestCase):
    def test_monaco_style_red_flag_then_safety_car(self):
        # Monaco 2024 sequence: yellow, red flag, clear, SC deploy, clear.
        ts = _track_status(
            seconds=[48.957, 3330.229, 5258.765, 5756.551, 5865.833],
            statuses=[1, 5, 1, 4, 1],
            messages=["AllClear", "Red", "AllClear", "SCDeployed", "AllClear"],
        )
        events = extract_race_control_events(_FakeSession(track_status=ts))
        self.assertEqual(events, [
            ("RedFlag", round(5258.765 - 3330.229, 1)),     # ~31.8 min
            ("SafetyCar", round(5865.833 - 5756.551, 1)),   # ~1.8 min
        ])

    def test_vsc_deploy_end_clear(self):
        # Miami 2024-style VSC: deploy -> ending -> all clear.
        ts = _track_status(
            seconds=[0, 5416.624, 5457.133, 5468.221],
            statuses=[1, 6, 7, 1],
            messages=["AllClear", "VSCDeployed", "VSCEnding", "AllClear"],
        )
        events = extract_race_control_events(_FakeSession(track_status=ts))
        self.assertEqual(events, [("VSC", round(5457.133 - 5416.624, 1))])

    def test_numeric_codes_without_message_text(self):
        # No Message column: fall back to numeric codes (4 = SC, 5 = red).
        ts = pd.DataFrame({
            "Time": pd.to_timedelta([0, 100, 400], unit="s"),
            "Status": [1, 5, 1],
        })
        events = extract_race_control_events(_FakeSession(track_status=ts))
        self.assertEqual(events, [("RedFlag", 300.0)])

    def test_unclosed_period_has_null_duration(self):
        ts = _track_status(
            seconds=[0, 100],
            statuses=[1, 4],
            messages=["AllClear", "SCDeployed"],
        )
        events = extract_race_control_events(_FakeSession(track_status=ts))
        self.assertEqual(events, [("SafetyCar", None)])


class MessageFallbackTests(unittest.TestCase):
    def test_repeated_safety_car_in_this_lap_is_keep_alive(self):
        # Regression test for the old bug: "SAFETY CAR IN THIS LAP" appeared
        # in BOTH deploy and end keywords, chopping one SC period into many.
        rcm = _messages(
            seconds=[100, 200, 300, 400],
            texts=[
                "SAFETY CAR IN THIS LAP",
                "SAFETY CAR IN THIS LAP",
                "SAFETY CAR IN THIS LAP",
                "SAFETY CAR WITHDRAWN",
            ],
        )
        events = extract_race_control_events(
            _FakeSession(track_status=None, race_control_messages=rcm)
        )
        self.assertEqual(events, [("SafetyCar", 300.0)])

    def test_red_flag_via_messages(self):
        rcm = _messages(
            seconds=[1000, 2900],
            texts=["RED FLAG", "TRACK CLEAR"],
        )
        events = extract_race_control_events(
            _FakeSession(track_status=None, race_control_messages=rcm)
        )
        self.assertEqual(events, [("RedFlag", 1900.0)])

    def test_vsc_via_messages(self):
        rcm = _messages(
            seconds=[500, 800],
            texts=["VIRTUAL SAFETY CAR DEPLOYED", "VIRTUAL SAFETY CAR ENDING"],
        )
        events = extract_race_control_events(
            _FakeSession(track_status=None, race_control_messages=rcm)
        )
        self.assertEqual(events, [("VSC", 300.0)])

    def test_chequered_flag_is_not_a_red_flag(self):
        # "CHEQUERED FLAG" contains "RED FLAG" as a substring — the
        # word-boundary matcher must not treat it as a deployment.
        rcm = _messages(
            seconds=[1000, 2000],
            texts=["CAR 1 TIME 1:34.193 DELETED - TRACK LIMITS AT TURN 4",
                   "CHEQUERED FLAG"],
        )
        events = extract_race_control_events(
            _FakeSession(track_status=None, race_control_messages=rcm)
        )
        self.assertEqual(events, [])

    def test_eventless_track_status_is_authoritative(self):
        # A green/yellow-only session must yield NO events even if the text
        # feed contains deploy-like phrases.
        ts = _track_status(
            seconds=[0, 100, 200],
            statuses=[1, 2, 1],
            messages=["AllClear", "Yellow", "AllClear"],
        )
        rcm = _messages(
            seconds=[50, 150],
            texts=["RED FLAG", "TRACK CLEAR"],
        )
        events = extract_race_control_events(
            _FakeSession(track_status=ts, race_control_messages=rcm)
        )
        self.assertEqual(events, [])

    def test_no_data_sources_returns_empty(self):
        self.assertEqual(extract_race_control_events(_FakeSession()), [])


if __name__ == "__main__":
    unittest.main()
