import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import time
import os
import json
from datetime import datetime, timezone

DATA_DIR = "historical_data/uko_uso"

def load_env():
    env = {}
    if os.path.exists(".env"):
        with open(".env", "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"): continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
    return env

def fetch_and_store():
    """Connects to MT5, fetches data, merges with local CSVs."""
    os.makedirs(DATA_DIR, exist_ok=True)
    env = load_env()

    # Fetch UKOUSD.sc and USOUSD.sc from Vantage (Broker 1)
    path_vantage = "C:\\MT5_Broker1\\terminal64.exe"
    login_vantage = int(env.get("MT5_LOGIN_2", 0))
    pass_vantage = env.get("MT5_PASSWORD_2", "")
    server_vantage = env.get("MT5_SERVER_2", "")

    print("Connecting to Vantage...")
    if not mt5.initialize(path=path_vantage, login=login_vantage, password=pass_vantage, server=server_vantage):
        raise Exception("Vantage init failed: " + str(mt5.last_error()))

    symbols = ["UKOUSD.sc", "USOUSD.sc"]
    for sym in symbols:
        print(f"Fetching {sym}...")
        mt5.symbol_select(sym, True)
        rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, 50000)
        
        if rates is not None and len(rates) > 0:
            df_new = pd.DataFrame(rates)[['time', 'close']]
            csv_path = os.path.join(DATA_DIR, f"{sym}.csv")
            if os.path.exists(csv_path):
                df_old = pd.read_csv(csv_path)
                df = pd.concat([df_old, df_new]).drop_duplicates(subset=['time'], keep='last')
            else:
                df = df_new
            df.sort_values('time', inplace=True)
            df.to_csv(csv_path, index=False)
            print(f"Saved {sym} - Total records: {len(df)}")
        else:
            print(f"Failed to fetch {sym}")

    mt5.shutdown()
    return {"status": "success"}

def get_chart_data():
    """Reads local CSVs, processes logic, returns Plotly traces."""
    if not os.path.exists(DATA_DIR):
        return {"error": "No historical data found. Please fetch data first."}
        
    uko_csv = os.path.join(DATA_DIR, "UKOUSD.sc.csv")
    uso_csv = os.path.join(DATA_DIR, "USOUSD.sc.csv")
    
    if not os.path.exists(uko_csv) or not os.path.exists(uso_csv):
        return {"error": "Data missing. Fetch data first."}
        
    df_uko = pd.read_csv(uko_csv)
    df_uso = pd.read_csv(uso_csv)
    
    rates_uko = df_uko.to_dict('records')
    rates_uso = df_uso.to_dict('records')
    
    map_uko = {r['time']: r for r in rates_uko}
    map_uso = {r['time']: r for r in rates_uso}
    
    common_times = sorted(list(set(map_uko.keys()) & set(map_uso.keys())))
    
    spreads = {}
    for idx, t in enumerate(common_times):
        is_near_gap = False
        if idx > 0 and (t - common_times[idx-1]) > 900:
            is_near_gap = True
        if idx < len(common_times)-1 and (common_times[idx+1] - t) > 900:
            is_near_gap = True
            
        st = time.gmtime(t)
        # Filter around midnight/daily gaps
        if (st.tm_hour == 23 and st.tm_min >= 45) or (st.tm_hour == 0 and st.tm_min <= 15):
            is_near_gap = True
            
        if not is_near_gap:
            spread = map_uko[t]['close'] - map_uso[t]['close']
            spreads[t] = spread

    traces_time = []
    times = sorted(spreads.keys())
    x_vals = [datetime.fromtimestamp(t).strftime('%Y-%m-%d %H:%M:%S') for t in times]
    y_vals = [round(spreads[t], 2) for t in times]
    
    if x_vals:
        traces_time.append({'x': x_vals, 'y': y_vals, 'name': 'UKOUSD - USOUSD', 'mode': 'lines', 'type': 'scatter', 'line': {'width': 1.5, 'color': '#f97316'}})
        
        # Calculate Average (Fair Value)
        avg_spread = sum(y_vals) / len(y_vals)
        
        # Calculate Average Before Iran War (Before 15 Feb 2026)
        # Using string comparison since format is %Y-%m-%d %H:%M:%S
        y_vals_before = [y for i, y in enumerate(y_vals) if x_vals[i] <= "2026-02-15 23:59:59"]
        avg_spread_before = sum(y_vals_before) / len(y_vals_before) if y_vals_before else None
        
        # Save fair values to JSON
        with open(os.path.join(DATA_DIR, "fair_value.json"), "w") as f:
            json.dump({
                "average": avg_spread,
                "average_before_war": avg_spread_before
            }, f, indent=4)
            
        # Add trace for Average
        traces_time.append({
            'x': [x_vals[0], x_vals[-1]],
            'y': [round(avg_spread, 2), round(avg_spread, 2)],
            'name': f'Fair Value (Avg={avg_spread:.2f})',
            'mode': 'lines',
            'line': {'width': 0.8, 'color': '#facc15', 'dash': 'dash'}
        })
        
        if avg_spread_before is not None:
            traces_time.append({
                'x': [x_vals[0], x_vals[-1]],
                'y': [round(avg_spread_before, 2), round(avg_spread_before, 2)],
                'name': f'Fair Value Before Iran War (Avg={avg_spread_before:.2f})',
                'mode': 'lines',
                'line': {'width': 0.8, 'color': '#22c55e', 'dash': 'dash'}  # Green dashed line
            })

    return {
        "traces_time": traces_time
    }

if __name__ == "__main__":
    fetch_and_store()
    print("Chart data size:", len(str(get_chart_data())))
