# 🏎️ F1 Race Strategy & Telemetry Analytics Platform

> Real-time telemetry capture, race-data import, performance analysis, and lap-time prediction for Formula 1 strategy work.

[![Python](https://img.shields.io/badge/Python-3.13-blue.svg)](https://www.python.org/)
[![MySQL](https://img.shields.io/badge/MySQL-8.0-orange.svg)](https://www.mysql.com/)
[![scikit-learn](https://img.shields.io/badge/scikit--learn-1.9-green.svg)](https://scikit-learn.org/)

---

## 📋 Overview

A data pipeline that captures live telemetry from F1 2018 (UDP, Legacy format), imports real race data via FastF1, stores everything in a normalized MySQL database, and serves a Flask dashboard with a machine-learning lap-time model and strategy advice.

**Key features:**
- 🎮 Real-time UDP telemetry capture with correct F1 2018 Legacy packet parsing
- 🏁 Real race data import (FastF1) with pit-stop event reconciliation and race-control extraction (SC/VSC/red flag)
- 💾 Normalized MySQL schema (`database/schema.sql`)
- 📊 Flask dashboard: lap times, fuel-adjusted tyre degradation (pit in/out laps marked as visible spikes), speed distribution, strategy events
- 🤖 LinearRegression lap-time model with explicit unseen-track rejection
- 🖱️ One-click Windows launchers for every pipeline step — setup, import, train, serve, capture
- 🧪 142 unit tests, all mocked against the DB so CI needs no MySQL

---

## 🚀 Quick Start

### Prerequisites

- Python 3.13+
- MySQL 8.0+
- F1 2018 game (only for live telemetry capture)

### Installation

1. **Clone the repository**
```bash
git clone https://github.com/akhmad-jpeg/Motorsports-telemetry.git
cd Motorsports-telemetry/f1-stategy-platform
```

2. **Install dependencies** (use a virtualenv)
```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

3. **Set up the database**
```sql
CREATE DATABASE f1_strategy;
USE f1_strategy;
SOURCE database/schema.sql;
```

4. **Configure MySQL credentials** — the app reads `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`, `DB_PORT` from the environment (`scripts/config.py`). Defaults are `localhost` / `root` / `f1_strategy` / `3306`, but the password has **no** default: it starts as the placeholder `CHANGE_ME` and the app refuses to connect until you set `DB_PASSWORD` (e.g. `set DB_PASSWORD=yourpassword` on Windows, or `export DB_PASSWORD=yourpassword` on Linux/macOS).

### Usage

**One-click launchers (recommended)** — double-click any file in `launchers/`; each one handles the Python/venv plumbing itself:

| Step | Launcher |
|---|---|
| Install dependencies into `.venv` | `launchers\01_setup_dependencies.bat` |
| Import one race (interactive) | `launchers\02_import_race.bat` |
| Batch-import races/seasons | `launchers\03_import_dataset.bat` |
| Audit / repair pit events | `launchers\04_audit_pit_events.bat` |
| Train the lap-time model | `launchers\05_train_model.bat` |
| Start the dashboard | `launchers\06_run_server.bat` |
| Live UDP telemetry capture | `launchers\07_capture_telemetry.bat` |
| Interactive lap-time prediction | `launchers\08_predict_lap_times.bat` |
| Performance analysis reports | `launchers\09_analyze_performance.bat` |
| Model-selection benchmark | `launchers\10_benchmark_models.bat` |
| Run the test suite | `launchers\11_run_tests.bat` |

Run them in numbered order the first time (01 → 06). The full table lives in `launchers/README.md`.

The same steps are available as plain Python commands (e.g. on non-Windows or for scripting):

**Live capture (F1 2018, Legacy UDP on port 20777):**
```bash
scripts\start_telemetry.bat
```

**Web dashboard:**
```bash
python scripts/run_server.py        # production (Waitress)
# or, for development:
python scripts/dashboard.py          # debug mode, binds 127.0.0.1 only
```
Open http://localhost:5000.

**Import a real race (FastF1):**
```bash
python scripts/import_f1_race.py
```

**Analysis reports (CLI):**
```bash
python scripts/analyze_performance.py
```

**Retrain the model:**
```bash
python scripts/ml_lap_predictions.py
```

---

## 🗺️ Architecture

```
F1 2018 (UDP 20777, Legacy) ──► capture_telemetry.py ──┐
FastF1 race data            ──► import_f1_race.py    ──┤
                                                        ▼
                                             MySQL (f1_strategy)
                                                        │
              ┌──────────────┬─────────────────────────┼───────────────┐
              ▼              ▼                         ▼               ▼
        dashboard.py   analyze_performance.py   ml_lap_predictions.py
        (Flask UI)     (charts + reports)       (LinearRegression)
                                                              │
                                                        predict_lap_times.py
                                                        (strategy advisor)
```

Key modules in `scripts/`:

| File | Purpose |
|---|---|
| `capture_telemetry.py` | Live UDP capture; parses F1 2018 Legacy packets, detects laps, samples telemetry, inserts into MySQL |
| `import_f1_race.py` / `import_f1_dataset.py` | FastF1 race import; tyre compounds, pit events, race-control extraction, 2025 calendar |
| `cleanup_pit_events.py` | Audit + repair tool: purge spurious pit events, insert missing ones, re-validate lap validity (dry-run by default, `--apply` to write) |
| `stint_analysis.py` | Per-stint detrending so tyre wear is visible despite fuel burn (shared by dashboard + CLI) |
| `dashboard.py` / `run_server.py` | Flask web app and its production entry point (prints a clickable localhost link) |
| `analyze_performance.py` | CLI charts and summary reports |
| `ml_lap_predictions.py` / `feature_pipeline.py` | Model training and feature engineering |
| `predict_lap_times.py` | Interactive lap-time prediction / strategy advisor CLI |
| `benchmark_models.py` | Reproducible model-selection benchmark (random split, stint-grouped, unseen-track contracts) |
| `fuel_estimation.py` | Fuel-load estimation from telemetry |

---

## 🧠 Model notes

- **Algorithm:** LinearRegression on `tyre_age`, tyre compound, and track one-hot features. Selected over RandomForest/GradientBoosting after a head-to-head benchmark (`scripts/benchmark_models.py`) — the trees' apparent edge came from stint leakage, and their tyre-age response is jagged in exactly the region the pit decision lives.
- **Performance (within-track split):** MAE ≈ 1.64 s, R² ≈ 0.86.
- **Unseen tracks are rejected, not extrapolated:** the predictor refuses tracks absent from training with a clear message (generalizing a track's speed from a single session is not possible — R² ≤ 0 on unseen tracks for every model tried).
- **Fuel-neutral advice:** stay-out vs pit comparisons detrend the fuel-burn slope baked into `tyre_age`, so the advisor doesn't overstate tyre wear.

---

## 🧪 Testing

```bash
python -m unittest discover -s tests
```

142 tests covering the packet parser (against the real spec byte offsets), race-control extraction, stint analysis (incl. pit-lap chart markers), pit-event reconciliation, importer behavior, dashboard API, the server startup banner, and capture liveness. All DB access is mocked; CI runs the same command on Python 3.13.

---

## 📂 Project structure

```
f1-stategy-platform/
├── database/schema.sql        # MySQL schema (incl. composite indexes)
├── scripts/                   # capture, import, analysis, model, dashboard
│   ├── templates/dashboard.html
│   └── start_telemetry.bat
├── launchers/                 # one-click .bat files for every pipeline step
├── tests/                     # 142 unit tests
├── requirements.txt           # pinned dependencies
└── .github/workflows/ci.yml   # CI: install + run tests
```

Generated at runtime (gitignored): `f1_cache/` (FastF1 cache), `ml_models/` (trained artifacts), `analysis/` (CLI report output), `.venv/`.

---

## 🛠️ Tech stack

- Python 3.13, Flask + Waitress, MySQL 8
- pandas, matplotlib, scikit-learn, statsmodels, joblib
- FastF1 (real race data), mysql-connector-python

---

## 📧 Contact

**Ayaan Ahmad** — ayaanakhmad@gmail.com
