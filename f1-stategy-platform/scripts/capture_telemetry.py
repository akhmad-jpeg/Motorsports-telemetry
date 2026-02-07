import socket
import struct
import mysql.connector
from datetime import datetime

# ============================================
# MANUAL CONFIGURATION (MODIFIED BY start_capture.bat)
# ============================================
TRACK_NAME = "spa"
STARTING_TYRE = "supersoft"
WEATHER = "clear"

# ============================================
# DATABASE CONFIGURATION
# ============================================
UDP_IP = "0.0.0.0"
UDP_PORT = 20777

DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'password',
    'database': 'f1_strategy'
}

TELEMETRY_SAMPLE_RATE = 60  # Sample every 60th packet (1 sample per second)

# Lap time validation
MIN_VALID_LAP_TIME_MS = 60000   # 60 seconds minimum
MAX_VALID_LAP_TIME_MS = 180000  # 3 minutes maximum

# ============================================
# DATABASE CONNECTION
# ============================================
def get_db_connection():
    """Connect to MySQL database"""
    conn = mysql.connector.connect(**DB_CONFIG)
    return conn

# ============================================
# F1 2017 LEGACY PACKET PARSING
# ============================================
def parse_legacy_packet(data):
    """
    Parse F1 2017 Legacy format packet (1289 bytes)
    
    Extracts:
    - Lap time (RELIABLE)
    - Speed (RELIABLE)
    - Telemetry (BEST EFFORT - noisy but shows patterns)
    """
    
    offset = 0
    
    try:
        # Current lap time (bytes 4-7) - RELIABLE
        current_lap_time = struct.unpack('<f', data[offset+4:offset+8])[0]
        
        # Speed (bytes 28-31) - RELIABLE
        speed = struct.unpack('<f', data[offset+28:offset+32])[0]
        
        # === TELEMETRY (BEST EFFORT) ===
        telem_offset = 52
        
        try:
            # Throttle (float, 0.0 to 1.0)
            throttle_raw = struct.unpack('<f', data[telem_offset:telem_offset+4])[0]
            throttle = max(0.0, min(1.0, throttle_raw))
            
            # Brake (float, 0.0 to 1.0)
            brake_raw = struct.unpack('<f', data[telem_offset+8:telem_offset+12])[0]
            brake = max(0.0, min(1.0, brake_raw))
            
            # Gear (int8) - will be noisy
            gear_raw = struct.unpack('<b', data[telem_offset+20:telem_offset+21])[0]
            gear = max(-1, min(8, gear_raw))
            
            # Engine RPM (uint16)
            rpm_raw = struct.unpack('<H', data[telem_offset+21:telem_offset+23])[0]
            rpm = max(0, min(15000, rpm_raw))
            
            # DRS (uint8)
            drs_raw = struct.unpack('<B', data[telem_offset+23:telem_offset+24])[0]
            drs = drs_raw == 1
            
        except:
            # If telemetry extraction fails, use defaults
            throttle = 0.0
            brake = 0.0
            gear = 0
            rpm = 0
            drs = False
        
        return {
            'current_lap_time': current_lap_time,
            'speed': int(max(0, min(400, speed))),
            'throttle': round(throttle, 2),
            'brake': round(brake, 2),
            'gear': gear,
            'rpm': rpm,
            'drs': drs,
        }
    
    except Exception as e:
        return None

# ============================================
# DATABASE INSERTION
# ============================================
def insert_session(conn, track_name, session_type, weather):
    """Insert a new session and return session_id"""
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO sessions (track_name, session_type, weather, date)
        VALUES (%s, %s, %s, %s)
    """, (track_name, session_type, weather, datetime.now().date()))
    
    session_id = cursor.lastrowid
    conn.commit()
    cursor.close()
    
    print(f"[SESSION] Created ID={session_id}, Track={track_name}")
    return session_id

def insert_lap(conn, session_id, lap_number, lap_time_ms, tyre_compound, tyre_age, fuel_load, is_valid=True):
    """Insert a completed lap and return lap_id"""
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO laps (session_id, lap_number, lap_time_ms, tyre_compound, tyre_age, fuel_load, is_valid)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (session_id, lap_number, lap_time_ms, tyre_compound, tyre_age, fuel_load, 1 if is_valid else 0))
    
    lap_id = cursor.lastrowid
    conn.commit()
    cursor.close()
    
    # Format lap time for display
    lap_time_sec = lap_time_ms / 1000
    minutes = int(lap_time_sec // 60)
    seconds = lap_time_sec % 60
    
    # Display status
    status = "[VALID]   " if is_valid else "[INVALID]"
    
    print(f"{status} Lap {lap_number}: {minutes}:{seconds:06.3f} | {tyre_compound} (age {tyre_age}) | Fuel: {fuel_load:.1f}L")
    
    return lap_id

def insert_telemetry(conn, lap_id, speed, throttle, brake, gear, rpm, drs):
    """Insert telemetry sample"""
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO telemetry (lap_id, speed, throttle, brake, gear, rpm, drs)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (lap_id, speed, throttle, brake, gear, rpm, 1 if drs else 0))
    
    conn.commit()
    cursor.close()

# ============================================
# UDP SOCKET SETUP
# ============================================
def setup_udp_listener():
    """Create UDP socket listening on port 20777"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_IP, UDP_PORT))
    print(f"[TELEMETRY] Listening on {UDP_IP}:{UDP_PORT}")
    return sock

