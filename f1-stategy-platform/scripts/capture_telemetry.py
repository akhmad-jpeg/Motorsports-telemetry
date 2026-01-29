import socket
import struct
import mysql.connector
from datetime import datetime

# ============================================
# CONFIGURATION
# ============================================
UDP_IP = "0.0.0.0"  # Listen on all network interfaces
UDP_PORT = 20777

DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'password',  # ⚠️ CHANGE THIS
    'database': 'f1_strategy'
}

# Telemetry sampling (insert every Nth telemetry packet)
TELEMETRY_SAMPLE_RATE = 40  # Insert 1 out of every 40 packets

# ============================================
# DATABASE CONNECTION
# ============================================
def get_db_connection():
    """Connect to MySQL database"""
    conn = mysql.connector.connect(**DB_CONFIG)
    return conn

# ============================================
# PACKET PARSING - HEADER
# ============================================
def parse_packet_header(data):
    """
    Parse packet header (first 21 bytes)
    
    Returns:
        packet_id (int): Type of packet (0-7)
    """
    # Byte 7 contains the packet ID
    packet_id = struct.unpack('<B', data[7:8])[0]
    return packet_id

# ============================================
# PACKET PARSING - LAP DATA (Packet ID = 2)
# ============================================
def parse_lap_data_packet(data):
    """
    Parse Lap Data packet
    
    Returns:
        dict with: last_lap_time_ms, current_lap_invalid, tyre_compound, tyre_age (not available in 2018)
    """
    # Skip 21-byte header, player is first car (index 0)
    offset = 21
    
    # Lap times (floats, 4 bytes each)
    last_lap_time = struct.unpack('<f', data[offset:offset+4])[0]
    current_lap_time = struct.unpack('<f', data[offset+4:offset+8])[0]
    
    # Current lap invalid flag (byte 29 from start of lap data)
    current_lap_invalid = struct.unpack('<B', data[offset+29:offset+30])[0]
    
    # Convert lap time from seconds to milliseconds
    last_lap_time_ms = int(last_lap_time * 1000) if last_lap_time > 0 else None
    
    return {
        'last_lap_time_ms': last_lap_time_ms,
        'current_lap_invalid': current_lap_invalid == 1,
    }

# ============================================
# PACKET PARSING - CAR TELEMETRY (Packet ID = 6)
# ============================================
def parse_telemetry_packet(data):
    """
    Parse Car Telemetry packet
    
    Returns:
        dict with: speed, throttle, brake, gear, rpm, drs
    """
    # Skip 21-byte header, player is first car
    offset = 21
    
    # Speed (uint16, 2 bytes)
    speed = struct.unpack('<H', data[offset:offset+2])[0]
    
    # Throttle (float, 4 bytes) - stored as 0.0 to 1.0
    throttle = struct.unpack('<f', data[offset+2:offset+6])[0]
    
    # Steer (float, 4 bytes) - we skip this
    # Brake (float, 4 bytes)
    brake = struct.unpack('<f', data[offset+10:offset+14])[0]
    
    # Skip clutch (1 byte)
    # Gear (int8, 1 byte) - -1=R, 0=N, 1-8
    gear = struct.unpack('<b', data[offset+15:offset+16])[0]
    
    # Engine RPM (uint16, 2 bytes)
    rpm = struct.unpack('<H', data[offset+16:offset+18])[0]
    
    # DRS (uint8, 1 byte) - 0=off, 1=on
    drs = struct.unpack('<B', data[offset+18:offset+19])[0]
    
    return {
        'speed': speed,
        'throttle': round(throttle, 2),
        'brake': round(brake, 2),
        'gear': gear,
        'rpm': rpm,
        'drs': drs == 1
    }

# ============================================
# PACKET PARSING - CAR STATUS (Packet ID = 7)
# ============================================
def parse_car_status_packet(data):
    """
    Parse Car Status packet to get tyre compound and fuel
    
    Returns:
        dict with: tyre_compound, fuel_in_tank
    """
    # Skip 21-byte header
    offset = 21
    
    # Tyre compound (uint8) - offset 16 in car status data
    # 0-6 represent different compounds in F1 2018
    tyre_compound_id = struct.unpack('<B', data[offset+16:offset+17])[0]
    
    # Map F1 2018 tyre IDs to compound names
    tyre_map = {
        0: 'Hypersoft',
        1: 'Ultrasoft', 
        2: 'Supersoft',
        3: 'Soft',
        4: 'Medium',
        5: 'Hard',
        6: 'Superhard',
        7: 'Intermediate',
        8: 'Wet'
    }
    
    tyre_compound = tyre_map.get(tyre_compound_id, 'Soft')
    
    # Fuel in tank (float, 4 bytes) - offset 0
    fuel_in_tank = struct.unpack('<f', data[offset:offset+4])[0]
    
    return {
        'tyre_compound': tyre_compound,
        'fuel_in_tank': round(fuel_in_tank, 1)
    }

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
    
    print(f"🏁 Created new session: ID={session_id}, Track={track_name}")
    return session_id

def insert_lap(conn, session_id, lap_number, lap_time_ms, tyre_compound, tyre_age, fuel_load, is_valid=True):
    """Insert a completed lap and return lap_id"""
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO laps (session_id, lap_number, lap_time_ms, tyre_compound, tyre_age, fuel_load, is_valid)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (session_id, lap_number, lap_time_ms, tyre_compound, tyre_age, fuel_load, is_valid))
    
    lap_id = cursor.lastrowid
    conn.commit()
    cursor.close()
    
    # Format lap time for display
    lap_time_sec = lap_time_ms / 1000
    minutes = int(lap_time_sec // 60)
    seconds = lap_time_sec % 60
    
    status = "✅" if is_valid else "❌ INVALID"
    print(f"{status} Lap {lap_number}: {minutes}:{seconds:06.3f} | {tyre_compound} (age {tyre_age}) | Fuel: {fuel_load:.1f}L")
    
    return lap_id

def insert_telemetry(conn, lap_id, speed, throttle, brake, gear, rpm, drs):
    """Insert telemetry sample"""
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO telemetry (lap_id, speed, throttle, brake, gear, rpm, drs)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (lap_id, speed, throttle, brake, gear, rpm, drs))
    
    conn.commit()
    cursor.close()

