import mysql.connector
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
import matplotlib.pyplot as plt
import os
import joblib
from datetime import datetime

# ============================================
# DATABASE CONNECTION
# ============================================
def get_db_connection():
    conn = mysql.connector.connect(
        host='localhost',
        user='root',
        password='password',
        database='f1_strategy'
    )
    return conn

# ============================================
# DATA PREPARATION
# ============================================

def load_training_data(conn):
    """Load lap data for training"""
    query = """
    SELECT 
        l.lap_time_ms / 1000 as lap_time,
        l.tyre_age,
        l.fuel_load,
        l.tyre_compound,
        l.is_valid,
        s.track_name
    FROM laps l
    JOIN sessions s ON l.session_id = s.session_id
    WHERE l.is_valid = 1 
    AND l.lap_time_ms BETWEEN 60000 AND 180000
    """
    return pd.read_sql(query, conn)

def prepare_features(df):
    """Prepare features for ML model"""
    
    # One-hot encode tyre compound
    df_encoded = pd.get_dummies(df, columns=['tyre_compound', 'track_name'], prefix=['tyre', 'track'])
    
    # Features (X)
    feature_cols = [col for col in df_encoded.columns if col not in ['lap_time', 'is_valid']]
    X = df_encoded[feature_cols]
    
    # Target (y)
    y = df_encoded['lap_time']
    
    return X, y, feature_cols

# ============================================
# MODEL TRAINING
# ============================================

def train_models(X_train, X_test, y_train, y_test):
    """Train multiple models and compare"""
    
    models = {
        'Linear Regression': LinearRegression(),
        'Random Forest': RandomForestRegressor(n_estimators=100, random_state=42)
    }
    
    results = {}
    
    for name, model in models.items():
        print(f"\n[TRAINING] {name}...")
        
        # Train
        model.fit(X_train, y_train)
        
        # Predict
        y_pred = model.predict(X_test)
        
        # Metrics
        mae = mean_absolute_error(y_test, y_pred)
        rmse = np.sqrt(mean_squared_error(y_test, y_pred))
        r2 = r2_score(y_test, y_pred)
        
        results[name] = {
            'model': model,
            'mae': mae,
            'rmse': rmse,
            'r2': r2,
            'predictions': y_pred
        }
        
        print(f"  MAE:  {mae:.3f}s")
        print(f"  RMSE: {rmse:.3f}s")
        print(f"  R²:   {r2:.3f}")
    
    return results

# ============================================
# VISUALIZATION
# ============================================

def plot_predictions(y_test, predictions, model_name, output_dir):
    """Plot actual vs predicted lap times"""
    plt.figure(figsize=(10, 6))
    
    plt.scatter(y_test, predictions, alpha=0.6, edgecolors='k')
    plt.plot([y_test.min(), y_test.max()], [y_test.min(), y_test.max()], 
             'r--', lw=2, label='Perfect Prediction')
    
    plt.xlabel('Actual Lap Time (s)', fontsize=12)
    plt.ylabel('Predicted Lap Time (s)', fontsize=12)
    plt.title(f'Lap Time Prediction - {model_name}', fontsize=14, fontweight='bold')
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    
    filename = os.path.join(output_dir, f'prediction_{model_name.replace(" ", "_").lower()}.png')
    plt.savefig(filename, dpi=300, bbox_inches='tight')
    print(f"[SAVED] {filename}")
    plt.close()

def plot_feature_importance(model, feature_names, output_dir):
    """Plot feature importance for Random Forest"""
    if hasattr(model, 'feature_importances_'):
        importances = model.feature_importances_
        indices = np.argsort(importances)[::-1][:10]  # Top 10
        
        plt.figure(figsize=(10, 6))
        plt.barh(range(len(indices)), importances[indices], color='skyblue', edgecolor='black')
        plt.yticks(range(len(indices)), [feature_names[i] for i in indices])
        plt.xlabel('Importance', fontsize=12)
        plt.title('Top 10 Feature Importance', fontsize=14, fontweight='bold')
        plt.gca().invert_yaxis()
        plt.tight_layout()
        
        filename = os.path.join(output_dir, 'feature_importance.png')
        plt.savefig(filename, dpi=300, bbox_inches='tight')
        print(f"[SAVED] {filename}")
        plt.close()

