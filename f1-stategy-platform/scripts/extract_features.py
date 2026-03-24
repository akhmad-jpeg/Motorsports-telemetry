import joblib
import mysql.connector
import pandas as pd

print("=" * 60)
print("EXTRACTING FEATURE NAMES FROM MODEL")
print("=" * 60)

# Connect to database
conn = mysql.connector.connect(
    host='localhost',
    user='root',
    password='password',
    database='f1_strategy'
)

# Load training data (same as ml_lap_prediction.py)
query = """
SELECT 
    l.lap_time_ms / 1000 as lap_time,
    l.tyre_age,
    l.fuel_load,
    l.tyre_compound,
    s.track_name
FROM laps l
JOIN sessions s ON l.session_id = s.session_id
WHERE l.is_valid = 1 
AND l.lap_time_ms BETWEEN 60000 AND 180000
"""

df = pd.read_sql(query, conn)
conn.close()

print(f"\n[DATA] Loaded {len(df)} laps")

# One-hot encode ONLY tyre_compound and track_name
df_encoded = pd.get_dummies(df, columns=['tyre_compound', 'track_name'], prefix=['tyre', 'track'])

# Get feature names (everything except lap_time)
feature_cols = [col for col in df_encoded.columns if col != 'lap_time']

print(f"[FEATURES] Found {len(feature_cols)} features")
print("\nFeature list:")
for i, feat in enumerate(feature_cols, 1):
    print(f"  {i}. {feat}")

# Save feature names
joblib.dump(feature_cols, 'ml_models/feature_names.pkl')
print(f"\n✓ Saved feature_names.pkl")
print("=" * 60)