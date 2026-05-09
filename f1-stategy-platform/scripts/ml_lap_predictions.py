import pandas as pd
import numpy as np
import mysql.connector
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
import matplotlib.pyplot as plt
import joblib
import os
from datetime import datetime

DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'password',
    'database': 'f1_strategy'
}

def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)

print("=" * 60)
print("F1 LAP TIME PREDICTION - MODEL TRAINING")
print("=" * 60)

conn = get_db_connection()

# NO WEATHER — removing it prevents feature mismatch errors
# since the dashboard and predictor never send weather as input
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

print("\n[DATABASE] Loading training data...")
df = pd.read_sql(query, conn)
conn.close()

print(f"✓ Loaded {len(df)} valid laps")
print(f"✓ Tracks: {df['track_name'].nunique()}")
print(f"✓ Tyres:  {df['tyre_compound'].nunique()}")

# Normalise text columns so 'spa' and 'Spa' aren't treated as different tracks
df['track_name']    = df['track_name'].str.strip().str.title()
df['tyre_compound'] = df['tyre_compound'].str.strip()

# Fill missing fuel load (estimate: start 100kg, burn 2kg/lap)
if df['fuel_load'].isnull().any():
    print("\n⚠ Estimating missing fuel_load (2kg/lap burn rate)")
    df['fuel_load'] = df['fuel_load'].fillna(100 - (df['tyre_age'] * 2))

print("\n[FEATURE ENGINEERING] One-hot encoding...")
df_encoded = pd.get_dummies(df, columns=['tyre_compound', 'track_name'],
                            prefix=['tyre', 'track'])

print(f"✓ Total features: {len(df_encoded.columns) - 1}")
print(f"✓ Feature list:   {[c for c in df_encoded.columns if c != 'lap_time']}")

X = df_encoded.drop('lap_time', axis=1)
y = df_encoded['lap_time']
feature_names = X.columns.tolist()

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42
)

print(f"\n✓ Training samples: {len(X_train)}")
print(f"✓ Test samples:     {len(X_test)}")

# ── TRAIN MODELS ──────────────────────────────────────────────
print("\n" + "=" * 60)
print("TRAINING MODELS")
print("=" * 60)

models = {}

print("\n[1/2] Linear Regression...")
lr = LinearRegression()
lr.fit(X_train, y_train)
y_pred_lr = lr.predict(X_test)

models['LinearRegression'] = {
    'model':       lr,
    'mae':         mean_absolute_error(y_test, y_pred_lr),
    'rmse':        np.sqrt(mean_squared_error(y_test, y_pred_lr)),
    'r2':          r2_score(y_test, y_pred_lr),
    'predictions': y_pred_lr
}
print(f"  MAE:  {models['LinearRegression']['mae']:.3f}s")
print(f"  RMSE: {models['LinearRegression']['rmse']:.3f}s")
print(f"  R²:   {models['LinearRegression']['r2']:.3f}")

print("\n[2/2] Random Forest (100 trees)...")
rf = RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1)
rf.fit(X_train, y_train)
y_pred_rf = rf.predict(X_test)

models['RandomForest'] = {
    'model':       rf,
    'mae':         mean_absolute_error(y_test, y_pred_rf),
    'rmse':        np.sqrt(mean_squared_error(y_test, y_pred_rf)),
    'r2':          r2_score(y_test, y_pred_rf),
    'predictions': y_pred_rf
}
print(f"  MAE:  {models['RandomForest']['mae']:.3f}s")
print(f"  RMSE: {models['RandomForest']['rmse']:.3f}s")
print(f"  R²:   {models['RandomForest']['r2']:.3f}")

# ── SELECT BEST ───────────────────────────────────────────────
best_name  = min(models, key=lambda k: models[k]['mae'])
best_model = models[best_name]['model']

