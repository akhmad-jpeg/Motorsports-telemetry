"""
F1 Game Telemetry Capture System
=================================
Listens for UDP packets from the F1 2017/2018 game and persists session, lap,
telemetry, and strategy-event data to MySQL.

Key design decisions
--------------------
* driver_id = 0  (GAME_DRIVER_ID) is the sentinel for all game/simulator data.
  It is never a real F1 racing number.
* Track names are normalised through the same get_or_create_track() used by
  import_f1_race.py so game and real-world sessions share the tracks table.
* Tyre compounds are normalised through the same TYRE_COMPOUND_MAP /
  normalize_compound() used by import_f1_race.py.
* Weather labels are mapped to Dry / Wet / Mixed — identical to the labels
  written by classify_weather() in import_f1_race.py.
* Strategy events use the existing ENUM values:
    PitStop, SafetyCar, VSC, RedFlag
"""

import socket
import struct
import argparse
import queue
import threading
import time
from datetime import datetime
from pathlib import Path
import sys

# Allow sibling imports (fuel_estimation, config, import_f1_race helpers)
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fuel_estimation import estimate_fuel_load
from config import get_db_connection
# Re-use the exact same normalisation helpers as the FastF1 importer so that
# compound names and track names land in the same DB rows.
from import_f1_race import (
    TYRE_COMPOUND_MAP,
    normalize_compound,
    get_or_create_track,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Sentinel driver_id for all game/simulator sessions.
# Must never collide with a real F1 racing number.
GAME_DRIVER_ID = 0

# UDP listener defaults
UDP_IP   = "0.0.0.0"
UDP_PORT = 20777

# How often to persist a telemetry sample (every Nth packet ≈ 1 Hz at 60 fps)
TELEMETRY_SAMPLE_RATE = 60

# Lap-time validity window (milliseconds)
MIN_VALID_LAP_MS = 60_000    # 60 s  – shorter than this is clearly wrong
MAX_VALID_LAP_MS = 180_000   # 3 min – longer than this is an out-lap / SC lap

# Strategy-event detection thresholds
# Pit stop: a live tyre-compound change is the primary signal; the in-pits
# flag with a lap at least PIT_STOP_MIN_EXTRA_SEC slower than the rolling
# median is the secondary signal.  Real F1 in-laps are ~20-40 s slower than
# a normal lap (100 s vs 70-90 s), so there is NO 180 s gate — the old gate
# made pit stops undetectable.
PIT_STOP_MIN_EXTRA_SEC = 15

# Safety Car: lap time >= 130% of expected AND lap-average speed < 75% of the
# recent lap-average speed (relative, so it works on any track; the absolute
# threshold is the fallback before 3 speed samples exist).
SC_LAP_TIME_RATIO_MIN  = 1.30
SC_SPEED_RATIO         = 0.75
SC_SPEED_THRESHOLD_KMH = 120

# VSC: lap time 115-130% of expected AND lap-average speed < 90% of recent.
# The speed gate is what stops traffic / mistake laps (15-30% slower but at
# normal speed) from false-positiving as VSC.
VSC_LAP_TIME_RATIO_MIN = 1.15
VSC_LAP_TIME_RATIO_MAX = 1.30
VSC_SPEED_RATIO        = 0.90

# Red Flag: lap time >= 200% of expected AND lap-average speed < 40% of
# recent (near standstill).  Absolute fallback threshold as for SC.
REDFLAG_LAP_TIME_RATIO_MIN  = 2.00
REDFLAG_SPEED_RATIO         = 0.40
REDFLAG_SPEED_THRESHOLD_KMH = 60

# ---------------------------------------------------------------------------
# Weather normalisation
# ---------------------------------------------------------------------------

# Maps user-supplied weather words → DB-compatible labels matching
# classify_weather() in import_f1_race.py (Dry / Wet / Mixed).
_WEATHER_MAP: dict[str, str] = {
    "dry":          "Dry",
    "clear":        "Dry",
    "sunny":        "Dry",
    "fine":         "Dry",
    "overcast":     "Dry",
    "cloudy":       "Dry",
    "wet":          "Wet",
    "rain":         "Wet",
    "rainy":        "Wet",
    "raining":      "Wet",
    "storm":        "Wet",
    "stormy":       "Wet",
    "mixed":        "Mixed",
    "changeable":   "Mixed",
    "variable":     "Mixed",
    "showers":      "Mixed",
    "shower":       "Mixed",
}


def normalise_weather(raw: str) -> str:
    """Map any user-supplied weather description to Dry, Wet, or Mixed.

    Falls back to 'Dry' for unrecognised inputs — same safe default used by
    classify_weather() in import_f1_race.py when sensor data is unavailable.
    """
    return _WEATHER_MAP.get(raw.strip().lower(), "Dry")


# ---------------------------------------------------------------------------
# F1 2017/2018 Legacy UDP packet parser
# ---------------------------------------------------------------------------
#
# The F1 2018 game's "Legacy" UDP format is the F1 2017 combined telemetry
# packet: one 1289-byte packet, packed with no padding, little-endian.
# Official spec: "F1 2017 D-Box and UDP Output Specification"
# (forums.codemasters.com/discussion/53139).  Offsets used below:
#
#   m_lapTime              4   float   seconds elapsed on the current lap
#   m_speed               28   float   car speed in m/s
#                                      (the original spec comment wrongly
#                                      says MPH — m/s confirmed in-thread)
#   m_throttle           116   float   0.0–1.0
#   m_brake              124   float   0.0–1.0
#   m_gear               132   float   raw value = display gear + 1
#                                      (0 = reverse, 1 = neutral, 2 = 1st…)
#   m_lap                144   float   current lap number
#   m_engineRate         148   float   engine RPM
#   m_drs                168   float   0 = off, 1 = on
#   m_in_pits            188   float   0 = none, 1 = pitting, 2 = in pit area
#   m_tyre_compound      312   byte    0 = ultrasoft … 6 = wet (see below)
#   m_currentLapInvalid  315   byte    0 = valid, 1 = invalid
#   m_car_data           337   CarUDPData[20]
#
# The first 337 bytes (everything we read) are identical across every
# released F1 2017 packet version, so 337 is the minimum accepted length.

# Live tyre-compound byte from the Legacy packet (offset 312).  Values map
# straight onto the DB tyre_compound ENUM used by the FastF1 importer.
LEGACY_COMPOUND_MAP: dict[int, str] = {
    0: "Ultrasoft",
    1: "Supersoft",
    2: "Soft",
    3: "Medium",
    4: "Hard",
    5: "Intermediate",
    6: "Wet",
}


def parse_legacy_packet(data: bytes) -> dict | None:
    """Parse an F1 2017/2018 Legacy UDP packet.

    Returns a dict with:
        current_lap_time  – seconds elapsed on the current lap
        speed             – km/h (0–400), converted from the raw m/s field
        throttle          – 0.0–1.0
        brake             – 0.0–1.0
        gear              – -1 (reverse), 0 (neutral), 1–8
        rpm               – 0–15000
        drs               – bool
        lap_number        – current lap number reported by the game
        in_pits           – 0 = none, 1 = pitting, 2 = in pit area
        tyre_compound     – normalised compound from the live packet byte
                           (None when the byte is not a known compound —
                           garbage during a wheel change is ignored)
        lap_invalid       – True when the game flags the current lap invalid

    Returns None if the packet is too short to be a valid Legacy packet.
    """
    if not data or len(data) < 337:
        return None
    try:
        current_lap_time = struct.unpack("<f", data[4:8])[0]
        speed_ms         = struct.unpack("<f", data[28:32])[0]

        throttle        = struct.unpack("<f", data[116:120])[0]
        brake           = struct.unpack("<f", data[124:128])[0]
        gear_raw        = struct.unpack("<f", data[132:136])[0]
        lap_number      = struct.unpack("<f", data[144:148])[0]
        rpm             = struct.unpack("<f", data[148:152])[0]
        drs_raw         = struct.unpack("<f", data[168:172])[0]
        in_pits         = struct.unpack("<f", data[188:192])[0]
        compound_raw    = struct.unpack("<B", data[312:313])[0]
        lap_invalid_raw = struct.unpack("<B", data[315:316])[0]

        # Unknown bytes (e.g. garbage during a wheel change) map to None so
        # the capture loop can ignore them instead of faking a tyre change.
        live_compound = LEGACY_COMPOUND_MAP.get(compound_raw)

        # m_speed is metres/second (the spec comment wrongly says MPH);
        # convert to km/h to match the telemetry table and speed thresholds.
        speed_kmh = speed_ms * 3.6

        # m_gear is the display gear + 1 (0 = reverse, 1 = neutral,
        # 2 = 1st … 9 = 8th), so subtract 1 to get the FastF1-style
        # convention stored in the DB: -1 = reverse, 0 = neutral, 1–8.
        gear = int(round(gear_raw)) - 1

        return {
            "current_lap_time": current_lap_time,
            "speed":            int(max(0, min(400, speed_kmh))),
            "throttle":         round(max(0.0, min(1.0, throttle)), 2),
            "brake":            round(max(0.0, min(1.0, brake)), 2),
            "gear":             max(-1, min(8, gear)),
            "rpm":              int(max(0, min(15_000, rpm))),
            "drs":              drs_raw >= 0.5,
            "lap_number":       int(round(lap_number)),
            "in_pits":          int(round(in_pits)),
            "tyre_compound":    live_compound,
            "lap_invalid":      lap_invalid_raw == 1,
        }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Strategy-event detection
# ---------------------------------------------------------------------------

def detect_strategy_events(
    lap_time_ms: int,
    tyre_changed: bool,
    saw_pit_flag: bool,
    avg_speed_kmh: float,
    expected_lap_ms: int,
    recent_lap_ms_list: list[int],
    expected_avg_speed_kmh: float = 0.0,
) -> list[tuple[str, float]]:
    """
    Detect strategy events from completed-lap telemetry signals.

    Returns a list of (event_type, duration_sec) tuples — 0 or 1 item.

    Event-type strings exactly match the strategy_events ENUM in the schema:
        PitStop | SafetyCar | VSC | RedFlag

    Signals
    -------
    * tyre_changed        – the live compound byte changed vs the previous lap
                            (definitive pit stop)
    * saw_pit_flag        – the car was seen in the pit area during this lap
                            (m_in_pits >= 1)
    * avg_speed_kmh       – FULL-LAP average speed (not the last 2 s of
                            finish-line speed, which is always high and made
                            SC/RedFlag undetectable)
    * expected_avg_speed_kmh – median lap-average speed of recent valid laps,
                            used for track-relative speed gates (0.0 = no
                            history yet → absolute fallback thresholds)

    Detection logic (in priority order)
    -------------------------------------
    1. RedFlag   – lap time >= 200% of expected AND avg speed < 40% of recent
                   (or < 60 km/h with no history).  Dominates pit detection:
                   a >= 200% lap is never a pit stop.

    2. PitStop   – tyre compound changed, OR the in-pits flag was seen AND the
                   lap was >= PIT_STOP_MIN_EXTRA_SEC slower than expected.
                   Real in-laps are ~100 s (20-40 s over a normal lap) — no
                   180 s gate.  Duration = (lap_time_ms – median recent) / 1000,
                   clamped [2, 60].

    3. SafetyCar – lap time >= 130% of expected AND avg speed < 75% of recent
                   (or < 120 km/h with no history).

    4. VSC       – lap time in [115%, 130%) of expected AND avg speed < 90%
                   of recent.  The speed gate is required: a 15-30% slower
                   lap at normal speed is traffic or a mistake, not a VSC.
                   Skipped when no speed history exists yet.

    Notes
    -----
    * A slow lap alone never produces an event.  A pit stop requires a
      compound change or the in-pits flag, and race-control events require
      a speed signature — a slow lap at normal speed (traffic, a mistake)
      stays silent instead of fabricating a spurious pit/VSC.
    * Race-control events never fire on a lap detected as a pit stop — the
      in-lap's slow pit-lane segment would otherwise false-positive as VSC/SC.
    * SC and VSC are mutually exclusive (SC wins if both conditions met).
    """
    # Baseline expected lap time
    if expected_lap_ms <= 0:
        expected_lap_ms = 90_000  # safe fallback (1:30)

    ratio     = lap_time_ms / expected_lap_ms
    extra_sec = (lap_time_ms - expected_lap_ms) / 1000.0

    def _slow_enough(relative_ratio: float, absolute_kmh: float) -> bool:
        """Track-relative speed gate, with an absolute fallback before 3
        valid lap-average speeds exist."""
        if expected_avg_speed_kmh > 0:
            return avg_speed_kmh < expected_avg_speed_kmh * relative_ratio
        return avg_speed_kmh < absolute_kmh

    # ------------------------------------------------------------------
    # 1. RedFlag — dominates everything
    # ------------------------------------------------------------------
    if (ratio >= REDFLAG_LAP_TIME_RATIO_MIN
            and _slow_enough(REDFLAG_SPEED_RATIO, REDFLAG_SPEED_THRESHOLD_KMH)):
        return [("RedFlag", round(lap_time_ms / 1000.0, 1))]

    # ------------------------------------------------------------------
    # 2. PitStop — tyre change (definitive) or in-pits flag + slow lap
    # ------------------------------------------------------------------
    if tyre_changed or (saw_pit_flag and extra_sec >= PIT_STOP_MIN_EXTRA_SEC):
        baseline = (
            sorted(recent_lap_ms_list)[len(recent_lap_ms_list) // 2]
            if recent_lap_ms_list
            else expected_lap_ms
        )
        duration = max(2.0, min(60.0, (lap_time_ms - baseline) / 1000.0))
        return [("PitStop", round(duration, 1))]

    # ------------------------------------------------------------------
    # 3. SafetyCar
    # ------------------------------------------------------------------
    if (ratio >= SC_LAP_TIME_RATIO_MIN
            and _slow_enough(SC_SPEED_RATIO, SC_SPEED_THRESHOLD_KMH)):
        return [("SafetyCar", round(lap_time_ms / 1000.0, 1))]

    # ------------------------------------------------------------------
    # 4. VSC — needs speed history for the track-relative speed gate
    # ------------------------------------------------------------------
    if (VSC_LAP_TIME_RATIO_MIN <= ratio < VSC_LAP_TIME_RATIO_MAX
            and expected_avg_speed_kmh > 0
            and avg_speed_kmh < expected_avg_speed_kmh * VSC_SPEED_RATIO):
        return [("VSC", round(lap_time_ms / 1000.0, 1))]

    return []



# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def ensure_game_driver(conn) -> None:
    """Guarantee driver_id=0 (Player sentinel) exists in the drivers table.

    Must be called once per connection before any FK reference to driver_id=0.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT driver_id FROM drivers WHERE driver_id = 0")
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO drivers (driver_id, driver_code, driver_name) "
            "VALUES (0, 'PLY', 'Player')"
        )
        conn.commit()
        print("[DB] Created sentinel driver row: driver_id=0 (Player)")
    cursor.close()


def insert_session(conn, track_id: int, track_name: str,
                   session_type: str, weather: str,
                   driver_id: int) -> int:
    """Insert a new session row and return session_id."""
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO sessions (track_id, track_name, session_type, weather, date, driver_id)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (track_id, track_name, session_type, weather,
         datetime.now().date(), driver_id),
    )
    session_id = cursor.lastrowid
    conn.commit()
    cursor.close()
    print(f"[SESSION] Created ID={session_id}, Track={track_name}, "
          f"Weather={weather}, driver_id={driver_id}")
    return session_id


def insert_lap(conn, session_id: int, lap_number: int, lap_time_ms: int,
               tyre_compound: str, tyre_age: int, fuel_load: float,
               is_valid: bool, driver_id: int) -> int:
    """Insert a lap row and return lap_id."""
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO laps
          (session_id, driver_id, lap_number, lap_time_ms,
           tyre_compound, tyre_age, fuel_load, is_valid)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (session_id, driver_id, lap_number, lap_time_ms,
         tyre_compound, tyre_age, fuel_load, 1 if is_valid else 0),
    )
    lap_id = cursor.lastrowid
    conn.commit()
    cursor.close()
    return lap_id


def update_lap_time(conn, lap_id: int, lap_time_ms: int, is_valid: bool) -> None:
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE laps SET lap_time_ms = %s, is_valid = %s WHERE lap_id = %s",
        (lap_time_ms, 1 if is_valid else 0, lap_id),
    )
    conn.commit()
    cursor.close()


def insert_telemetry(conn, lap_id: int, speed: int, throttle: float,
                     brake: float, gear: int, rpm: int, drs: bool) -> None:
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO telemetry (lap_id, speed, throttle, brake, gear, rpm, drs) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (lap_id, speed, throttle, brake, gear, rpm, 1 if drs else 0),
    )
    conn.commit()
    cursor.close()


def insert_strategy_event(conn, lap_id: int | None,
                          event_type: str, duration_sec: float) -> None:
    """Insert a strategy_events row.

    lap_id may be None for session-wide events (RedFlag, SafetyCar, VSC)
    that should not be pinned to one driver's lap.  The schema allows NULL.
    """
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO strategy_events (lap_id, event_type, duration_sec) "
        "VALUES (%s, %s, %s)",
        (lap_id, event_type, duration_sec),
    )
    conn.commit()
    cursor.close()
    print(f"[EVENT] {event_type} logged "
          f"(lap_id={lap_id}, duration={duration_sec}s)")


# ---------------------------------------------------------------------------
# Asynchronous DB worker thread
# ---------------------------------------------------------------------------

def db_worker(db_queue: queue.Queue, stop_event: threading.Event,
              raw_track_name: str, error_holder: dict) -> None:
    """
    Consume DB-write tasks from db_queue on a background thread.

    Resolves the track through get_or_create_track() (same as FastF1 importer)
    and stores the track_id in the session row.

    error_holder: dict shared with the main thread.  If the worker dies on an
    exception (e.g. the MySQL connection drops mid-capture), the exception is
    stored under error_holder["exc"] so the capture loop can detect the death
    instead of busy-waiting forever on a result that will never arrive.

    Task tuple formats
    ------------------
    ('insert_session',  session_type, weather, driver_id, res_holder)
    ('insert_lap',      session_id, lap_number, lap_time_ms, compound,
                        tyre_age, fuel_load, is_valid, driver_id, res_holder)
    ('update_lap_time', lap_id, lap_time_ms, is_valid)
    ('insert_telemetry',lap_id, speed, throttle, brake, gear, rpm, drs)
    ('insert_strategy_event', lap_id, event_type, duration_sec)
    """
    conn = None
    try:
        conn = get_db_connection()
        ensure_game_driver(conn)

        # Resolve/create track once per session using the same helper as
        # import_f1_race.py so game and FastF1 data share the tracks table.
        cursor = conn.cursor()
        track_id, canonical_track = get_or_create_track(cursor, raw_track_name)
        conn.commit()
        cursor.close()
        print(f"[DB] Track resolved: '{canonical_track}' (track_id={track_id})")

        while not stop_event.is_set() or not db_queue.empty():
            try:
                task = db_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            action = task[0]

            if action == "insert_session":
                _, session_type, weather, driver_id, res_holder = task
                res_holder["session_id"] = insert_session(
                    conn, track_id, canonical_track,
                    session_type, weather, driver_id,
                )
            elif action == "insert_lap":
                _, session_id, lap_number, lap_time_ms, compound, \
                    tyre_age, fuel_load, is_valid, driver_id, res_holder = task
                res_holder["lap_id"] = insert_lap(
                    conn, session_id, lap_number, lap_time_ms,
                    compound, tyre_age, fuel_load, is_valid, driver_id,
                )
            elif action == "update_lap_time":
                _, lap_id, lap_time_ms, is_valid = task
                update_lap_time(conn, lap_id, lap_time_ms, is_valid)
            elif action == "insert_telemetry":
                _, lap_id, speed, throttle, brake, gear, rpm, drs = task
                insert_telemetry(conn, lap_id, speed, throttle, brake, gear, rpm, drs)
            elif action == "insert_strategy_event":
                _, lap_id, event_type, duration_sec = task
                insert_strategy_event(conn, lap_id, event_type, duration_sec)

            db_queue.task_done()

    except Exception as exc:
        print(f"[DB WORKER ERROR] {exc}")
        # Record the death so the capture loop can fail fast instead of
        # busy-waiting on a result that will never arrive.
        error_holder["exc"] = exc
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Worker-liveness helpers
# ---------------------------------------------------------------------------

class DBWorkerError(RuntimeError):
    """Raised when the DB worker thread dies or stalls mid-capture."""


def _raise_if_worker_dead(worker: threading.Thread, error_holder: dict,
                          what: str = "running") -> None:
    """Fail fast if the DB worker thread has exited unexpectedly.

    Without this check the capture loop keeps accepting UDP packets and
    queueing DB writes that can never be persisted — the old code only
    noticed nothing was wrong.
    """
    if worker.is_alive():
        return
    exc = error_holder.get("exc")
    detail = f"Last error: {exc!r}" if exc else "No error recorded."
    # ASCII only: these messages are printed to the console, and non-ASCII
    # (e.g. an em-dash) renders as '�' in Windows cp1252 consoles.
    raise DBWorkerError(
        f"DB worker thread died while {what}. Stopping capture - nothing "
        f"further will be persisted. {detail}"
    )


def _wait_for_result(res_holder: dict, worker: threading.Thread,
                     error_holder: dict, what: str,
                     timeout: float = 30.0) -> None:
    """Block until the DB worker fills res_holder with a result.

    Replaces the old `while key not in res_holder: time.sleep(0.01)`
    busy-waits, which spun forever if the worker thread died.
    """
    deadline = time.monotonic() + timeout
    while not res_holder:
        _raise_if_worker_dead(worker, error_holder,
                              what=f"waiting for {what}")
        if time.monotonic() > deadline:
            raise DBWorkerError(
                f"Timed out after {timeout:.0f}s waiting for {what} - "
                "DB worker is unresponsive."
            )
        time.sleep(0.01)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="F1 2017/2018 Legacy UDP Telemetry Capture"
    )
    parser.add_argument(
        "--track",
        type=str,
        default="Sochi",
        help="Track name — matched against the tracks/track_aliases table "
             "(e.g. Spa, Monaco, Silverstone, Sochi).",
    )
    parser.add_argument(
        "--tyre",
        type=str,
        default="Ultrasoft",
        help=(
            "Starting tyre compound. Accepted values: "
            + ", ".join(sorted(TYRE_COMPOUND_MAP.values(), key=str))
        ),
    )
    parser.add_argument(
        "--weather",
        type=str,
        default="Dry",
        help="Weather conditions: Dry, Wet, Mixed, Rain, Clear, Cloudy, etc. "
             "Mapped to Dry / Wet / Mixed to match FastF1 import labels.",
    )
    parser.add_argument("--ip",   type=str, default=UDP_IP,   help="UDP listen IP")
    parser.add_argument("--port", type=int, default=UDP_PORT, help="UDP listen port")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main capture loop
# ---------------------------------------------------------------------------

def main() -> None:
    args = parse_args()

    # Normalise compound and weather using the same helpers as the FastF1 importer
    starting_tyre   = normalize_compound(args.tyre)
    weather_label   = normalise_weather(args.weather)
    raw_track_name  = args.track  # will be title-cased by get_or_create_track

    print("=" * 60)
    print("F1 TELEMETRY CAPTURE SYSTEM")
    print("=" * 60)
    print(f"  Track       : {raw_track_name}")
    print(f"  Tyre        : {starting_tyre}")
    print(f"  Weather     : {weather_label}")
    print(f"  Driver ID   : {GAME_DRIVER_ID}  (Player sentinel)")
    print("=" * 60)

    db_queue   = queue.Queue()
    stop_event = threading.Event()
    worker_error: dict = {}   # filled by db_worker with {"exc": ...} on death

    worker = threading.Thread(
        target=db_worker,
        args=(db_queue, stop_event, raw_track_name, worker_error),
        daemon=True,
    )
    worker.start()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.ip, args.port))
    sock.settimeout(1.0)
    print(f"[TELEMETRY] Listening on {args.ip}:{args.port}")
    print("[INFO] Start driving in F1 2018...")
    print("[INFO] Press Ctrl+C to stop\n")

    # ---- State ----
    current_session_id      = None
    current_lap_id          = None
    last_lap_number         = 0
    current_tyre_compound   = starting_tyre
    previous_tyre_compound  = starting_tyre
    tyre_age                = 0

    max_lap_time_seen   = 0.0
    lap_in_progress     = False
    lap_speed_samples: list[int]   = []   # full-lap speed samples → lap average
    recent_lap_times: list[int]    = []   # last ≤5 valid laps
    recent_avg_speeds: list[float] = []   # lap-average speed of last ≤5 valid laps
    saw_pit_flag        = False           # car seen in the pit area this lap
    packet_count        = 0
    telemetry_counter   = 0

    try:
        while True:
            try:
                data, _ = sock.recvfrom(2048)
            except socket.timeout:
                # Heartbeat: no packets for 1 s — cheap chance to notice the
                # worker died at startup (e.g. DB unreachable) instead of
                # idling forever.
                _raise_if_worker_dead(worker, worker_error)
                continue

            packet_count += 1
            parsed = parse_legacy_packet(data)
            if parsed is None:
                continue

            # Accumulate per-lap speed samples.  The lap-average is used for
            # SC/VSC/red-flag detection — a rolling window of the last ~2 s
            # (120 samples at 60 fps) is always finish-line speed, which made
            # SC and RedFlag undetectable.
            if parsed["speed"] > 0:
                lap_speed_samples.append(parsed["speed"])

            # Did the car enter the pit area during this lap?
            if parsed["in_pits"] >= 1:
                saw_pit_flag = True

            # Sync the live tyre-compound byte so compound changes (pit
            # stops) are detected.  Unknown bytes parse as None and are
            # ignored so garbage packets cannot fake a tyre change.
            live_compound = parsed["tyre_compound"]
            if live_compound is not None and live_compound != current_tyre_compound:
                current_tyre_compound = live_compound

            # ----------------------------------------------------------------
            # Create session + Lap 1 on the very first valid packet
            # ----------------------------------------------------------------
            if current_session_id is None:
                ses_res: dict = {}
                db_queue.put((
                    "insert_session",
                    "Race", weather_label, GAME_DRIVER_ID,
                    ses_res,
                ))
                _wait_for_result(ses_res, worker, worker_error,
                                 "session creation")
                current_session_id = ses_res["session_id"]

                last_lap_number = 1
                tyre_age        = 1
                lap_res: dict   = {}
                # In-progress laps are inserted with lap_time_ms=0 and
                # is_valid=0.  Only update_lap_time() (fired when the lap
                # completes) may mark a lap valid — so a capture that stops
                # mid-lap leaves a 0 ms lap that can never count as a fastest
                # lap or inflate averages.
                db_queue.put((
                    "insert_lap",
                    current_session_id, last_lap_number, 0,
                    current_tyre_compound, tyre_age,
                    estimate_fuel_load(last_lap_number),
                    False, GAME_DRIVER_ID, lap_res,
                ))
                _wait_for_result(lap_res, worker, worker_error,
                                 "lap 1 creation")
                current_lap_id = lap_res["lap_id"]
                print(f"[LAP START] Lap 1 in progress... (driver_id={GAME_DRIVER_ID})")

            # ----------------------------------------------------------------
            # Track lap timer
            # ----------------------------------------------------------------
            current_lap_time = parsed["current_lap_time"]
            if current_lap_time > 1.0:
                lap_in_progress = True
                if current_lap_time > max_lap_time_seen:
                    max_lap_time_seen = current_lap_time

            # ----------------------------------------------------------------
            # Lap completion detection: timer resets to near-zero
            # ----------------------------------------------------------------
            if lap_in_progress and current_lap_time < 1.0 and max_lap_time_seen > 10.0:
                lap_time_ms = int(max_lap_time_seen * 1000)
                is_valid    = MIN_VALID_LAP_MS <= lap_time_ms <= MAX_VALID_LAP_MS

                db_queue.put(("update_lap_time", current_lap_id, lap_time_ms, is_valid))

                lap_time_sec = lap_time_ms / 1000
                minutes = int(lap_time_sec // 60)
                seconds = lap_time_sec % 60
                status  = "[VALID]   " if is_valid else "[INVALID]"
                print(
                    f"{status} Lap {last_lap_number}: "
                    f"{minutes}:{seconds:06.3f} | "
                    f"{current_tyre_compound} (age {tyre_age}) | "
                    f"Fuel: {estimate_fuel_load(last_lap_number):.1f}kg"
                )

                # Expected lap time: rolling median of last ≤5 valid laps
                avg_speed_kmh = (
                    sum(lap_speed_samples) / len(lap_speed_samples)
                    if lap_speed_samples else 0.0
                )
                expected_lap_ms = 90_000  # fallback
                if len(recent_lap_times) >= 3:
                    sorted_times = sorted(recent_lap_times)
                    expected_lap_ms = sorted_times[len(sorted_times) // 2]
                # Expected lap-average speed: median of recent valid laps,
                # used as the track-relative SC/VSC/red-flag speed gate.
                expected_avg_speed_kmh = 0.0
                if len(recent_avg_speeds) >= 3:
                    sorted_speeds = sorted(recent_avg_speeds)
                    expected_avg_speed_kmh = sorted_speeds[len(sorted_speeds) // 2]

                if is_valid:
                    recent_lap_times.append(lap_time_ms)
                    if len(recent_lap_times) > 5:
                        recent_lap_times.pop(0)
                    if avg_speed_kmh > 0:
                        recent_avg_speeds.append(avg_speed_kmh)
                        if len(recent_avg_speeds) > 5:
                            recent_avg_speeds.pop(0)

                # ---- Strategy-event detection ----
                # A compound change on lap 1 just syncs the starting tyre
                # with what the game reports — not a pit stop.
                tyre_changed = (
                    current_tyre_compound != previous_tyre_compound
                    and last_lap_number > 1
                )
                events = detect_strategy_events(
                    lap_time_ms            = lap_time_ms,
                    tyre_changed           = tyre_changed,
                    saw_pit_flag           = saw_pit_flag,
                    avg_speed_kmh          = avg_speed_kmh,
                    expected_lap_ms        = expected_lap_ms,
                    recent_lap_ms_list     = list(recent_lap_times),
                    expected_avg_speed_kmh = expected_avg_speed_kmh,
                )
                for event_type, duration_sec in events:
                    # PitStop is driver-specific → link to lap_id.
                    # SC / VSC / RedFlag are session-wide → store with lap_id=None.
                    use_lap_id = current_lap_id if event_type == "PitStop" else None
                    db_queue.put((
                        "insert_strategy_event",
                        use_lap_id, event_type, duration_sec,
                    ))

                # Reset lap state
                previous_tyre_compound = current_tyre_compound
                lap_speed_samples      = []
                saw_pit_flag           = False
                max_lap_time_seen      = 0.0
                lap_in_progress        = False

                last_lap_number += 1
                if tyre_changed:
                    tyre_age = 1   # new stint starts on the pit-out lap
                else:
                    tyre_age += 1
                next_lap_res: dict = {}
                # Same as lap 1: in-progress lap is invalid until completed.
                db_queue.put((
                    "insert_lap",
                    current_session_id, last_lap_number, 0,
                    current_tyre_compound, tyre_age,
                    estimate_fuel_load(last_lap_number),
                    False, GAME_DRIVER_ID, next_lap_res,
                ))
                _wait_for_result(next_lap_res, worker, worker_error,
                                 f"lap {last_lap_number} creation")
                current_lap_id = next_lap_res["lap_id"]
                print(f"[LAP START] Lap {last_lap_number} in progress...")

            # ----------------------------------------------------------------
            # Telemetry sampling
            # ----------------------------------------------------------------
            telemetry_counter += 1
            if (telemetry_counter % TELEMETRY_SAMPLE_RATE == 0
                    and current_lap_id is not None):
                db_queue.put((
                    "insert_telemetry",
                    current_lap_id,
                    parsed["speed"], parsed["throttle"], parsed["brake"],
                    parsed["gear"], parsed["rpm"], parsed["drs"],
                ))

            if packet_count % 500 == 0:
                # Periodic liveness check: notice a mid-lap worker death (no
                # lap boundary to trip the wait-for-result checks) within
                # ~8 s at 60 fps instead of capturing into the void.
                _raise_if_worker_dead(worker, worker_error)
                print(
                    f"[STATUS] Packets: {packet_count} | "
                    f"Lap: {last_lap_number} | "
                    f"Time: {current_lap_time:.3f}s | "
                    f"Tyre: {current_tyre_compound}"
                )

    except KeyboardInterrupt:
        print("\n[STOP] Stopped by user")
    except Exception as exc:
        print(f"\n[ERROR] {exc}")
    finally:
        sock.close()
        stop_event.set()
        # Only join when the worker is alive: join() blocks until every task
        # is processed, which can never happen for a worker that already died
        # with items still in the queue.
        if worker.is_alive():
            db_queue.join()
        print("\n" + "=" * 60)
        print("TELEMETRY CAPTURE ENDED")
        print("=" * 60)
        print(f"  Total packets : {packet_count}")
        print(f"  Total laps    : {last_lap_number}")
        print("=" * 60)


if __name__ == "__main__":
    main()