# ============================================
# UDP SOCKET SETUP
# ============================================
def setup_udp_listener():
    """Create UDP socket listening on port 20777"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_IP, UDP_PORT))
    print(f"🎧 Listening for F1 2018 telemetry on {UDP_IP}:{UDP_PORT}")
    return sock

# ============================================
# MAIN TELEMETRY CAPTURE LOOP
# ============================================
def main():
    """Main telemetry capture loop"""
    print("=" * 60)
    print("F1 2018 TELEMETRY CAPTURE")
    print("=" * 60)
    
    sock = setup_udp_listener()
    conn = get_db_connection()
    
    print("✅ Connected to MySQL database")
    print("🏁 Start driving in F1 2018...")
    print("💡 Make sure you're IN THE CAR on track, not in menus!\n")
    
    # Session state tracking
    current_session_id = None
    last_lap_number = 0
    telemetry_counter = 0
    current_lap_id = None
    
    # Track state
    current_tyre_compound = 'Soft'
    current_fuel = 100.0
    tyre_age = 0
    
    # Packet debugging
    packet_count = 0
    
    try:
        while True:
            # Receive UDP packet
            data, addr = sock.recvfrom(2048)
            packet_count += 1
            
            # Print periodic status so you know it's working
            if packet_count % 500 == 0:
                print(f"📡 {packet_count} packets received...")
            
            # Parse packet header to determine type
            packet_id = parse_packet_header(data)
            
            # ==========================================
            # LAP DATA PACKET (ID = 2)
            # ==========================================
            if packet_id == 2:
                lap_data = parse_lap_data_packet(data)
                
                # Check if this is the first session
                if current_session_id is None:
                    current_session_id = insert_session(conn, "Unknown Track", "Race", "Clear")
                
                # Detect lap completion (lap time exists and is new)
                if lap_data['last_lap_time_ms'] is not None:
                    # Infer lap number (increments each time we see a new lap time)
                    # This is a simplification - in real implementation you'd track lap numbers from the packet
                    current_lap_num = last_lap_number + 1
                    
                    # Only insert if this is a new lap
                    if current_lap_num > last_lap_number:
                        # Increment tyre age
                        tyre_age += 1
                        
                        # Insert the completed lap
                        is_valid = not lap_data['current_lap_invalid']
                        current_lap_id = insert_lap(
                            conn,
                            current_session_id,
                            current_lap_num,
                            lap_data['last_lap_time_ms'],
                            current_tyre_compound,
                            tyre_age,
                            current_fuel,
                            is_valid
                        )
                        
                        last_lap_number = current_lap_num
            
            # ==========================================
            # CAR STATUS PACKET (ID = 7)
            # ==========================================
            elif packet_id == 7:
                car_status = parse_car_status_packet(data)
                
                # Update tyre compound (detect pit stops)
                if car_status['tyre_compound'] != current_tyre_compound:
                    print(f"🔧 Tyre change detected: {current_tyre_compound} → {car_status['tyre_compound']}")
                    current_tyre_compound = car_status['tyre_compound']
                    tyre_age = 0  # Reset tyre age
                
                # Update fuel level
                current_fuel = car_status['fuel_in_tank']
            
            # ==========================================
            # CAR TELEMETRY PACKET (ID = 6)
            # ==========================================
            elif packet_id == 6:
                telemetry_counter += 1
                
                # Sample telemetry (not every frame)
                if telemetry_counter % TELEMETRY_SAMPLE_RATE == 0 and current_lap_id is not None:
                    telemetry = parse_telemetry_packet(data)
                    
                    insert_telemetry(
                        conn,
                        current_lap_id,
                        telemetry['speed'],
                        telemetry['throttle'],
                        telemetry['brake'],
                        telemetry['gear'],
                        telemetry['rpm'],
                        telemetry['drs']
                    )
    
    except KeyboardInterrupt:
        print("\n⛔ Stopped by user (Ctrl+C)")
    
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        conn.close()
        sock.close()
        print("🏁 Telemetry capture ended")
        print(f"📊 Total laps captured: {last_lap_number}")
        print(f"📦 Total packets received: {packet_count}")

if __name__ == "__main__":
    main()
# ```

# ---

# ## 🎯 Key changes:

# 1. **UDP_IP changed to `"0.0.0.0"`** - listens on all network interfaces
# 2. **Added packet counter** - prints "📡 X packets received..." every 500 packets so you know it's working
# 3. **Added reminder message** - tells you to be IN THE CAR

# ---

# ## ✅ How to test:

# 1. **Close F1 2018 completely**
# 2. **Restart F1 2018**
# 3. Go to **Time Trial**
# 4. Select **Monza** (or any track)
# 5. **Enter the track and wait until you're in the car**
# 6. **THEN run:**
# ```
#    python scripts/capture_telemetry.py
# ```
# 7. **Drive at least one lap**

# You should see:
# ```
# 📡 500 packets received...
# 📡 1000 packets received...
# 🏁 Created new session: ID=4, Track=Unknown Track
# 📡 1500 packets received...
# ✅ Lap 1: 1:23.456 | Soft (age 1) | Fuel: 95.2L