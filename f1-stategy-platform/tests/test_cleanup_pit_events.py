"""cleanup_pit_events must reconcile PitStop events with reality.

The database should carry exactly one PitStop event per real pit stop,
attached to the in-lap.  The cleanup purges spurious stops (duration < 15s),
deletes phantom stops (no tyre change follows), and inserts missing events
(mid-race tyre change with no event) with a NULL duration.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cleanup_pit_events import (
    apply_fixes,
    find_inconsistencies,
    reconcile_pit_events,
    verify,
)


def lap(num, compound, age, lap_id=None, pit=False):
    return {
        'session_id': 1,
        'lap_number': num,
        'lap_id': lap_id if lap_id is not None else 100 + num,
        'tyre_compound': compound,
        'tyre_age': age,
        'has_pit_event': pit,
    }


class ReconcileTests(unittest.TestCase):

    def test_phantom_event_is_detected(self):
        # Pit event on L2, but L3 continues on the same tyre -> never happened.
        laps = [
            lap(1, 'Hard', 1, 101, False),
            lap(2, 'Hard', 2, 102, True),   # phantom
            lap(3, 'Hard', 3, 103, False),
        ]
        phantoms, missing = reconcile_pit_events(laps)
        self.assertEqual(phantoms, [102])
        self.assertEqual(missing, [])

    def test_real_event_is_kept(self):
        # Pit event on L2 followed by a compound change on L3 -> real.
        laps = [
            lap(1, 'Hard', 1, 101, False),
            lap(2, 'Hard', 2, 102, True),    # in-lap
            lap(3, 'Soft', 1, 103, False),   # out-lap (compound changed)
        ]
        phantoms, missing = reconcile_pit_events(laps)
        self.assertEqual(phantoms, [])
        self.assertEqual(missing, [])

    def test_age_drop_event_is_kept(self):
        # Same compound but age resets (fresh intermediates) -> real pit.
        laps = [
            lap(1, 'Intermediate', 27, 101, False),
            lap(2, 'Intermediate', 27, 102, True),   # in-lap (old set)
            lap(3, 'Intermediate', 1, 103, False),   # fresh set, age reset
        ]
        phantoms, missing = reconcile_pit_events(laps)
        self.assertEqual(phantoms, [])
        self.assertEqual(missing, [])

    def test_missing_mid_race_change_is_detected(self):
        # Age drops 4 -> 2 with no event on the in-lap (L3): missing.
        laps = [
            lap(1, 'Intermediate', 1, 101, False),
            lap(2, 'Intermediate', 2, 102, False),
            lap(3, 'Intermediate', 4, 103, False),   # in-lap, no event
            lap(4, 'Intermediate', 2, 104, False),   # fresh set
        ]
        phantoms, missing = reconcile_pit_events(laps)
        self.assertEqual(phantoms, [])
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]['lap_id'], 103)
        self.assertEqual(missing[0]['lap_number'], 3)

    def test_lap1_compound_jump_is_not_missing(self):
        # Race-start / red-flag quirk on lap 1: not a box stop, no event.
        laps = [
            lap(1, 'Hard', 1, 101, False),
            lap(2, 'Medium', 2, 102, False),
        ]
        phantoms, missing = reconcile_pit_events(laps)
        self.assertEqual(phantoms, [])
        self.assertEqual(missing, [])

    def test_phantom_requires_known_next_lap(self):
        # Next lap has unknown tyre data -> cannot verify -> keep the event.
        laps = [
            lap(1, 'Hard', 1, 101, False),
            {'session_id': 1, 'lap_number': 2, 'lap_id': 102,
             'tyre_compound': None, 'tyre_age': None, 'has_pit_event': True},
        ]
        phantoms, missing = reconcile_pit_events(laps)
        self.assertEqual(phantoms, [])
        self.assertEqual(missing, [])

    def test_gap_laps_still_detect_changes(self):
        # Deleted laps leave gaps; the next existing lap still counts.
        laps = [
            lap(1, 'Hard', 2, 101, False),
            lap(2, 'Hard', 3, 102, True),   # in-lap
            lap(5, 'Hard', 1, 105, False),  # out-lap (age drop 3 -> 1)
        ]
        phantoms, missing = reconcile_pit_events(laps)
        self.assertEqual(phantoms, [])
        self.assertEqual(missing, [])

    def test_last_lap_event_is_not_phantom(self):
        # Event on the final lap cannot be verified -> kept.
        laps = [
            lap(1, 'Hard', 1, 101, False),
            lap(2, 'Hard', 2, 102, True),
        ]
        phantoms, missing = reconcile_pit_events(laps)
        self.assertEqual(phantoms, [])
        self.assertEqual(missing, [])


class ApplyFixesTests(unittest.TestCase):

    def test_apply_fixes_issues_expected_sql(self):
        laps = [
            lap(1, 'Intermediate', 3, 101, False),
            lap(2, 'Intermediate', 4, 102, True),   # phantom (L3 unchanged)
            lap(3, 'Intermediate', 5, 103, False),
            lap(4, 'Intermediate', 6, 104, False),  # missing (age drop to L5)
            lap(5, 'Intermediate', 2, 105, False),
        ]
        cur = MagicMock()
        cur.fetchall.return_value = []   # no spurious sub-15s events
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = cur

        with patch('cleanup_pit_events.load_laps', return_value=laps):
            inc = apply_fixes(mock_conn)

        self.assertEqual(inc['phantoms'], [{'lap_id': 102, 'session_id': 1,
                                            'lap_number': 2}])
        self.assertEqual(len(inc['missing']), 1)
        self.assertEqual(inc['missing'][0]['lap_id'], 104)

        sqls = [c.args[0] for c in cur.execute.call_args_list]
        # Spurious purge (no rows, but the statement must be issued).
        self.assertTrue(any('duration_sec < %s' in s for s in sqls))
        # Phantom delete targets the phantom lap_id (as a bound parameter).
        del_call = next(c for c in cur.execute.call_args_list
                        if 'lap_id IN' in c.args[0])
        self.assertEqual(del_call.args[1], [102])
        # Missing inserts use a NULL duration (unknown box time).
        ins_sql = next(s for s in sqls if "INSERT INTO strategy_events" in s)
        self.assertIn('NULL', ins_sql)
        mock_conn.commit.assert_called_once()

    def test_apply_fixes_is_noop_on_clean_data(self):
        laps = [
            lap(1, 'Hard', 1, 101, False),
            lap(2, 'Hard', 2, 102, True),    # real (age drop to L3)
            lap(3, 'Hard', 1, 103, False),
        ]
        cur = MagicMock()
        cur.fetchall.return_value = []
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = cur
        with patch('cleanup_pit_events.load_laps', return_value=laps):
            inc = apply_fixes(mock_conn)
        self.assertEqual(inc['spurious'], [])
        self.assertEqual(inc['phantoms'], [])
        self.assertEqual(inc['missing'], [])
        # No DELETE / INSERT issued for pit reconciliation.
        sqls = [c.args[0] for c in cur.execute.call_args_list]
        self.assertFalse(any('DELETE' in s for s in sqls))
        self.assertFalse(any('INSERT' in s for s in sqls))
        mock_conn.commit.assert_called_once()


class VerifyTests(unittest.TestCase):

    def test_verify_reports_clean_state(self):
        cur = MagicMock()
        cur.fetchall.return_value = []          # no spurious events
        cur.fetchone.side_effect = [{'n': 0}, {'n': 0}]   # 0ms counts
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = cur
        with patch('cleanup_pit_events.load_laps', return_value=[]):
            v = verify(mock_conn)
        self.assertEqual(v, {
            'spurious': 0, 'phantoms': 0, 'missing': 0,
            'zero_ms_valid_laps': 0, 'zero_ms_total_laps': 0,
        })

    def test_verify_flags_zero_ms_valid_laps(self):
        cur = MagicMock()
        cur.fetchall.return_value = []
        cur.fetchone.side_effect = [{'n': 2}, {'n': 2}]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = cur
        with patch('cleanup_pit_events.load_laps', return_value=[]):
            v = verify(mock_conn)
        self.assertEqual(v['zero_ms_valid_laps'], 2)


if __name__ == "__main__":
    unittest.main()
