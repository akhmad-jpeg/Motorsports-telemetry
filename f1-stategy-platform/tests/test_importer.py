"""
Unit tests for F1 Race Data Importer logic.

Tests are kept DB-free: database calls are mocked where needed.
"""

import queue
import threading
import time
import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from import_f1_race import (
    normalize_compound,
    get_or_create_source,
    get_or_create_regulation,
    get_or_create_season,
    get_or_create_track,
    upsert_driver_from_fastf1,
    resolve_driver_input,
    resolve_race_input,
    classify_weather,
    RACE_CALENDAR,
)


class NormalizeCompoundTests(unittest.TestCase):
    def test_legacy_compounds(self):
        for raw, expected in [
            ("HYPERSOFT",    "Hypersoft"),
            ("ULTRASOFT",    "Ultrasoft"),
            ("SUPERSOFT",    "Supersoft"),
            ("SOFT",         "Soft"),
            ("MEDIUM",       "Medium"),
            ("HARD",         "Hard"),
            ("INTERMEDIATE", "Intermediate"),
            ("WET",          "Wet"),
        ]:
            with self.subTest(raw=raw):
                self.assertEqual(normalize_compound(raw), expected)

    def test_unknown_compound_is_not_fabricated(self):
        # A missing or unknown compound must come back as None -- never a
        # guessed "Soft" -- so the caller can record it honestly (NULL).
        self.assertIsNone(normalize_compound(None))
        self.assertIsNone(normalize_compound(float("nan")))
        self.assertIsNone(normalize_compound("UNKNOWN_THING"))
        # Pirelli C-codes are not FastF1 compound strings; no guessing.
        self.assertIsNone(normalize_compound("C1"))
        self.assertIsNone(normalize_compound("C5"))


