import joblib
import pandas as pd
import numpy as np
import os

print("=" * 60)
print("F1 LAP TIME PREDICTOR")
print("=" * 60)

# Check if model exists
if not os.path.exists('ml_models/best_model.pkl'):
    print("\n[ERROR] Model not found!")
    print("Run this first: python scripts/ml_lap_prediction.py")
    exit()

# Load the trained model
model = joblib.load('ml_models/best_model.pkl')
feature_names = joblib.load('ml_models/feature_names.pkl')

print("\n✓ Model loaded successfully!")
print(f"✓ Model type: {type(model).__name__}")
print(f"✓ Features: {len(feature_names)}\n")

# Extract available tyres and tracks from feature names
available_tyres = []
available_tracks = []

for feature in feature_names:
    if feature.startswith('tyre_'):
        tyre = feature.replace('tyre_', '')
        if tyre not in ['age', 'load']:
            available_tyres.append(tyre)
    elif feature.startswith('track_'):
        track = feature.replace('track_', '')
        available_tracks.append(track)

print("=" * 60)
print("MAKE A PREDICTION")
print("=" * 60)

# Get user input
print("\nEnter race conditions:")
tyre_age = int(input("Tyre age (laps): "))
fuel_load = float(input("Fuel load (kg): "))

print("\n" + "=" * 60)
print("TYRE COMPOUND SELECTION")
print("=" * 60)
print("\nAvailable tyre compounds (based on your training data):")

for i, tyre in enumerate(available_tyres, 1):
    if tyre in ['Hypersoft', 'Ultrasoft', 'Supersoft', 'Soft', 'Medium', 'Hard']:
        tyre_type = "DRY"
    elif tyre in ['Intermediate']:
        tyre_type = "WET (Light Rain)"
    elif tyre in ['Wet']:
        tyre_type = "WET (Heavy Rain)"
    else:
        tyre_type = "UNKNOWN"

    print(f"  {i}. {tyre:15s} [{tyre_type}]")

print("\n Note: Only tyres you've driven on are available")
print("   To add wet tyres, drive laps in wet conditions and retrain")
print("=" * 60)

while True:
    try:
        tyre_choice = int(input("\nSelect tyre compound: "))
        if 1 <= tyre_choice <= len(available_tyres):
            break
        else:
            print(f"   Enter a number between 1 and {len(available_tyres)}")
    except ValueError:
        print("   Please enter a number, not text")

tyre_compound = available_tyres[tyre_choice - 1]

print("\n" + "=" * 60)
print("TRACK SELECTION")
print("=" * 60)
print("\nAvailable tracks (based on your training data):")

for i, track in enumerate(available_tracks, 1):
    print(f"  {i}. {track.title()}")

print("=" * 60)

while True:
    try:
        track_choice = int(input("\nSelect track: "))
        if 1 <= track_choice <= len(available_tracks):
            break
        else:
            print(f"   Enter a number between 1 and {len(available_tracks)}")
    except ValueError:
        print("   Please enter a number, not text")

track_name = available_tracks[track_choice - 1]

# Create input DataFrame with ALL features from training
input_data = pd.DataFrame(0, index=[0], columns=feature_names)

# Set the numeric features
input_data['tyre_age'] = tyre_age
input_data['fuel_load'] = fuel_load

# Set the correct tyre compound to 1
tyre_feature = f'tyre_{tyre_compound}'
input_data[tyre_feature] = 1

# Set the correct track to 1
track_feature = f'track_{track_name}'
input_data[track_feature] = 1

# Make prediction
predicted_time = model.predict(input_data)[0]

# Convert to minutes:seconds
minutes = int(predicted_time // 60)
seconds = predicted_time % 60

print("\n" + "=" * 60)
print("PREDICTION RESULT")
print("=" * 60)
print(f"\nRace Conditions:")
print(f"  Track:        {track_name.title()}")
print(f"  Tyre:         {tyre_compound} (age {tyre_age})")
print(f"  Fuel:         {fuel_load:.1f} kg")
print(f"\nPredicted Lap Time:")
print(f"  {minutes}:{seconds:06.3f}")
print(f"  ({predicted_time:.3f} seconds)")

# Add interpretation for wet tyres
if tyre_compound in ['Intermediate', 'Wet']:
    print(f"\n💧 Weather Prediction:")
    print(f"  This is a {tyre_compound} tyre prediction")
    if tyre_compound == 'Wet':
        print(f"  Expected conditions: Heavy rain")
    else:
        print(f"  Expected conditions: Light rain or drying track")

print("=" * 60)