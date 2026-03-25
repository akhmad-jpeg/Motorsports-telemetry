import mysql.connector

DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'password',
    'database': 'f1_strategy'
}

def clean_unknown_tracks():
    """Remove sessions with 'Unknown Track' from database"""
    
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()
    
    print("=" * 60)
    print("DATABASE CLEANUP")
    print("=" * 60)
    
    # Find sessions with unknown track
    cursor.execute("""
        SELECT session_id, track_name, date, session_type
        FROM sessions
        WHERE track_name LIKE '%unknown%' OR track_name LIKE '%Unknown%'
    """)
    
    sessions_to_delete = cursor.fetchall()
    
    if not sessions_to_delete:
        print("\n✓ No 'Unknown Track' sessions found!")
        cursor.close()
        conn.close()
        return
    
    print(f"\nFound {len(sessions_to_delete)} session(s) with unknown track:")
    for session_id, track_name, date, session_type in sessions_to_delete:
        print(f"  Session {session_id}: {track_name} ({session_type}) on {date}")
    
    confirm = input("\nDelete these sessions? (yes/no): ").strip().lower()
    
    if confirm != 'yes':
        print("\n[CANCELLED] No changes made.")
        cursor.close()
        conn.close()
        return
    
    # Delete in correct order (child tables first, then parent)
    for session_id, _, _, _ in sessions_to_delete:
        # Get all lap IDs for this session
        cursor.execute("SELECT lap_id FROM laps WHERE session_id = %s", (session_id,))
        lap_ids = [row[0] for row in cursor.fetchall()]
        
        # Delete telemetry data
        if lap_ids:
            cursor.execute(f"DELETE FROM telemetry WHERE lap_id IN ({','.join(['%s']*len(lap_ids))})", lap_ids)
            print(f"  ✓ Deleted telemetry for session {session_id}")
            
            # Delete strategy events
            cursor.execute(f"DELETE FROM strategy_events WHERE lap_id IN ({','.join(['%s']*len(lap_ids))})", lap_ids)
            print(f"  ✓ Deleted strategy events for session {session_id}")
        
        # Delete laps
        cursor.execute("DELETE FROM laps WHERE session_id = %s", (session_id,))
        print(f"  ✓ Deleted laps for session {session_id}")
        
        # Finally delete the session
        cursor.execute("DELETE FROM sessions WHERE session_id = %s", (session_id,))
        print(f"  ✓ Deleted session {session_id}")
    
    conn.commit()
    cursor.close()
    conn.close()
    
    print("\n✓ Cleanup complete!")
    print("=" * 60)

def view_all_sessions():
    """View all sessions in database"""
    
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()
    
    print("\n" + "=" * 60)
    print("ALL SESSIONS IN DATABASE")
    print("=" * 60)
    
    cursor.execute("""
        SELECT 
            s.session_id,
            s.track_name,
            s.date,
            COUNT(l.lap_id) as total_laps
        FROM sessions s
        LEFT JOIN laps l ON s.session_id = l.session_id
        GROUP BY s.session_id
        ORDER BY s.date DESC
    """)
    
    sessions = cursor.fetchall()
    
    if not sessions:
        print("\nNo sessions found.")
    else:
        print(f"\nTotal sessions: {len(sessions)}\n")
        print(f"{'ID':<5} {'Track':<20} {'Date':<12} {'Laps':<6}")
        print("-" * 60)
        for session_id, track_name, date, total_laps in sessions:
            print(f"{session_id:<5} {track_name:<20} {str(date):<12} {total_laps:<6}")
    
    cursor.close()
    conn.close()
    print("=" * 60)

def fix_track_names():
    """Standardize track names (fix capitalization)"""
    
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()
    
    print("=" * 60)
    print("STANDARDIZING TRACK NAMES")
    print("=" * 60)
    
    # Fix common issues
    fixes = {
        'spa': 'Spa',
        'SPA': 'Spa',
        'monaco': 'Monaco',
        'MONACO': 'Monaco',
        'silverstone': 'Silverstone',
        'jeddah': 'Jeddah',
        'china': 'China',
        'canada': 'Canada',
        'mexico': 'Mexico'
    }
    
    for old_name, new_name in fixes.items():
        cursor.execute("""
            UPDATE sessions 
            SET track_name = %s 
            WHERE LOWER(track_name) = %s
        """, (new_name, old_name.lower()))
        
        if cursor.rowcount > 0:
            print(f"  ✓ Updated '{old_name}' → '{new_name}' ({cursor.rowcount} sessions)")
    
    conn.commit()
    cursor.close()
    conn.close()
    
    print("\n✓ Track names standardized!")
    print("=" * 60)

if __name__ == "__main__":
    print("\nDatabase Cleanup Tool")
    print("=" * 60)
    print("1. View all sessions")
    print("2. Remove 'Unknown Track' sessions")
    print("3. Fix track names (standardize capitalization)")
    print("4. Exit")
    
    choice = input("\nSelect option: ").strip()
    
    if choice == "1":
        view_all_sessions()
    elif choice == "2":
        clean_unknown_tracks()
    elif choice == "3":
        fix_track_names()
    else:
        print("\nExiting...")