def plot_residuals(y_test, predictions, model_name, output_dir):
    """Plot residuals (errors)"""
    residuals = y_test - predictions
    
    plt.figure(figsize=(10, 6))
    plt.scatter(predictions, residuals, alpha=0.6, edgecolors='k')
    plt.axhline(y=0, color='r', linestyle='--', lw=2)
    
    plt.xlabel('Predicted Lap Time (s)', fontsize=12)
    plt.ylabel('Residual (s)', fontsize=12)
    plt.title(f'Residual Plot - {model_name}', fontsize=14, fontweight='bold')
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    
    filename = os.path.join(output_dir, f'residuals_{model_name.replace(" ", "_").lower()}.png')
    plt.savefig(filename, dpi=300, bbox_inches='tight')
    print(f"[SAVED] {filename}")
    plt.close()

# ============================================
# MAIN ML PIPELINE
# ============================================

def main():
    print("=" * 60)
    print("F1 LAP TIME PREDICTION - ML MODEL")
    print("=" * 60)
    
    conn = get_db_connection()
    
    # Load data
    print("\n[1/5] Loading training data...")
    df = load_training_data(conn)
    
    if len(df) < 10:
        print("\n[ERROR] Not enough data for training!")
        print(f"Found {len(df)} laps. Need at least 10.")
        print("Drive more laps and try again.")
        conn.close()
        return
    
    print(f"[DATA] Loaded {len(df)} valid laps")
    print(f"[DATA] Tracks: {df['track_name'].unique().tolist()}")
    print(f"[DATA] Tyre compounds: {df['tyre_compound'].unique().tolist()}")
    
    # Prepare features
    print("\n[2/5] Preparing features...")
    X, y, feature_names = prepare_features(df)
    print(f"[FEATURES] {len(feature_names)} features created")
    
    # Split data
    print("\n[3/5] Splitting data (80% train, 20% test)...")
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    print(f"[SPLIT] Training: {len(X_train)} samples | Testing: {len(X_test)} samples")
    
    # Train models
    print("\n[4/5] Training models...")
    results = train_models(X_train, X_test, y_train, y_test)
    
# Find best model
    best_model_name = min(results, key=lambda k: results[k]['mae'])
    best_model = results[best_model_name]['model']
    
    print("\n" + "=" * 60)
    print("MODEL COMPARISON")
    print("=" * 60)
    for name, res in results.items():
        marker = " <- BEST" if name == best_model_name else ""
        print(f"{name:20s} | MAE: {res['mae']:.3f}s | RMSE: {res['rmse']:.3f}s | R²: {res['r2']:.3f}{marker}")
    
    # Create output directory
    output_dir = "ml_models"
    os.makedirs(output_dir, exist_ok=True)
    
    # Save visualizations
    print(f"\n[5/5] Generating visualizations...")
    for name, res in results.items():
        plot_predictions(y_test, res['predictions'], name, output_dir)
        plot_residuals(y_test, res['predictions'], name, output_dir)    
    
    # Feature importance (Random Forest only)
    if 'Random Forest' in results:
        plot_feature_importance(results['Random Forest']['model'], feature_names, output_dir)
    
    # Save best model
    model_filename = os.path.join(output_dir, 'best_model.pkl')
    joblib.dump(best_model, model_filename)
    print(f"[SAVED] {model_filename}")
    
    # Save feature names (needed for predictions later)
    features_filename = os.path.join(output_dir, 'feature_names.pkl')
    joblib.dump(feature_names, features_filename)
    print(f"[SAVED] {features_filename}")

    
    # Save model metadata
    metadata_filename = os.path.join(output_dir, 'model_info.txt')
    with open(metadata_filename, 'w') as f:
        f.write("F1 LAP TIME PREDICTION MODEL\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"Best Model: {best_model_name}\n")
        f.write(f"MAE: {results[best_model_name]['mae']:.3f}s\n")
        f.write(f"RMSE: {results[best_model_name]['rmse']:.3f}s\n")
        f.write(f"R²: {results[best_model_name]['r2']:.3f}\n\n")
        f.write(f"Training samples: {len(X_train)}\n")
        f.write(f"Test samples: {len(X_test)}\n")
        f.write(f"Features: {len(feature_names)}\n\n")
        f.write(f"Trained on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    print(f"[SAVED] {metadata_filename}")
    
    conn.close()
    
    print("\n" + "=" * 60)
    print("ML TRAINING COMPLETE")
    print("=" * 60)
    print(f"All files saved to: {output_dir}/")
    print(f"Best model: {best_model_name} (MAE: {results[best_model_name]['mae']:.3f}s)")

if __name__ == "__main__":
    main()