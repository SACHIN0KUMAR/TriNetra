import sqlite3
import pandas as pd
import numpy as np
import pickle
from sklearn.ensemble import RandomForestRegressor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'data' / 'trinetra.db'
MODELS_DIR = ROOT / 'models'

# Features for regression
FEATURES = [
    'original_cost_cr',
    'expenditure_cr',
    'physical_progress_pct',
    'expenditure_pct_original',
    'expenditure_progress_gap',
    'progress_change_pp'
]

def prepare_data():
    conn = sqlite3.connect(DB)
    df = pd.read_sql('SELECT * FROM projects_latest', conn)
    conn.close()
    
    # Calculate Cost Overrun (Cr)
    df['cost_overrun_cr'] = df['revised_cost_cr'] - df['original_cost_cr']
    
    # Calculate Time Overrun (Months)
    df['original_doc'] = pd.to_datetime(df['original_date_of_commissioning'], errors='coerce')
    df['revised_doc'] = pd.to_datetime(df['revised_date_of_commissioning'], errors='coerce')
    
    # Simple month difference
    df['time_overrun_months'] = (df['revised_doc'].dt.year - df['original_doc'].dt.year) * 12 + \
                                (df['revised_doc'].dt.month - df['original_doc'].dt.month)
                                
    # Fill NAs
    df['time_overrun_months'] = df['time_overrun_months'].fillna(0)
    df['cost_overrun_cr'] = df['cost_overrun_cr'].fillna(0)
    
    for f in FEATURES:
        df[f] = pd.to_numeric(df[f], errors='coerce').fillna(0)
        
    return df

def train_and_save():
    df = prepare_data()
    
    # Cost Model
    cost_model = RandomForestRegressor(n_estimators=100, max_depth=8, random_state=42)
    cost_model.fit(df[FEATURES], df['cost_overrun_cr'])
    
    cost_path = MODELS_DIR / 'cost_overrun_model.pkl'
    with open(cost_path, 'wb') as f:
        pickle.dump({'model': cost_model, 'features': FEATURES}, f)
    print(f"Saved Cost Overrun model to {cost_path}")
    
    # Time Model
    time_model = RandomForestRegressor(n_estimators=100, max_depth=8, random_state=42)
    time_model.fit(df[FEATURES], df['time_overrun_months'])
    
    time_path = MODELS_DIR / 'time_overrun_model.pkl'
    with open(time_path, 'wb') as f:
        pickle.dump({'model': time_model, 'features': FEATURES}, f)
    print(f"Saved Time Overrun model to {time_path}")

if __name__ == '__main__':
    MODELS_DIR.mkdir(exist_ok=True)
    train_and_save()