print(f"\n🏆 BEST MODEL: {best_name}")
print(f"   MAE:  {models[best_name]['mae']:.3f}s")
print(f"   RMSE: {models[best_name]['rmse']:.3f}s")
print(f"   R²:   {models[best_name]['r2']:.3f}")

# ── SAVE ──────────────────────────────────────────────────────
os.makedirs('ml_models', exist_ok=True)
joblib.dump(best_model,   'ml_models/best_model.pkl')
joblib.dump(feature_names,'ml_models/feature_names.pkl')
print("\n✓ Saved: ml_models/best_model.pkl")
print("✓ Saved: ml_models/feature_names.pkl")

# Model info text file
with open('ml_models/model_info.txt', 'w') as f:
    f.write("F1 LAP TIME PREDICTION MODEL\n")
    f.write("=" * 60 + "\n\n")
    f.write(f"Best Model:       {best_name}\n")
    f.write(f"MAE:              {models[best_name]['mae']:.3f}s\n")
    f.write(f"RMSE:             {models[best_name]['rmse']:.3f}s\n")
    f.write(f"R²:               {models[best_name]['r2']:.3f}\n")
    f.write(f"Training samples: {len(X_train)}\n")
    f.write(f"Test samples:     {len(X_test)}\n")
    f.write(f"Features:         {len(feature_names)}\n")
    f.write(f"Trained on:       {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
    f.write("Features used:\n")
    for fn in feature_names:
        f.write(f"  {fn}\n")

    if best_name == 'RandomForest':
        importances = best_model.feature_importances_
        feat_imp = pd.DataFrame({'feature': feature_names, 'importance': importances})
        feat_imp['category'] = feat_imp['feature'].apply(
            lambda x: 'Tyre Age'      if x == 'tyre_age'        else
                      'Fuel Load'     if x == 'fuel_load'       else
                      'Tyre Compound' if x.startswith('tyre_')  else
                      'Track'         if x.startswith('track_') else 'Other'
        )
        cat_imp = feat_imp.groupby('category')['importance'].sum().sort_values(ascending=False)
        f.write("\nGrouped Feature Importance:\n")
        f.write("-" * 40 + "\n")
        for cat, imp in cat_imp.items():
            f.write(f"  {cat:20s}: {imp:.3f}\n")

print("✓ Saved: ml_models/model_info.txt")

# ── CHARTS ────────────────────────────────────────────────────

# Feature importance (Random Forest only)
if best_name == 'RandomForest':
    importances = best_model.feature_importances_
    feat_imp = pd.DataFrame({'feature': feature_names, 'importance': importances})
    feat_imp = feat_imp.sort_values('importance', ascending=False)

    plt.figure(figsize=(10, 6))
    top15 = feat_imp.head(15)
    plt.barh(range(len(top15)), top15['importance'])
    plt.yticks(range(len(top15)), top15['feature'])
    plt.xlabel('Importance')
    plt.title('Top 15 Feature Importances — Random Forest')
    plt.tight_layout()
    plt.savefig('ml_models/feature_importance.png', dpi=300)
    print("✓ Saved: ml_models/feature_importance.png")

# Predictions vs actual
plt.figure(figsize=(10, 6))
plt.scatter(y_test, models[best_name]['predictions'], alpha=0.5, label='Predictions')
plt.plot(
    [y_test.min(), y_test.max()],
    [y_test.min(), y_test.max()],
    'r--', lw=2, label='Perfect Prediction'
)
plt.xlabel('Actual Lap Time (seconds)')
plt.ylabel('Predicted Lap Time (seconds)')
plt.title(f'{best_name} — Predicted vs Actual Lap Times')
plt.legend()
plt.grid(alpha=0.3)
plt.tight_layout()
plt.savefig('ml_models/predictions_vs_actual.png', dpi=300)
print("✓ Saved: ml_models/predictions_vs_actual.png")

print("\n" + "=" * 60)
print("TRAINING COMPLETE!")
print("=" * 60)
