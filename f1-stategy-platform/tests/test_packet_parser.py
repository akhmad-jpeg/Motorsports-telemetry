import sys
import struct
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from capture_telemetry import parse_legacy_packet

# The F1 2018 game's "Legacy" UDP format is the F1 2017 combined packet
# (one 1289-byte packet, packed, little-endian).  Offsets below come from
# the official spec, "F1 2017 D-Box and UDP Output Specification"
# (forums.codemasters.com/discussion/53139):
#
#   m_lapTime              4   float   seconds elapsed on the current lap
#   m_speed               28   float   m/s (spec comment wrongly says MPH)
#   m_throttle           116   float   0.0–1.0
#   m_brake              124   float   0.0–1.0
#   m_gear               132   float   raw = display gear + 1
#   m_lap                144   float   current lap number
#   m_engineRate         148   float   engine RPM
#   m_drs                168   float   0 = off, 1 = on
#   m_in_pits            188   float   0 = none, 1 = pitting, 2 = in pit area
#   m_tyre_compound      312   byte    0 = ultrasoft … 6 = wet
#   m_currentLapInvalid  315   byte    0 = valid, 1 = invalid


def build_legacy_packet(*, lap_time=82.5, speed_ms=70.0, throttle=0.95,
                        brake=0.0, gear_raw=8.0, rpm=11500.0, drs=1.0,
                        lap_number=5.0, in_pits=0.0, compound=2,
                        lap_invalid=0):
    """Build a byte-accurate F1 2018 Legacy packet at the spec offsets."""
    data = bytearray(1289)
    struct.pack_into("<f", data, 4, lap_time)
    struct.pack_into("<f", data, 28, speed_ms)
    struct.pack_into("<f", data, 116, throttle)
    struct.pack_into("<f", data, 124, brake)
    struct.pack_into("<f", data, 132, gear_raw)
    struct.pack_into("<f", data, 144, lap_number)
    struct.pack_into("<f", data, 148, rpm)
    struct.pack_into("<f", data, 168, drs)
    struct.pack_into("<f", data, 188, in_pits)
    struct.pack_into("<B", data, 312, compound)
    struct.pack_into("<B", data, 315, lap_invalid)
    return bytes(data)


class PacketParserTests(unittest.TestCase):
    def test_parse_valid_legacy_packet(self):
        parsed = parse_legacy_packet(build_legacy_packet())

        self.assertIsNotNone(parsed)
        self.assertAlmostEqual(parsed['current_lap_time'], 82.5, places=1)
        self.assertEqual(parsed['speed'], 252)          # 70 m/s = 252 km/h
        self.assertEqual(parsed['throttle'], 0.95)
        self.assertEqual(parsed['brake'], 0.0)
        self.assertEqual(parsed['gear'], 7)             # raw 8 -> display 7
        self.assertEqual(parsed['rpm'], 11500)
        self.assertTrue(parsed['drs'])
        self.assertEqual(parsed['lap_number'], 5)
        self.assertEqual(parsed['in_pits'], 0)
        self.assertEqual(parsed['tyre_compound'], 'Soft')   # raw 2
        self.assertFalse(parsed['lap_invalid'])

    def test_rejects_empty_or_short_packet(self):
        self.assertIsNone(parse_legacy_packet(b""))
        self.assertIsNone(parse_legacy_packet(b"short payload"))
        # The spec fields live at offset 116+, so a 100-byte packet cannot
        # be a Legacy packet (the old parser accepted 76-byte packets).
        self.assertIsNone(parse_legacy_packet(bytes(100)))

    def test_speed_is_converted_from_metres_per_second(self):
        parsed = parse_legacy_packet(build_legacy_packet(speed_ms=90.0))
        self.assertEqual(parsed['speed'], 324)          # 90 m/s = 324 km/h

    def test_gear_raw_value_is_display_gear_plus_one(self):
        # raw 2 -> 1st gear, raw 1 -> neutral, raw 0 -> reverse
        self.assertEqual(
            parse_legacy_packet(build_legacy_packet(gear_raw=2.0))['gear'], 1)
        self.assertEqual(
            parse_legacy_packet(build_legacy_packet(gear_raw=1.0))['gear'], 0)
        self.assertEqual(
            parse_legacy_packet(build_legacy_packet(gear_raw=0.0))['gear'], -1)

    def test_clamps_out_of_bounds_telemetry(self):
        parsed = parse_legacy_packet(build_legacy_packet(
            speed_ms=500.0, throttle=1.5, brake=-0.5, rpm=20000.0))
        self.assertEqual(parsed['speed'], 400)          # 1800 km/h -> clamp
        self.assertEqual(parsed['throttle'], 1.0)
        self.assertEqual(parsed['brake'], 0.0)
        self.assertEqual(parsed['rpm'], 15000)

    def test_bytes_52_75_are_ignored(self):
        # Regression test for the old bug: the previous parser read
        # throttle/brake/gear/rpm/drs from bytes 52–75 (the suspension
        # arrays), which yielded garbage such as reverse gear on normal
        # laps and brake that never exceeded 0.12.  Those bytes must not
        # influence the parse at all.
        data = bytearray(build_legacy_packet())
        struct.pack_into("<f", data, 52, 0.0)           # old "throttle"
        struct.pack_into("<b", data, 72, -1)            # old "gear"
        struct.pack_into("<H", data, 73, 0)             # old "rpm"
        parsed = parse_legacy_packet(bytes(data))
        self.assertEqual(parsed['gear'], 7)             # still the spec value
        self.assertEqual(parsed['throttle'], 0.95)
        self.assertEqual(parsed['rpm'], 11500)

    def test_live_tyre_compound_mapping(self):
        self.assertEqual(
            parse_legacy_packet(build_legacy_packet(compound=0))['tyre_compound'],
            'Ultrasoft')
        self.assertEqual(
            parse_legacy_packet(build_legacy_packet(compound=1))['tyre_compound'],
            'Supersoft')
        self.assertEqual(
            parse_legacy_packet(build_legacy_packet(compound=3))['tyre_compound'],
            'Medium')
        self.assertEqual(
            parse_legacy_packet(build_legacy_packet(compound=5))['tyre_compound'],
            'Intermediate')
        self.assertEqual(
            parse_legacy_packet(build_legacy_packet(compound=6))['tyre_compound'],
            'Wet')

    def test_lap_invalid_and_pit_status_flags(self):
        self.assertTrue(
            parse_legacy_packet(build_legacy_packet(lap_invalid=1))['lap_invalid'])
        self.assertEqual(
            parse_legacy_packet(build_legacy_packet(in_pits=1.0))['in_pits'], 1)
        self.assertEqual(
            parse_legacy_packet(build_legacy_packet(in_pits=2.0))['in_pits'], 2)


if __name__ == "__main__":
    unittest.main()
