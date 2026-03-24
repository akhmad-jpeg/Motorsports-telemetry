import fastf1
import mysql.connector
from datetime import datetime
import pandas as pd
import os

# Create cache directory if it doesn't exist
cache_dir = 'f1_cache'
if not os.path.exists(cache_dir):
    os.makedirs(cache_dir)
    print(f"[CACHE] Created cache directory: {cache_dir}")

# Enable caching
fastf1.Cache.enable_cache(cache_dir)

DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'password',
    'database': 'f1_strategy'
}

def import_race(year, race_name, session_type='R'):
    """
    Import F1 race data
    
    year: 2026
    race_name: 'China', 'Bahrain', 'Monaco', etc.
    session_type: 'R' (Race), 'Q' (Qualifying), 'FP1', 'FP2', 'FP3'
    """
    
    print("=" * 60)
    print("F1 RACE DATA IMPORT")
    print("=" * 60)
    print(f"Loading {year} {race_name} {session_type}...")
    
    try:
        # Load session
        session = fastf1.get_session(year, race_name, session_type)
        session.load()
        
        print(f"✓ Session loaded: {session.event['EventName']}")
    except Exception as e:
        print(f"\n[ERROR] Could not load session: {e}")
        print("\nPossible reasons:")
        print("- Race hasn't happened yet (data not available)")
        print("- Wrong race name (try: 'Bahrain', 'Saudi Arabia', 'Australia', etc.)")
        print("- Wrong year")
        return
    
    # Connect to database
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()
    
    # Create session
    track_name = session.event['Location']
    cursor.execute("""
        INSERT INTO sessions (track_name, session_type, weather, date)
        VALUES (%s, %s, %s, %s)
    """, (track_name, 'Race', 'Clear', session.event['EventDate'].date()))
    session_id = cursor.lastrowid
    conn.commit()
    
    print(f"✓ Database session created: ID={session_id}")
    
    # Get laps for a specific driver (or all drivers)
    print("\nAvailable drivers:")
    drivers = session.laps['Driver'].unique()
    for i, driver in enumerate(drivers, 1):
        print(f"{i}. {driver}")
    
    choice = input("\nDriver number (or 0 for all, ENTER for first driver): ").strip()
    
    if choice == '' or choice == '0':
        if choice == '0':
            laps = session.laps
            print("Importing ALL drivers...")
        else:
            selected_driver = drivers[0]
            laps = session.laps[session.laps['Driver'] == selected_driver]
            print(f"Importing {selected_driver}...")
    else:
        try:
            selected_driver = drivers[int(choice) - 1]
            laps = session.laps[session.laps['Driver'] == selected_driver]
            print(f"Importing {selected_driver}...")
        except:
            print("Invalid choice, importing first driver...")
            selected_driver = drivers[0]
            laps = session.laps[session.laps['Driver'] == selected_driver]
    
    # Import laps
    count = 0
    for idx, lap in laps.iterrows():
        try:
            driver = lap['Driver']
            lap_num = int(lap['LapNumber'])
            
            # Lap time
            if pd.notna(lap['LapTime']):
                lap_time_ms = int(lap['LapTime'].total_seconds() * 1000)
            else:
                continue  # Skip laps with no time
            
            # Tyre info
            compound = lap['Compound'] if pd.notna(lap['Compound']) else 'SOFT'
            tyre_life = int(lap['TyreLife']) if pd.notna(lap['TyreLife']) else 1
            
            # Insert lap
            cursor.execute("""
                INSERT INTO laps (session_id, lap_number, lap_time_ms, tyre_compound, tyre_age, fuel_load, is_valid)
                VALUES (%s, %s, %s, %s, %s, 100.0, 1)
            """, (session_id, lap_num, lap_time_ms, compound, tyre_life))
            
            lap_id = cursor.lastrowid
            count += 1
            
            # Check for pit stop
            if pd.notna(lap['PitOutTime']):
                cursor.execute("""
                    INSERT INTO strategy_events (lap_id, event_type, duration_sec)
                    VALUES (%s, 'PitStop', 24)
                """, (lap_id,))
            
            if count % 10 == 0:
                print(f"  Imported {count} laps...")
        
        except Exception as e:
            print(f"  Error on lap {lap_num}: {e}")
    
    conn.commit()
    cursor.close()
    conn.close()
    
    print(f"\n✓ Import complete: {count} laps imported!")
    print("=" * 60)

if __name__ == "__main__":
    print("\nF1 Race Data Importer")
    print("=" * 60)
    
    # Get user input
    year = input("Year (default 2024): ").strip() or "2024"
    year = int(year)
    
    print("\nPopular races:")
    print("  Bahrain, Saudi Arabia, Australia, Japan, China")
    print("  Miami, Monaco, Spain, Canada, Austria")
    print("  Britain, Hungary, Belgium, Netherlands, Italy")
    print("  Singapore, United States, Mexico, Brazil, Abu Dhabi")
    
    race = input("\nRace name (default 'Bahrain'): ").strip() or "Bahrain"
    
    print("\nSession types:")
    print("  R = Race, Q = Qualifying")
    print("  FP1, FP2, FP3 = Free Practice")
    
    session = input("Session type (default 'R'): ").strip() or "R"
    
    print("\n")
    
    # Import the race
    import_race(year, race, session)