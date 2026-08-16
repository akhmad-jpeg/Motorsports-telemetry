# F1 Race Strategy & Telemetry Analytics Platform

An academic F1 telemetry platform that captures F1 2018 **Legacy UDP** packets, stores lap and sampled telemetry data in MySQL, trains a lap-time model, and serves a local Flask dashboard.

## What is included

- `scripts/capture_telemetry.py` — live UDP capture on port `20777`
- `scripts/import_f1_race.py` — historical FastF1 session import
- `scripts/analyze_performance.py` — performance charts and reports
- `scripts/ml_lap_predictions.py` — model training and artifact generation
- `scripts/dashboard.py` — local Flask API and dashboard
- `scripts/config.py` — central database configuration and environment variables
- `scripts/templates/dashboard.html` — dashboard UI
- `database/schema.sql` — MySQL schema

## Prerequisites

- Python 3.10+
- MySQL 8+
- F1 2018 with UDP telemetry set to **Legacy** and port `20777` for live capture

## Setup

1. Create and activate a virtual environment.

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

2. Install dependencies.

   ```powershell
   pip install -r requirements.txt
   ```

3. Create the MySQL schema.

   ```powershell
   mysql -u root -p < database\schema.sql
   ```

4. Configure database credentials. Override defaults using environment variables (`DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`, `DB_PORT`) or edit `scripts/config.py`. Do not commit secret credentials.

## Running the platform

Run every command from the repository root.

```powershell
# Capture F1 2018 Legacy UDP telemetry
scripts\start_telemetry.bat

# Or import historical FastF1 data
python scripts\import_f1_race.py

# Train the model; this creates ml_models\best_model.pkl and feature_names.pkl
python scripts\ml_lap_predictions.py

# Start the local dashboard at http://localhost:5000
python scripts\dashboard.py
```

The model artifacts, FastF1 cache, and analysis charts are generated locally and intentionally excluded from Git. Train a model before using prediction endpoints.

## Fuel-load feature

F1 2018 Legacy UDP does not expose fuel mass. The platform derives an estimated fuel load as `max(0, 110 - lap_number * 2)` kg and stores it per lap, but it is **not** used as a model feature: it is a deterministic function of `lap_number` and therefore perfectly collinear with `tyre_age` inside every stint, which destabilised the linear coefficients (the old model "predicted" laps get faster as tyres age). `tyre_age` alone carries the within-stint pace progression.

The lap-time model is trained only on representative green-flag racing laps: invalid laps, pit in/out-laps, the first two laps of every stint (cold-tyre/race-start traffic), and SC/VSC/red-flag laps are all excluded. It covers the tracks in `ml_models/model_info.json` — the predictor and dashboard reject any other track with a clear error listing the covered tracks.

## Repository hygiene

Commit the templates, schema, scripts, `requirements.txt`, `.gitignore`, and this README. Do not commit database passwords, FastF1 cache files, generated reports, or ad-hoc model files.

## Current scope

This is a local academic demonstration, not a production deployment. It has no authentication, migrations, CI pipeline, or production secrets configuration yet.
