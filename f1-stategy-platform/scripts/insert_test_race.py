import mysql.connector
from datetime import date

conn = mysql.connector.connect(
    host = "localhost",
    user = "root",
    password = "password",
    database = "f1_strategy"
)

cursor = conn.cursor()
print("Connected to SQL")

track = "Spa"
session_type = "Race"
weather = "Clear"
race_date = date(2024,9,1)

cursor.execute('''
               INSERT INTO sessions (track_name, session_type, weather, date)
               VALUES (%s, %s, %s, %s)
               ''', (track, session_type, weather, race_date))
session_id = cursor.lastrowid
print(f"Created session with ID: {session_id}")


laps_data = [
    # Stint 1 - Soft tyres, heavy fuel
    (1,  82450, 'Soft', 1, 95.0),    # Out-lap from grid 1:22.450
    (2,  81890, 'Soft', 2, 94.0),    # Fuel burn 
    (3,  81750, 'Soft', 3, 93.0),    # Peak performance
    (4,  81850, 'Soft', 4, 92.0),    # Slight deg
    (5,  82100, 'Soft', 5, 91.0),    # More deg
    
    # Pit stop on lap 6
    (6,  94500, 'Soft', 6, 90.0),    # IN-LAP: +12s pit lane
    (7,  94200, 'Medium', 1, 89.0),  # OUT-LAP: +12s, new mediums
    
    # Stint 2 - Medium tyres, lighter fuel
    (8,  81200, 'Medium', 2, 88.0),  # Back to pace, lighter car
    (9,  81150, 'Medium', 3, 87.0),  # Still quick
    (10, 81300, 'Medium', 4, 86.0),  # Slight deg
]

lap_ids = []
for lap_num, lap_time, compound, tyre_age, fuel in laps_data:
    cursor.execute("""
        INSERT INTO laps (session_id, lap_number, lap_time_ms, tyre_compound, tyre_age, fuel_load)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (session_id, lap_num, lap_time, compound, tyre_age, fuel))
    
    lap_ids.append(cursor.lastrowid)
    print(f"Inserted lap {lap_num}")

# Insert telemetry for each lap (simplified: 1 data point per lap)
for i, lap_id in enumerate(lap_ids):
    speed = 315 + (i * 2)  # Speed increases slightly (fuel burn)
    throttle = 0.95 - (i * 0.01) #Throttle decreases slightly (tyre deg)
    brake = 0.0
    gear = 8
    rpm = 11000 - (i * 50) #RPMs drop slightly you dont go flatout everytime everywhere
    drs = True if i > 0 else False  # DRS available after lap 1
    
    cursor.execute("""
        INSERT INTO telemetry (lap_id, speed, throttle, brake, gear, rpm, drs)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (lap_id, speed, throttle, brake, gear, rpm, drs))

print("Inserted telemetry for all laps")

cursor.execute("""
    INSERT INTO strategy_events (lap_id, event_type, duration_sec)
    VALUES (%s, %s, %s)
""", (lap_ids[2], 'PitStop', 2.3))  # lap_ids[2] = lap 3

print("Inserted pit stop event")

conn.commit()

# Close connection
cursor.close()
conn.close()

print("Test race inserted successfully!")