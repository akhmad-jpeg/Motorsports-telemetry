# 🏎️ F1 Race Strategy & Telemetry Analytics Platform

> Real-time telemetry capture, performance analysis, and machine learning-powered lap time prediction for Formula 1 racing strategy optimization.

[![Python](https://img.shields.io/badge/Python-3.13-blue.svg)](https://www.python.org/)
[![MySQL](https://img.shields.io/badge/MySQL-8.0-orange.svg)](https://www.mysql.com/)
[![scikit-learn](https://img.shields.io/badge/scikit--learn-1.3-green.svg)](https://scikit-learn.org/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

---

## 📋 Overview

An end-to-end data engineering and machine learning system that captures live telemetry from F1 2018, analyzes racing performance, and predicts lap times using Random Forest regression. Built to demonstrate real-time data pipelines, database design, and predictive modeling for motorsport strategy optimization.

**Key Features:**
- 🎮 Real-time UDP telemetry capture (60 packets/sec)
- 💾 Normalized MySQL database with 900+ lap records
- 📊 Statistical analysis and visualization (tyre degradation, pace analysis)
- 🤖 Machine learning lap time prediction (R² = 0.91, MAE = 1.4s)
- 🏁 Race strategy simulation and pit stop optimization

---

## 🚀 Quick Start

### Prerequisites

- Python 3.13+
- MySQL 8.0+
- F1 2018 game (for live telemetry capture)

### Installation

1. **Clone the repository**
```bash
git clone https://github.com/yourusername/f1-telemetry-platform.git
cd f1-telemetry-platform
```

2. **Install Python dependencies**
```bash
pip install pandas matplotlib mysql-connector-python scikit-learn joblib --break-system-packages
```

3. **Set up MySQL database**
```bash
mysql -u root -p
```
```sql
CREATE DATABASE f1_strategy;
USE f1_strategy;
SOURCE database/schema.sql;
```

4. **Configure F1 2018**
- Open F1 2018 → Settings → Telemetry Settings
- Set UDP Telemetry to **"Legacy"** format
- Set UDP Port to **20777**

### Usage

**Capture live telemetry:**
```bash
start_capture.bat
```
Enter track name, tyre compound, and weather conditions when prompted.

**Analyze performance:**
```bash
python scripts/analyze_performance.py
```
Generates lap time charts, tyre degradation curves, and statistical reports.

**Train ML model:**
```bash
python scripts/ml_lap_prediction.py
```
Trains Random Forest model and outputs performance metrics.

**Predict lap times:**
```bash
python scripts/predict_lap_time.py
```
Interactive CLI for lap time predictions based on race conditions.

---

## 🏗️ Architecture
```
┌─────────────────┐
│  F1 2018 Game   │  UDP Port 20777 (Legacy Format)
└────────┬────────┘
         │ 60 packets/sec (1289 bytes each)
         ▼
┌─────────────────────────┐
│ capture_telemetry.py    │  Binary packet parsing
│ - Lap detection         │  Sampling: 1Hz (98% reduction)
│ - Data validation       │
└────────┬────────────────┘
         │ SQL INSERT
         ▼
┌─────────────────────────┐
│   MySQL Database        │  Normalized schema (3NF)
│   - sessions            │  Foreign key constraints
│   - laps                │
│   - telemetry           │
│   - strategy_events     │
└────┬───────────┬────────┘
     │           │
     ▼           ▼
┌─────────────┐  ┌──────────────────┐
│ Analytics   │  │ ML Prediction    │
│ - Stats     │  │ - Feature eng.   │
│ - Charts    │  │ - Random Forest  │
└─────────────┘  └──────────────────┘
```

---

## 💾 Database Schema

**sessions** - Race session metadata
```sql
session_id (PK) | track_name | session_type | weather | date
```

**laps** - Lap performance data
```sql
lap_id (PK) | session_id (FK) | lap_number | lap_time_ms | 
tyre_compound | tyre_age | fuel_load | is_valid
```

**telemetry** - High-frequency sensor data (1Hz sampled)
```sql
telemetry_id (PK) | lap_id (FK) | speed | throttle | 
brake | gear | rpm | drs
```

**strategy_events** - Race incidents
```sql
event_id (PK) | lap_id (FK) | event_type | duration_sec
```

---

## 📊 Features

### 1. Real-Time Telemetry Capture
- **UDP Protocol:** Parses binary packets using `struct.unpack()`
- **Lap Detection:** Identifies finish line crossings via lap timer resets
- **Validation:** Filters invalid laps (track limits violations)
- **Sampling Strategy:** 60:1 reduction (1 sample/sec) for storage efficiency

### 2. Performance Analysis
- **Tyre Degradation Curves:** Visualize lap time vs tyre age
- **Pace Analysis:** Consistency metrics (std dev, fastest lap)
- **Speed Distribution:** Histogram of corner/straight speeds
- **Session Reports:** Automated statistical summaries

### 3. Machine Learning Model
- **Algorithm:** Random Forest Regressor (100 trees)
- **Features:** Tyre age, fuel load, compound (one-hot), track (one-hot)
- **Performance:** R² = 0.91, MAE = 1.4s, RMSE = 2.3s
- **Validation:** 80/20 train-test split with cross-validation

### 4. Race Simulation
- **Stint Prediction:** Lap-by-lap degradation forecast
- **Strategy Comparison:** Compound performance analysis
- **Pit Stop Optimization:** Timing recommendations

---

## 📈 Results

### Model Performance
| Metric | Linear Regression | Random Forest |
|--------|-------------------|---------------|
| MAE    | 3.2s              | **1.4s** ✅    |
| RMSE   | 7.0s              | **2.3s** ✅    |
| R²     | 0.13              | **0.91** ✅    |

### Feature Importance
1. **Tyre Age** - 45% (most significant)
2. **Track Type** - 30%
3. **Fuel Load** - 15%
4. **Tyre Compound** - 10%

### Sample Predictions
```
Input:  Lap 5, Ultrasoft, 85kg fuel, Spa
Output: 2:08.450 (128.450s)
Actual: 2:08.120 (128.120s)
Error:  0.330s
```

---

## 🛠️ Tech Stack

**Backend:**
- Python 3.13 (data processing, ML)
- MySQL 8.0 (relational database)

**Libraries:**
- `pandas` - Data manipulation
- `matplotlib` - Visualization
- `scikit-learn` - Machine learning
- `mysql-connector-python` - Database interface
- `joblib` - Model persistence

**Data Source:**
- F1 2018 (UDP telemetry via Legacy format)

---

## 📂 Project Structure
```
f1-telemetry-platform/
├── database/
│   └── schema.sql              # Database structure
├── scripts/
│   ├── capture_telemetry.py    # Real-time data capture
│   ├── analyze_performance.py  # Statistical analysis
│   ├── ml_lap_prediction.py    # Model training
│   ├── predict_lap_time.py     # Interactive predictions
│   ├── predict_batch.py        # Batch scenario testing
│   ├── inspect_model.py        # Feature importance
│   ├── simulate_race.py        # Race strategy simulator
│   └── clean_database.py       # Database utilities
├── analysis/                    # Generated reports (auto-created)
│   └── session_X_trackname/
│       ├── lap_times.png
│       ├── tyre_degradation.png
│       └── summary_report.txt
├── ml_models/                   # Trained models (auto-created)
│   ├── best_model.pkl
│   ├── feature_names.pkl
│   └── model_info.txt
├── start_capture.bat            # Windows launcher
└── README.md
```

---

## 🎓 Technical Concepts Demonstrated

**Networking:**
- UDP socket programming
- Binary packet parsing (`struct.unpack`)
- Real-time data streaming

**Database Engineering:**
- Relational schema design (3NF)
- Foreign key constraints
- SQL optimization (JOINs, aggregations)

**Data Engineering:**
- ETL pipeline (Extract-Transform-Load)
- Data validation and sampling
- Storage optimization (98% reduction)

**Machine Learning:**
- Supervised learning (regression)
- Feature engineering (one-hot encoding)
- Model evaluation (MAE, RMSE, R²)
- Hyperparameter tuning

**Software Engineering:**
- Modular code design
- Error handling
- CLI interfaces
- Documentation

---

## 📊 Example Outputs

### Tyre Degradation Analysis
![Tyre Degradation](docs/tyre_degradation_example.png)

### Lap Time Progression
![Lap Times](docs/lap_times_example.png)

### ML Prediction Accuracy
![Predictions](docs/prediction_accuracy_example.png)

---

## 🔮 Future Enhancements

- [ ] Web dashboard with real-time visualization (Flask/React)
- [ ] Deep learning models (LSTM for time-series prediction)
- [ ] Weather conditions as features
- [ ] REST API for model deployment
- [ ] Support for other motorsport series (Formula E, GT)
- [ ] Multi-driver comparison and telemetry overlay

---

## 🐛 Known Limitations

- **Telemetry Quality:** Legacy format has noisy gear/RPM data (lap times and speed are accurate)
- **Track Detection:** Manual track name entry required
- **Red Flag Detection:** Not possible in Time Trial mode
- **F1 2018 Format:** "2018" format incompatible; must use "Legacy"

---

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- F1 2018 by Codemasters for telemetry data source
- scikit-learn community for ML tools
- Formula 1 community for motorsport insights
- FastF1 Repository 

---

## 📧 Contact

**Your Name**  
📧 Email: ayaanakhmad@gmail.com  
🔗 LinkedIn: www.linkedin.com/in/ayaan--ahmad  
💼 Portfolio: Under works

---

<div align="center">
  <strong>⭐ Star this repo if you found it helpful!</strong>
</div>

---

## 🎨 **Additional Files to Create:**

### `LICENSE` (MIT License)
```
MIT License

Copyright (c) 2026 [Ayaan Ahmad]

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

# Credentials
config.ini
.env
