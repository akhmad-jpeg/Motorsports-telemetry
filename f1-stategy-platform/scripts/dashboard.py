from flask import Flask, render_template, jsonify, request
import mysql.connector
import joblib
import pandas as pd
import os
import traceback

app = Flask(__name__)

# ── Database config ──────────────────────────────────────────
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'password',
    'database': 'f1_strategy'
}

def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)

# ── ML model (loaded once at startup) ───────────────────────
MODEL_PATH = 'ml_models/best_model.pkl'
FEATURES_PATH = 'ml_models/feature_names.pkl'

model = None
feature_names = []

if os.path.exists(MODEL_PATH) and os.path.exists(FEATURES_PATH):
    model = joblib.load(MODEL_PATH)
    feature_names = joblib.load(FEATURES_PATH)
    print(f"✓ Model loaded: {type(model).__name__} | {len(feature_names)} features")
else:
    print("⚠ Model not found — run scripts/ml_lap_prediction.py first")


# PAGE ROUTES
@app.route('/')
def index():
    return render_template('dashboard.html')


# SESSION / TELEMETRY API
@app.route('/api/sessions')
def get_sessions():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT
                s.session_id,
                s.track_name,
                s.session_type,
                s.weather,
                s.date,
                COUNT(l.lap_id)         AS total_laps,
                MIN(l.lap_time_ms)/1000 AS fastest_lap
            FROM sessions s
            LEFT JOIN laps l ON s.session_id = l.session_id
            GROUP BY s.session_id, s.track_name, s.session_type, s.weather, s.date
            ORDER BY s.date DESC, s.session_id DESC
            LIMIT 50
        """)
        sessions = cursor.fetchall()
        cursor.close()
        conn.close()

        for s in sessions:
            if s['date']:
                s['date'] = s['date'].strftime('%Y-%m-%d')
            s['fastest_lap'] = float(s['fastest_lap']) if s['fastest_lap'] else None

        return jsonify(sessions)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/session/<int:session_id>/laps')
def get_session_laps(session_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT
                lap_number,
                lap_time_ms / 1000.0 AS lap_time,
                tyre_compound,
                tyre_age,
                fuel_load,
                is_valid
            FROM laps
            WHERE session_id = %s
            ORDER BY lap_number
        """, (session_id,))
        laps = cursor.fetchall()
        cursor.close()
        conn.close()

        for lap in laps:
            lap['lap_time'] = float(lap['lap_time'])
            lap['fuel_load'] = float(lap['fuel_load']) if lap['fuel_load'] else 0

        return jsonify(laps)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/session/<int:session_id>/tyre-degradation')
def get_tyre_degradation(session_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT
                tyre_age,
                tyre_compound,
                AVG(lap_time_ms)/1000.0 AS avg_lap_time,
                COUNT(*)                AS num_laps
            FROM laps
            WHERE session_id = %s AND is_valid = 1
            GROUP BY tyre_age, tyre_compound
            ORDER BY tyre_compound, tyre_age
        """, (session_id,))
        data = cursor.fetchall()
        cursor.close()
        conn.close()

        for row in data:
            row['avg_lap_time'] = float(row['avg_lap_time'])

        return jsonify(data)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/latest-lap')
def get_latest_lap():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT
                s.track_name,
                l.lap_number,
                l.lap_time_ms / 1000.0 AS lap_time,
                l.tyre_compound,
                l.tyre_age,
                l.is_valid
            FROM laps l
            JOIN sessions s ON l.session_id = s.session_id
            ORDER BY l.lap_id DESC
            LIMIT 1
        """)
        lap = cursor.fetchone()
        cursor.close()
        conn.close()

        if lap:
            lap['lap_time'] = float(lap['lap_time'])
            return jsonify(lap)
        return jsonify({})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