class RegulationEraTests(unittest.TestCase):
    def _make_cursor(self, lastrowid=10):
        cursor = MagicMock()
        cursor.fetchone.return_value = None  # force creation path
        cursor.lastrowid = lastrowid
        return cursor

    def test_turbo_hybrid_era(self):
        cursor = self._make_cursor(10)
        self.assertEqual(get_or_create_regulation(cursor, 2020), 10)

    def test_ground_effect_era(self):
        cursor = self._make_cursor(11)
        self.assertEqual(get_or_create_regulation(cursor, 2024), 11)

    def test_2026_era(self):
        cursor = self._make_cursor(12)
        self.assertEqual(get_or_create_regulation(cursor, 2026), 12)

    def test_returns_existing_without_insert(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = (5,)
        self.assertEqual(get_or_create_regulation(cursor, 2023), 5)
        # Must NOT have called INSERT
        for call in cursor.execute.call_args_list:
            self.assertNotIn("INSERT", str(call))


class SourceAndSeasonTests(unittest.TestCase):
    def test_get_or_create_source_existing(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = (2,)
        self.assertEqual(get_or_create_source(cursor, "FastF1", "Real World"), 2)

    def test_get_or_create_season_new(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.lastrowid = 7
        self.assertEqual(get_or_create_season(cursor, 2024, 3), 7)


class TrackTests(unittest.TestCase):
    def test_new_track_created(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.lastrowid = 55
        track_id, canonical = get_or_create_track(cursor, "sakhir", "Bahrain")
        self.assertEqual(track_id, 55)
        self.assertEqual(canonical, "Sakhir")

    def test_existing_track_returned(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = (3, "Monaco")
        track_id, canonical = get_or_create_track(cursor, "Monaco")
        self.assertEqual(track_id, 3)
        self.assertEqual(canonical, "Monaco")


class DriverUpsertTests(unittest.TestCase):
    def test_inserts_new_driver(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        upsert_driver_from_fastf1(cursor, 16, "LEC", "Charles Leclerc")
        # Verify an INSERT was issued
        calls = [str(c) for c in cursor.execute.call_args_list]
        self.assertTrue(any("INSERT" in c for c in calls))

    def test_skips_existing_driver(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = (16,)  # already in DB
        upsert_driver_from_fastf1(cursor, 16, "LEC", "Charles Leclerc")
        calls = [str(c) for c in cursor.execute.call_args_list]
        # Must NOT have issued an INSERT
        self.assertFalse(any("INSERT" in c for c in calls))


class ResolveDriverInputTests(unittest.TestCase):
    DB_DRIVERS = [
        {"driver_id": 16, "driver_code": "LEC", "driver_name": "Charles Leclerc"},
        {"driver_id": 44, "driver_code": "HAM", "driver_name": "Lewis Hamilton"},
        {"driver_id":  1, "driver_code": "VER", "driver_name": "Max Verstappen"},
    ]

    def test_resolve_by_number(self):
        d = resolve_driver_input("16", self.DB_DRIVERS)
        self.assertEqual(d["driver_id"], 16)
        self.assertEqual(d["driver_code"], "LEC")

    def test_resolve_by_code(self):
        d = resolve_driver_input("HAM", self.DB_DRIVERS)
        self.assertEqual(d["driver_id"], 44)

    def test_resolve_code_case_insensitive(self):
        d = resolve_driver_input("ver", self.DB_DRIVERS)
        self.assertEqual(d["driver_id"], 1)

    def test_invalid_number_raises(self):
        with self.assertRaises(ValueError):
            resolve_driver_input("99", self.DB_DRIVERS)

    def test_invalid_code_raises(self):
        with self.assertRaises(ValueError):
            resolve_driver_input("ZZZ", self.DB_DRIVERS)

    def test_no_silent_fallback(self):
        """Entering '0' must not silently select anyone."""
        with self.assertRaises(ValueError):
            resolve_driver_input("0", self.DB_DRIVERS)


class ResolveRaceInputTests(unittest.TestCase):
    CALENDAR = ["Bahrain", "Saudi Arabia", "Australia", "Monaco"]

    def test_by_number(self):
        self.assertEqual(resolve_race_input("1", self.CALENDAR), "Bahrain")
        self.assertEqual(resolve_race_input("4", self.CALENDAR), "Monaco")

    def test_by_name_passthrough(self):
        self.assertEqual(resolve_race_input("Spa", self.CALENDAR), "Spa")

    def test_out_of_range_raises(self):
        with self.assertRaises(ValueError):
            resolve_race_input("99", self.CALENDAR)


class RaceCalendarTests(unittest.TestCase):
    def test_calendar_has_expected_years(self):
        for year in (2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025):
            self.assertIn(year, RACE_CALENDAR)
            self.assertGreater(len(RACE_CALENDAR[year]), 0)

    def test_calendar_2025_is_the_full_season(self):
        self.assertEqual(len(RACE_CALENDAR[2025]), 24)
        self.assertEqual(RACE_CALENDAR[2025][0], "Australia")
        self.assertEqual(RACE_CALENDAR[2025][-1], "Abu Dhabi")


class PitStopDurationLogicTests(unittest.TestCase):
    """
    Test the pit-stop duration calculation in isolation.

    The importer collects pit_in_rows during the lap loop, then resolves
    durations via pit_out_by_lapnum in a second pass.  We replicate that
    logic here without touching the DB.
    """

    @staticmethod
    def _compute_duration(pit_in_time, pit_out_same, next_lap_out):
        """Mirror of the duration logic in import_race step 5b."""
        import pandas as pd
        duration_sec = None

        if next_lap_out is not None:
            try:
                delta = (next_lap_out - pit_in_time).total_seconds()
                if 2.0 <= delta <= 120.0:
                    duration_sec = round(delta, 2)
            except Exception:
                pass

        if duration_sec is None and pd.notna(pit_out_same):
            try:
                delta = (pit_out_same - pit_in_time).total_seconds()
                if 2.0 <= delta <= 120.0:
                    duration_sec = round(delta, 2)
            except Exception:
                pass

        return duration_sec

    def test_uses_next_lap_pitout_primary(self):
        """Next-lap PitOutTime should give realistic duration."""
        import pandas as pd
        pit_in = pd.Timedelta("1:10:00")
        next_out = pd.Timedelta("1:10:22.5")
        result = self._compute_duration(pit_in, None, next_out)
        self.assertAlmostEqual(result, 22.5, places=1)

    def test_fallback_to_same_lap_pitout(self):
        """When next-lap PitOutTime is absent, fall back to same-lap value."""
        import pandas as pd
        pit_in  = pd.Timedelta("1:10:00")
        same_out = pd.Timedelta("1:10:19.0")
        result = self._compute_duration(pit_in, same_out, None)
        self.assertAlmostEqual(result, 19.0, places=1)

    def test_implausible_duration_returns_none(self):
        """A 1-second delta (< 2 s floor) is implausible; should return None."""
        import pandas as pd
        pit_in   = pd.Timedelta("1:10:00")
        bad_out  = pd.Timedelta("1:10:00.5")
        result = self._compute_duration(pit_in, bad_out, None)
        self.assertIsNone(result)

    def test_next_lap_takes_priority_over_same_lap(self):
        """next_lap_out should always win when both are available."""
        import pandas as pd
        pit_in   = pd.Timedelta("1:10:00")
        same_out = pd.Timedelta("1:10:30")  # 30 s
        next_out = pd.Timedelta("1:10:20")  # 20 s — should win
        result = self._compute_duration(pit_in, same_out, next_out)
        self.assertAlmostEqual(result, 20.0, places=1)

    def test_none_when_no_pitout_at_all(self):
        """No PitOutTime available → return None (DNF/final lap)."""
        import pandas as pd
        pit_in = pd.Timedelta("1:10:00")
        result = self._compute_duration(pit_in, None, None)
        self.assertIsNone(result)


class RaceControlMessageParsingTests(unittest.TestCase):
    """
    Test the RC message pattern-matching logic in isolation.
    We replicate the deploy/end state-machine from step 5c and verify
    it correctly identifies SafetyCar, VSC, and RedFlag periods.
    """

    RC_PATTERNS = [
        (
            "SafetyCar",
            ["SAFETY CAR DEPLOYED", "SAFETY CAR IN THIS LAP"],
            ["SAFETY CAR IN THIS LAP", "SAFETY CAR WITHDRAWN", "TRACK CLEAR"],
        ),
        (
            "VSC",
            ["VIRTUAL SAFETY CAR DEPLOYED"],
            ["VIRTUAL SAFETY CAR ENDING", "TRACK CLEAR"],
        ),
        (
            "RedFlag",
            ["RED FLAG", "SESSION SUSPENDED"],
            ["SESSION RESTARTED", "SESSION RESUMED", "TRACK CLEAR"],
        ),
    ]

    def _run_pattern(self, event_type, deploy_kws, end_kws, messages):
        """
        Run the deploy/end state machine on a list of (time_sec, message) tuples.
        Returns list of computed durations (None if unknown).
        """
        import pandas as pd
        results = []
        pending = None
        for t, msg in messages:
            upper = msg.upper().strip()
            if pending is None:
                if any(kw in upper for kw in deploy_kws):
                    pending = t
            else:
                if any(kw in upper for kw in end_kws):
                    dur = round(t - pending, 1) if t - pending > 0 else None
                    results.append(dur)
                    pending = None
                elif any(kw in upper for kw in deploy_kws):
                    results.append(None)
                    pending = t
        if pending is not None:
            results.append(None)
        return results

    def test_safety_car_detected_and_duration_computed(self):
        msgs = [
            (0,    "Green light - GO"),
            (1200, "SAFETY CAR DEPLOYED"),
            (1380, "SAFETY CAR WITHDRAWN"),
        ]
        durations = self._run_pattern(*self.RC_PATTERNS[0], msgs)
        self.assertEqual(len(durations), 1)
        self.assertAlmostEqual(durations[0], 180.0)

    def test_vsc_detected(self):
        msgs = [
            (500,  "VIRTUAL SAFETY CAR DEPLOYED"),
            (620,  "VIRTUAL SAFETY CAR ENDING"),
        ]
        durations = self._run_pattern(*self.RC_PATTERNS[1], msgs)
        self.assertEqual(len(durations), 1)
        self.assertAlmostEqual(durations[0], 120.0)

    def test_red_flag_detected(self):
        msgs = [
            (100,  "RED FLAG"),
            (800,  "SESSION RESTARTED"),
        ]
        durations = self._run_pattern(*self.RC_PATTERNS[2], msgs)
        self.assertEqual(len(durations), 1)
        self.assertAlmostEqual(durations[0], 700.0)

    def test_no_false_positive_on_normal_messages(self):
        msgs = [
            (0,   "GREEN LIGHT - GO"),
            (100, "TRACK CLEAR"),
            (200, "DRS ENABLED"),
        ]
        durations = self._run_pattern(*self.RC_PATTERNS[0], msgs)
        self.assertEqual(durations, [])  # No SC deployed, nothing recorded

    def test_multiple_sc_periods(self):
        msgs = [
            (100,  "SAFETY CAR DEPLOYED"),
            (250,  "SAFETY CAR WITHDRAWN"),
            (600,  "SAFETY CAR DEPLOYED"),
            (900,  "TRACK CLEAR"),
        ]
        durations = self._run_pattern(*self.RC_PATTERNS[0], msgs)
        self.assertEqual(len(durations), 2)
        self.assertAlmostEqual(durations[0], 150.0)
        self.assertAlmostEqual(durations[1], 300.0)

    def test_unclosed_event_at_session_end(self):
        """SC deployed but no withdrawal message → duration=None, but event recorded."""
        msgs = [(100, "SAFETY CAR DEPLOYED")]
        durations = self._run_pattern(*self.RC_PATTERNS[0], msgs)
        self.assertEqual(len(durations), 1)
        self.assertIsNone(durations[0])

class WeatherClassificationTests(unittest.TestCase):
    """Tests for classify_weather() against mocked FastF1 session objects."""

    @staticmethod
    def _make_session(rainfall_values):
        """Return a mock session whose weather_data has the given Rainfall list."""
        import pandas as pd
        session = MagicMock()
        session.weather_data = pd.DataFrame({"Rainfall": rainfall_values})
        return session

    def test_all_dry_returns_dry(self):
        session = self._make_session([0, 0, 0, 0, 0])
        self.assertEqual(classify_weather(session), "Dry")

    def test_all_wet_returns_wet(self):
        session = self._make_session([1, 1, 1, 1, 1])
        self.assertEqual(classify_weather(session), "Wet")

    def test_majority_wet_returns_wet(self):
        # 6/10 samples rainy = 60% >= 50% threshold
        session = self._make_session([1, 1, 1, 1, 1, 1, 0, 0, 0, 0])
        self.assertEqual(classify_weather(session), "Wet")

    def test_minority_wet_returns_mixed(self):
        # 2/10 samples rainy = 20% (>= 10% but < 50%)
        session = self._make_session([1, 1, 0, 0, 0, 0, 0, 0, 0, 0])
        self.assertEqual(classify_weather(session), "Mixed")

    def test_trace_rain_below_threshold_is_dry(self):
        # 1/20 = 5% < 10% threshold → still Dry
        session = self._make_session([1] + [0] * 19)
        self.assertEqual(classify_weather(session), "Dry")

    def test_exactly_50_percent_is_wet(self):
        session = self._make_session([1, 1, 0, 0])
        self.assertEqual(classify_weather(session), "Wet")

    def test_exactly_10_percent_is_mixed(self):
        session = self._make_session([1, 0, 0, 0, 0, 0, 0, 0, 0, 0])
        self.assertEqual(classify_weather(session), "Mixed")

    def test_empty_weather_data_returns_dry(self):
        import pandas as pd
        session = MagicMock()
        session.weather_data = pd.DataFrame()
        self.assertEqual(classify_weather(session), "Dry")

    def test_no_rainfall_column_returns_dry(self):
        import pandas as pd
        session = MagicMock()
        session.weather_data = pd.DataFrame({"AirTemp": [25.0, 26.0]})
        self.assertEqual(classify_weather(session), "Dry")

    def test_missing_weather_data_attribute_returns_dry(self):
        session = MagicMock(spec=[])  # no weather_data attribute
        self.assertEqual(classify_weather(session), "Dry")

    def test_boolean_rainfall_column(self):
        """FastF1 may return Rainfall as boolean True/False."""
        session = self._make_session([True, True, True, False, False])
        # 3/5 = 60% → Wet
        self.assertEqual(classify_weather(session), "Wet")



class CaptureWeatherNormalisationTests(unittest.TestCase):
    """Tests for capture_telemetry.normalise_weather()."""

    def setUp(self):
        from capture_telemetry import normalise_weather
        self.normalise = normalise_weather

    def test_dry_aliases(self):
        for raw in ("Dry", "Clear", "Sunny", "Fine", "Overcast", "Cloudy",
                    "clear", "DRY", "CLOUDY"):
            with self.subTest(raw=raw):
                self.assertEqual(self.normalise(raw), "Dry")

    def test_wet_aliases(self):
        for raw in ("Wet", "Rain", "Rainy", "Raining", "Storm", "Stormy",
                    "WET", "RAIN"):
            with self.subTest(raw=raw):
                self.assertEqual(self.normalise(raw), "Wet")

    def test_mixed_aliases(self):
        for raw in ("Mixed", "Changeable", "Variable", "Showers", "Shower",
                    "MIXED", "showers"):
            with self.subTest(raw=raw):
                self.assertEqual(self.normalise(raw), "Mixed")

    def test_unknown_falls_back_to_dry(self):
        self.assertEqual(self.normalise("SomethingElse"), "Dry")
        self.assertEqual(self.normalise(""), "Dry")


class CaptureStrategyEventTests(unittest.TestCase):
    """Tests for capture_telemetry.detect_strategy_events()."""

    def setUp(self):
        from capture_telemetry import detect_strategy_events
        self.detect = detect_strategy_events

    def _detect(self, **kw):
        defaults = dict(
            lap_time_ms=85_000,
            tyre_changed=False,
            saw_pit_flag=False,
            avg_speed_kmh=220,
            expected_lap_ms=85_000,
            recent_lap_ms_list=[84_000, 85_000, 86_000],
            expected_avg_speed_kmh=220,
        )
        defaults.update(kw)
        return self.detect(**defaults)

    # Typical clean lap — no events
    def test_clean_lap_no_events(self):
        self.assertEqual(self._detect(), [])

    # Tyre change → PitStop (primary signal, live compound byte)
    def test_tyre_change_triggers_pitstop(self):
        events = self._detect(lap_time_ms=110_000, tyre_changed=True,
                              saw_pit_flag=True)
        self.assertEqual([e[0] for e in events], ["PitStop"])

    # In-pits flag + REALISTIC in-lap (~100 s, NOT > 180 s) → PitStop.
    # The old gate required > 180 s, which real in-laps never reach.
    def test_in_pit_flag_triggers_pitstop_on_realistic_inlap(self):
        events = self._detect(lap_time_ms=110_000,   # ~25 s over expected
                              saw_pit_flag=True, avg_speed_kmh=170)
        self.assertEqual([e[0] for e in events], ["PitStop"])

    # In-pits flag but a normal-speed lap → no event (guards against
    # spurious pit stops on laps that merely pass the pit lane entry).
    def test_in_pit_flag_without_slow_lap_no_event(self):
        events = self._detect(lap_time_ms=88_000, saw_pit_flag=True,
                              avg_speed_kmh=215)
        self.assertEqual(events, [])

    # Safety Car: very slow lap AND very low lap-average speed
    def test_safety_car_detected(self):
        events = self._detect(lap_time_ms=115_000,   # 35% over expected
                              avg_speed_kmh=95)      # < 75% of 220
        types = [e[0] for e in events]
        self.assertIn("SafetyCar", types)
        self.assertNotIn("VSC", types)
        self.assertNotIn("RedFlag", types)

    # VSC: moderately slow lap AND clearly reduced lap-average speed
    def test_vsc_detected(self):
        events = self._detect(lap_time_ms=100_000,   # ~18% over → VSC band
                              avg_speed_kmh=180)     # 82% of 220 → below 90% gate
        types = [e[0] for e in events]
        self.assertIn("VSC", types)
        self.assertNotIn("SafetyCar", types)

    # THE audit complaint: a 15-30% slower lap at NORMAL speed is traffic or
    # a mistake, not a VSC — the old code had no speed check at all.
    def test_slow_lap_at_normal_speed_is_not_vsc(self):
        events = self._detect(lap_time_ms=100_000,   # ~18% over → in VSC band…
                              avg_speed_kmh=215)     # …but speed is normal
        self.assertEqual(events, [])

    # Red Flag: near standstill for most of the lap — and it beats pit
    # detection (a >= 200% lap is never a pit stop, even while pitting).
    def test_red_flag_detected(self):
        events = self._detect(lap_time_ms=200_000, saw_pit_flag=True,
                              avg_speed_kmh=40)
        types = [e[0] for e in events]
        self.assertIn("RedFlag", types)
        self.assertNotIn("SafetyCar", types)
        self.assertNotIn("PitStop", types)

    # PitStop under SC: tyre change → PitStop; SC is NOT added because pit
    # detection blocks race-control event detection on the same lap.
    def test_pitstop_blocks_safety_car(self):
        events = self._detect(lap_time_ms=115_000, tyre_changed=True,
                              saw_pit_flag=True, avg_speed_kmh=95)
        self.assertEqual([e[0] for e in events], ["PitStop"])

    # Duration clamp: pit stop duration must be in [2, 60] even for a very
    # long in-lap (extra = 65 s over expected here → clamped to 60).
    def test_pitstop_duration_clamped(self):
        events = self._detect(lap_time_ms=150_000, tyre_changed=True,
                              saw_pit_flag=True, avg_speed_kmh=180)
        pitstop_events = [e for e in events if e[0] == "PitStop"]
        self.assertEqual(len(pitstop_events), 1)
        dur = pitstop_events[0][1]
        self.assertGreaterEqual(dur, 2.0)
        self.assertLessEqual(dur, 60.0)
        self.assertEqual(dur, 60.0)

    # No recent laps / no speed history → absolute fallback thresholds;
    # must not raise, and VSC must not fire without speed context.
    def test_no_recent_laps_uses_fallback(self):
        events = self._detect(lap_time_ms=100_000,   # in VSC time band
                              recent_lap_ms_list=[],
                              expected_avg_speed_kmh=0.0)
        self.assertIsInstance(events, list)
        self.assertEqual(events, [])


class CaptureWorkerLivenessTests(unittest.TestCase):
    """The capture loop must not busy-wait forever when the DB worker dies (#7).

    The old code spun on `while key not in res_holder: sleep(0.01)` with no
    timeout and no way to learn the worker thread had died.  These tests pin
    the replacement: _wait_for_result() fails fast on a dead worker or a
    timeout, and db_worker() records its death so the main loop can detect it.
    """

    def setUp(self):
        from capture_telemetry import (
            _wait_for_result,
            _raise_if_worker_dead,
            DBWorkerError,
        )
        self._wait_for_result     = _wait_for_result
        self._raise_if_worker_dead = _raise_if_worker_dead
        self.DBWorkerError        = DBWorkerError

    class _AliveWorker:
        def is_alive(self):
            return True

    class _DeadWorker:
        def is_alive(self):
            return False

    def test_wait_returns_when_worker_fills_result(self):
        holder = {'session_id': 7}
        # Already filled → returns immediately, no busy-wait.
        self._wait_for_result(holder, self._AliveWorker(), {},
                              'session creation', timeout=5)
        self.assertEqual(holder['session_id'], 7)

    def test_wait_polls_until_filled(self):
        holder = {}
        def fill():
            time.sleep(0.03)
            holder['lap_id'] = 42
        t = threading.Thread(target=fill)
        t.start()
        try:
            self._wait_for_result(holder, self._AliveWorker(), {},
                                  'lap creation', timeout=5)
        finally:
            t.join()
        self.assertEqual(holder['lap_id'], 42)

    def test_dead_worker_raises_clear_error(self):
        """THE audit case: worker dies → the wait must raise immediately
        (with the recorded DB error), not spin forever."""
        holder = {}
        with self.assertRaises(self.DBWorkerError) as ctx:
            self._wait_for_result(
                holder, self._DeadWorker(),
                {'exc': RuntimeError('Can\'t connect to MySQL')},
                'session creation', timeout=30,
            )
        msg = str(ctx.exception)
        self.assertIn('session creation', msg)
        self.assertIn('MySQL', msg)          # last DB error surfaced
        self.assertIn('Stopping capture', msg)

    def test_live_worker_but_no_result_times_out(self):
        holder = {}
        start = time.monotonic()
        with self.assertRaises(self.DBWorkerError) as ctx:
            self._wait_for_result(holder, self._AliveWorker(), {},
                                  'lap creation', timeout=0.05)
        self.assertLess(time.monotonic() - start, 2.0)   # fails fast
        self.assertIn('Timed out', str(ctx.exception))

    def test_raise_if_worker_dead_noop_when_alive(self):
        # Must not raise while the worker is healthy.
        self._raise_if_worker_dead(self._AliveWorker(), {})

    def test_raise_if_worker_dead_raises_when_dead(self):
        with self.assertRaises(self.DBWorkerError) as ctx:
            self._raise_if_worker_dead(
                self._DeadWorker(), {'exc': ConnectionError('db gone')})
        self.assertIn('db gone', str(ctx.exception))

    @patch('capture_telemetry.get_db_connection',
           side_effect=RuntimeError('no mysql'))
    def test_db_worker_records_death_error(self, _mock_conn):
        """db_worker must surface its exception through error_holder so the
        main loop can distinguish 'worker died' from 'still working'."""
        from capture_telemetry import db_worker
        worker_error = {}
        db_worker(queue.Queue(), threading.Event(), 'Spa', worker_error)
        self.assertIn('exc', worker_error)
        self.assertIsInstance(worker_error['exc'], RuntimeError)
        self.assertEqual(str(worker_error['exc']), 'no mysql')

    def test_worker_clean_exit_records_no_error(self):
        """A normal shutdown (stop_event set, queue drained) is NOT a death."""
        from capture_telemetry import db_worker
        q = queue.Queue()
        stop = threading.Event()
        stop.set()
        worker_error = {}
        with patch('capture_telemetry.get_db_connection') as mock_conn:
            mock_conn.return_value = MagicMock()
            db_worker(q, stop, 'Spa', worker_error)
        self.assertNotIn('exc', worker_error)


class CaptureLapValidityTests(unittest.TestCase):
    """In-progress laps (lap_time_ms = 0) must never be stored as valid.

    The capture loop inserts a lap at 0 ms when it starts and only fills in
    the real time via update_lap_time() when it completes.  If capture stops
    mid-lap, the 0 ms row used to remain is_valid=1 — which made
    analyze_performance report a 0.000 s fastest lap.  Only the completion
    path may mark a lap valid.
    """

    def _insert(self, lap_time_ms, is_valid):
        from capture_telemetry import insert_lap
        conn = MagicMock()
        cursor = MagicMock()
        cursor.lastrowid = 42
        conn.cursor.return_value = cursor
        lap_id = insert_lap(conn, 1, 1, lap_time_ms, "Soft", 1, 100.0,
                            is_valid, 1)
        return cursor, lap_id

    def test_in_progress_lap_inserted_as_invalid(self):
        cursor, lap_id = self._insert(lap_time_ms=0, is_valid=False)
        self.assertEqual(lap_id, 42)
        # is_valid column receives 0 for the in-progress lap
        self.assertEqual(cursor.execute.call_args[0][1][7], 0)

    def test_completed_lap_can_be_valid(self):
        cursor, _ = self._insert(lap_time_ms=85_000, is_valid=True)
        self.assertEqual(cursor.execute.call_args[0][1][7], 1)

    def test_update_lap_time_sets_validity(self):
        from capture_telemetry import update_lap_time
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        update_lap_time(conn, 42, 85_000, True)
        sql, params = cursor.execute.call_args[0]
        self.assertIn("lap_time_ms = %s", sql)
        self.assertEqual(params, (85_000, 1, 42))
        conn.commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