# ============================================
# MAIN TELEMETRY CAPTURE LOOP
# ============================================
def main():
    """Main telemetry capture loop for F1 2017 Legacy format"""
    print("=" * 60)
    print("F1 TELEMETRY CAPTURE SYSTEM")
    print("=" * 60)
    print(f"Track:   {TRACK_NAME}")
    print(f"Tyres:   {STARTING_TYRE}")
    print(f"Weather: {WEATHER}")
    print("=" * 60)
    
    sock = setup_udp_listener()
    conn = get_db_connection()
    
    print("[DATABASE] Connected to MySQL")
    print("[INFO] Make sure F1 2018 UDP format is set to 'Legacy'")
    print("[INFO] Start driving in F1 2018...")
    print("[INFO] Press Ctrl+C to stop\n")
    
    # Session state
    current_session_id = None
    current_lap_id = None
    last_lap_number = 0
    
    # Track state (use manual configuration)
    current_tyre_compound = STARTING_TYRE
    current_fuel = 100.0
    tyre_age = 0
    
    # Lap tracking
    previous_lap_time = 0.0
    max_lap_time_seen = 0.0
    lap_in_progress = False
    
    # Telemetry sampling
    packet_count = 0
    telemetry_counter = 0
    
    try:
        while True:
            data, addr = sock.recvfrom(2048)
            packet_count += 1
            
            # Parse legacy packet
            parsed = parse_legacy_packet(data)
            
            if parsed is None:
                continue
            
            # Create session on first packet
            if current_session_id is None:
                current_session_id = insert_session(conn, TRACK_NAME, "Race", WEATHER)
                current_lap_id = insert_lap(conn, current_session_id, 1, 90000, current_tyre_compound, 1, current_fuel, True)
                last_lap_number = 1
                tyre_age = 1
                print("")
            
            current_lap_time = parsed['current_lap_time']
            
            # Lap is in progress
            if current_lap_time > 1.0:
                lap_in_progress = True
                if current_lap_time > max_lap_time_seen:
                    max_lap_time_seen = current_lap_time
            
            # Detect lap completion: current_lap_time drops to near zero
            if lap_in_progress and current_lap_time < 1.0 and max_lap_time_seen > 10.0:
                # Lap just completed
                lap_time_ms = int(max_lap_time_seen * 1000)
                
                # Validate lap time
                is_valid = True
                
                if lap_time_ms < MIN_VALID_LAP_TIME_MS:
                    is_valid = False
                elif lap_time_ms > MAX_VALID_LAP_TIME_MS:
                    is_valid = False
                
                # Insert lap
                last_lap_number += 1
                tyre_age += 1
                
                current_lap_id = insert_lap(
                    conn,
                    current_session_id,
                    last_lap_number,
                    lap_time_ms,
                    current_tyre_compound,
                    tyre_age,
                    current_fuel,
                    is_valid
                )
                
                # Reset for next lap
                max_lap_time_seen = 0.0
                lap_in_progress = False
            
            previous_lap_time = current_lap_time
            
            # Sample telemetry
            telemetry_counter += 1
            if telemetry_counter % TELEMETRY_SAMPLE_RATE == 0 and current_lap_id is not None:
                insert_telemetry(
                    conn,
                    current_lap_id,
                    parsed['speed'],
                    parsed['throttle'],
                    parsed['brake'],
                    parsed['gear'],
                    parsed['rpm'],
                    parsed['drs']
                )
            
            # Status updates
            if packet_count % 500 == 0:
                print(f"[STATUS] Packets: {packet_count} | Lap: {last_lap_number} | Time: {current_lap_time:.3f}s | Tyre: {current_tyre_compound}")
    
    except KeyboardInterrupt:
        print("\n[STOP] Stopped by user")
    
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        conn.close()
        sock.close()
        print("\n" + "=" * 60)
        print("TELEMETRY CAPTURE ENDED")
        print("=" * 60)
        print(f"Total packets: {packet_count}")
        print(f"Total laps captured: {last_lap_number}")
        print(f"Track: {TRACK_NAME}")

if __name__ == "__main__":
    main()