# PREDICTOR API
@app.route('/api/predict/options')
def get_predict_options():
    if not feature_names:
        return jsonify({"error": "Model not loaded"}), 500

    tyres  = []
    tracks = []

    for feature in feature_names:
        if feature.startswith('tyre_'):
            name = feature.replace('tyre_', '')
            if name not in ['age', 'load']:
                tyre_type = 'INTERMEDIATE' if name == 'Intermediate' else ('WET' if name == 'Wet' else 'DRY')
                tyres.append({"name": name, "type": tyre_type})
        elif feature.startswith('track_'):
            tracks.append(feature.replace('track_', ''))

    return jsonify({"tyres": tyres, "tracks": tracks})


@app.route('/api/predict', methods=['POST'])
def predict_lap():
    if model is None:
        return jsonify({"error": "Model not loaded"}), 500
    try:
        body          = request.get_json()
        tyre_age      = float(body['tyre_age'])
        fuel_load     = float(body['fuel_load'])
        tyre_compound = body['tyre_compound']
        track_name    = body['track_name']

        tyre_feature  = f'tyre_{tyre_compound}'
        track_feature = f'track_{track_name}'

        if tyre_feature not in feature_names:
            return jsonify({"error": f"Unknown tyre: {tyre_compound}"}), 400
        if track_feature not in feature_names:
            return jsonify({"error": f"Unknown track: {track_name}"}), 400

        input_data = pd.DataFrame(0, index=[0], columns=feature_names)
        input_data['tyre_age']    = tyre_age
        input_data['fuel_load']   = fuel_load
        input_data[tyre_feature]  = 1
        input_data[track_feature] = 1

        predicted_time = float(model.predict(input_data)[0])
        minutes = int(predicted_time // 60)
        seconds = predicted_time % 60

        return jsonify({
            "predicted_time": predicted_time,
            "formatted":      f"{minutes}:{seconds:06.3f}",
            "track":          track_name,
            "tyre_compound":  tyre_compound,
            "tyre_age":       tyre_age,
            "fuel_load":      fuel_load
        })
    except KeyError as e:
        return jsonify({"error": f"Missing field: {e}"}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# STRATEGY ADVISOR API
def _stint_time(tyre, start_age, laps, track, fuel):
    """Sum predicted lap times across a full stint."""
    tf = f'tyre_{tyre}'
    tkf = f'track_{track}'
    if tf not in feature_names or tkf not in feature_names or laps <= 0:
        return 0.0
    total = 0.0
    for i in range(laps):
        row = pd.DataFrame(0, index=[0], columns=feature_names)
        row['tyre_age']  = start_age + i
        row['fuel_load'] = max(40, fuel - i * 2)
        row[tf]  = 1
        row[tkf] = 1
        total += float(model.predict(row)[0])
    return total


def _reason(event, strategy, laps_rem, tyre_age):
    pit = strategy['pit_stops'] > 0
    if event == 'VSC':
        return (f"VSC cuts pit loss. Fresh tyres worth it with {laps_rem} laps left." if pit
                else f"Tyres still usable (age {tyre_age}). Save stop for later.")
    if event == 'SafetyCar':
        return ("Safety Car = free pit stop. Take it NOW!" if pit
                else f"Only {laps_rem} laps left — not worth stopping.")
    if event == 'Rain':
        if 'Intermediate' in strategy['option'] or 'Wet' in strategy['option']:
            return "Track is wet — box for rain tyres immediately!"
        return "Rain just started. Track still has grip — monitor before committing."
    if event == 'Crash':
        return ("Incident likely brings VSC/SC — cheap pit window incoming." if pit
                else "Wait for VSC/SC confirmation before pitting.")
    return "Fastest strategy based on current model predictions."


@app.route('/api/strategy/analyze', methods=['POST'])
def analyze_strategy():
    if model is None:
        return jsonify({"error": "Model not loaded"}), 500
    try:
        body         = request.get_json()
        cur_lap      = int(body['current_lap'])
        total_laps   = int(body['total_laps'])
        cur_tyre     = body['current_tyre']
        cur_age      = int(body['current_age'])
        track        = body['track']
        event        = body['event_type']

        laps_rem  = max(1, total_laps - cur_lap)
        fuel      = max(40, 100 - cur_lap * 2)
        pit_loss  = 15 if event in ['VSC', 'SafetyCar'] else 25

        strategies = []

        # Stay out
        t = _stint_time(cur_tyre, cur_age, laps_rem, track, fuel)
        if t > 0:
            strategies.append({
                "option":      "Stay Out",
                "description": f"Continue on {cur_tyre} (age {cur_age})",
                "total_time":  t,
                "pit_stops":   0,
                "risk":        "Medium" if cur_age > 15 else "Low"
            })

        # Pit — same compound
        t = _stint_time(cur_tyre, 0, laps_rem, track, fuel) + pit_loss
        if t > pit_loss:
            strategies.append({
                "option":      f"Pit — Fresh {cur_tyre}",
                "description": f"New {cur_tyre} tyres (+{pit_loss}s pit)",
                "total_time":  t,
                "pit_stops":   1,
                "risk":        "Low"
            })

        # Pit — harder compound
        harder = {'Hypersoft':'Ultrasoft','Ultrasoft':'Supersoft','Supersoft':'Soft','Soft':'Medium','Medium':'Hard'}
        if cur_tyre in harder:
            alt = harder[cur_tyre]
            if f'tyre_{alt}' in feature_names and laps_rem > 8:
                t = _stint_time(alt, 0, laps_rem, track, fuel) + pit_loss
                if t > pit_loss:
                    strategies.append({
                        "option":      f"Pit — Switch to {alt}",
                        "description": f"More durable compound (+{pit_loss}s pit)",
                        "total_time":  t,
                        "pit_stops":   1,
                        "risk":        "Medium"
                    })

        # Pit — softer compound
        softer = {'Hard':'Medium','Medium':'Soft','Soft':'Supersoft','Supersoft':'Ultrasoft','Ultrasoft':'Hypersoft'}
        if cur_tyre in softer and laps_rem <= 15:
            alt = softer[cur_tyre]
            if f'tyre_{alt}' in feature_names:
                t = _stint_time(alt, 0, laps_rem, track, fuel) + pit_loss
                if t > pit_loss:
                    strategies.append({
                        "option":      f"Pit — Switch to {alt}",
                        "description": f"Attack mode — softer compound (+{pit_loss}s pit)",
                        "total_time":  t,
                        "pit_stops":   1,
                        "risk":        "High"
                    })

        # Rain tyres
        if event == 'Rain':
            for rain in ['Intermediate', 'Wet']:
                if f'tyre_{rain}' in feature_names:
                    t = _stint_time(rain, 0, laps_rem, track, fuel) + pit_loss
                    if t > pit_loss:
                        strategies.append({
                            "option":      f"Pit — {rain}",
                            "description": f"Switch to {rain} for wet conditions",
                            "total_time":  t,
                            "pit_stops":   1,
                            "risk":        "Low"
                        })

        strategies.sort(key=lambda x: x['total_time'])

        best = strategies[0] if strategies else None
        recommendation = {
            "action": best['option'] if best else "No data",
            "reason": _reason(event, best, laps_rem, cur_age) if best else "Not enough model data."
        }

        return jsonify({
            "event":             event,
            "current_situation": {"lap": cur_lap, "laps_remaining": laps_rem, "tyre": cur_tyre, "tyre_age": cur_age},
            "strategies":        strategies,
            "recommendation":    recommendation
        })

    except KeyError as e:
        return jsonify({"error": f"Missing field: {e}"}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

def clickable(url, text=None):
    if text is None:
        text = url
    return f"\033]8;;{url}\033\\{text}\033]8;;\033\\"


if __name__ == '__main__':
    print("=" * 60)
    print("F1 DIGITAL PIT WALL — Starting")
    print("=" * 60)
    print(f"\n🌐  {clickable('http://localhost:5000')}")
    print("\nPress Ctrl+C to stop\n")
    app.run(debug=True, host='0.0.0.0', port=5000)
