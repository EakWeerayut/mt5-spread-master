import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import time
import os
import json
from datetime import datetime, timezone

DATA_DIR = "historical_data/cmx"
META_FILE = os.path.join(DATA_DIR, "meta.json")

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

def load_meta():
    if os.path.exists(META_FILE):
        with open(META_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_meta(meta):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(META_FILE, 'w') as f:
        json.dump(meta, f, indent=4)

def fetch_and_store():
    """Connects to MT5, fetches data, merges with local CSVs."""
    os.makedirs(DATA_DIR, exist_ok=True)
    env = load_env()
    meta = load_meta()

    # 1. Fetch Vantage XAUUSD.sc
    path_vantage = "C:\\MT5_Broker1\\terminal64.exe"
    login_vantage = int(env.get("MT5_LOGIN_2", 0))
    pass_vantage = env.get("MT5_PASSWORD_2", "")
    server_vantage = env.get("MT5_SERVER_2", "")

    print("Connecting to Vantage...")
    if not mt5.initialize(path=path_vantage, login=login_vantage, password=pass_vantage, server=server_vantage):
        raise Exception("Vantage init failed: " + str(mt5.last_error()))

    sym_xau = "XAUUSD.sc"
    mt5.symbol_select(sym_xau, True)
    # Fetch a large chunk to guarantee overlaps, but appending is safe.
    rates_xau = mt5.copy_rates_from_pos(sym_xau, mt5.TIMEFRAME_M5, 0, 50000)
    mt5.shutdown()

    if rates_xau is not None and len(rates_xau) > 0:
        df_new_xau = pd.DataFrame(rates_xau)[['time', 'close']]
        csv_path = os.path.join(DATA_DIR, f"{sym_xau}.csv")
        if os.path.exists(csv_path):
            df_old = pd.read_csv(csv_path)
            df_xau = pd.concat([df_old, df_new_xau]).drop_duplicates(subset=['time'], keep='last')
        else:
            df_xau = df_new_xau
        df_xau.sort_values('time', inplace=True)
        df_xau.to_csv(csv_path, index=False)
        print(f"Saved {sym_xau} - Total records: {len(df_xau)}")
    else:
        raise Exception("Failed to get XAUUSD.sc data")

    # 2. Fetch MTS CMX
    path_mts = "C:\\MT5_Broker2\\terminal64.exe"
    login_mts = int(env.get("MT5_LOGIN", 0))
    pass_mts = env.get("MT5_PASSWORD", "")
    server_mts = env.get("MT5_SERVER", "")

    print("Connecting to MTS...")
    if not mt5.initialize(path=path_mts, login=login_mts, password=pass_mts, server=server_mts):
        raise Exception("MTS init failed: " + str(mt5.last_error()))

    cmx_symbols = mt5.symbols_get(group="*CMX.MGC*")
    if not cmx_symbols:
        mt5.shutdown()
        raise Exception("No CMX.MGC symbols found")

    for s in cmx_symbols:
        if s.expiration_time == 0:
            continue
        # Save expiration to meta so if it expires, we still have it
        meta[s.name] = {"expiration_time": s.expiration_time}
        
        print(f"Fetching {s.name}...")
        mt5.symbol_select(s.name, True)
        rates = mt5.copy_rates_from_pos(s.name, mt5.TIMEFRAME_M5, 0, 50000)
        
        if rates is not None and len(rates) > 0:
            df_new_cmx = pd.DataFrame(rates)[['time', 'close']]
            csv_path = os.path.join(DATA_DIR, f"{s.name}.csv")
            if os.path.exists(csv_path):
                df_old = pd.read_csv(csv_path)
                df_cmx = pd.concat([df_old, df_new_cmx]).drop_duplicates(subset=['time'], keep='last')
            else:
                df_cmx = df_new_cmx
            df_cmx.sort_values('time', inplace=True)
            df_cmx.to_csv(csv_path, index=False)
            print(f"Saved {s.name} - Total records: {len(df_cmx)}")

    mt5.shutdown()
    save_meta(meta)
    return {"status": "success"}

def get_chart_data():
    """Reads local CSVs, processes logic, returns Plotly traces."""
    if not os.path.exists(DATA_DIR):
        return {"error": "No historical data found. Please fetch data first."}
        
    meta = load_meta()
    
    # Load XAU
    xau_csv = os.path.join(DATA_DIR, "XAUUSD.sc.csv")
    if not os.path.exists(xau_csv):
        return {"error": "XAUUSD.sc data missing."}
        
    df_xau = pd.read_csv(xau_csv)
    rates_xau = df_xau.to_dict('records') # list of dicts with 'time', 'close'
    
    # Load CMX
    files = os.listdir(DATA_DIR)
    cmx_symbols = [f.replace('.csv', '') for f in files if f.startswith('CMX.MGC') and f.endswith('.csv')]
    
    if not cmx_symbols:
        return {"error": "No CMX data missing."}
        
    data_cmx = {}
    for sym in cmx_symbols:
        csv_path = os.path.join(DATA_DIR, f"{sym}.csv")
        df_cmx = pd.read_csv(csv_path)
        exp_time = meta.get(sym, {}).get("expiration_time", 0)
        if exp_time > 0:
            data_cmx[sym] = {
                "rates": df_cmx.to_dict('records'),
                "expiration_time": exp_time
            }
            
    sorted_syms = sorted(list(data_cmx.keys()), key=lambda x: data_cmx[x]['expiration_time'])
    
    latest_t_xau = max([r['time'] for r in rates_xau])
    
    spreads_by_sym = {sym: {} for sym in sorted_syms}
    dte_by_sym = {sym: {} for sym in sorted_syms}

    for sym_cmx in sorted_syms:
        rates_cmx = data_cmx[sym_cmx]['rates']
        exp_time = data_cmx[sym_cmx]['expiration_time']
        latest_t_cmx = max([r['time'] for r in rates_cmx])
        
        offset = round((latest_t_xau - latest_t_cmx) / 3600) * 3600
        
        map_xau = {r['time'] - offset: r for r in rates_xau}
        map_cmx = {r['time']: r for r in rates_cmx}
        
        common_times = sorted(list(set(map_xau.keys()) & set(map_cmx.keys())))
        
        for idx, t in enumerate(common_times):
            is_near_gap = False
            if idx > 0 and (t - common_times[idx-1]) > 900:
                is_near_gap = True
            if idx < len(common_times)-1 and (common_times[idx+1] - t) > 900:
                is_near_gap = True
                
            st_cmx = time.gmtime(t)
            if (st_cmx.tm_hour == 23 and st_cmx.tm_min == 45) or (st_cmx.tm_hour == 0 and st_cmx.tm_min in [0, 15]):
                is_near_gap = True
                
            st_xau = time.gmtime(t + offset)
            if (st_xau.tm_hour == 23 and st_xau.tm_min == 45) or (st_xau.tm_hour == 0 and st_xau.tm_min in [0, 15]):
                is_near_gap = True
                
            if not is_near_gap:
                spread = map_cmx[t]['close'] - map_xau[t]['close']
                dte = (exp_time - t) / 86400.0
                if dte >= 0:
                    # Filter Q6 noisy block
                    if "Q6" in sym_cmx and 145 <= dte <= 155:
                        continue
                    spreads_by_sym[sym_cmx][t] = spread
                    dte_by_sym[sym_cmx][t] = dte

    traces_dte = []
    for sym in sorted_syms:
        times = sorted(spreads_by_sym[sym].keys(), reverse=True)
        x_vals = [round(dte_by_sym[sym][t], 3) for t in times]
        y_vals = [round(spreads_by_sym[sym][t], 2) for t in times]
        if x_vals:
            traces_dte.append({'x': x_vals, 'y': y_vals, 'name': sym, 'mode': 'lines', 'type': 'scatter', 'line': {'width': 1.5}})

    traces_time = []
    for sym in sorted_syms:
        times = sorted(spreads_by_sym[sym].keys())
        x_vals = [datetime.fromtimestamp(t).strftime('%Y-%m-%d %H:%M:%S') for t in times]
        y_vals = [round(spreads_by_sym[sym][t], 2) for t in times]
        if x_vals:
            traces_time.append({'x': x_vals, 'y': y_vals, 'name': sym, 'mode': 'lines', 'type': 'scatter', 'line': {'width': 1.5}})

    traces_calendar = []
    if len(sorted_syms) >= 2:
        nearest_sym = sorted_syms[0]
        colors = ['#f97316', '#8b5cf6', '#ef4444', '#10b981', '#3b82f6', '#f59e0b']
        
        for i, sym in enumerate(sorted_syms[1:]):
            color = colors[i % len(colors)]
            x_vals, y_vals = [], []
            
            common_times = sorted(list(set(spreads_by_sym[sym].keys()) & set(spreads_by_sym[nearest_sym].keys())))
            
            for t in common_times:
                x_vals.append(datetime.fromtimestamp(t).strftime('%Y-%m-%d %H:%M:%S'))
                y_vals.append(round(spreads_by_sym[sym][t] - spreads_by_sym[nearest_sym][t], 2))
                
            if x_vals:
                traces_calendar.append({
                    'x': x_vals, 
                    'y': y_vals, 
                    'name': f'{sym} - {nearest_sym}', 
                    'mode': 'lines', 
                    'type': 'scatter', 
                    'line': {'width': 1.5, 'color': color}
                })

    # --- Regression Calculation ---
    all_x = []
    all_y = []
    for trace in traces_dte:
        all_x.extend(trace['x'])
        all_y.extend(trace['y'])
        
    regression_info = {"slope": 0.5612, "intercept": -2.5948, "r2": 0}
    if len(all_x) > 1:
        n = len(all_x)
        sum_x = sum(all_x)
        sum_y = sum(all_y)
        sum_xx = sum(x*x for x in all_x)
        sum_xy = sum(x*y for x, y in zip(all_x, all_y))
        
        denominator = n * sum_xx - sum_x**2
        if denominator != 0:
            m = (n * sum_xy - sum_x * sum_y) / denominator
            c = (sum_y - m * sum_x) / n
            
            mean_y = sum_y / n
            ss_tot = sum((y - mean_y)**2 for y in all_y)
            ss_res = sum((y - (m*x + c))**2 for x, y in zip(all_x, all_y))
            r2 = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
            
            regression_info = {"slope": m, "intercept": c, "r2": r2, "points": n}
            
            with open(os.path.join(DATA_DIR, "regression.json"), "w") as f:
                json.dump(regression_info, f, indent=4)
                
            # Add trace for Regression Line
            if all_x:
                min_x = min(all_x)
                max_x = max(all_x)
                traces_dte.append({
                    'x': [max_x, min_x],  # Reversing so it draws correctly left-to-right on countdown axis
                    'y': [round(m*max_x + c, 2), round(m*min_x + c, 2)],
                    'name': f'Fair Value (y={m:.4f}x{c:+.4f})',
                    'mode': 'lines',
                    'line': {'width': 0.8, 'color': '#facc15', 'dash': 'dash'}
                })
    # ------------------------------

    return {
        "traces_dte": traces_dte,
        "traces_time": traces_time,
        "traces_calendar": traces_calendar
    }

if __name__ == "__main__":
    # Test script standalone functionality
    fetch_and_store()
    print("Chart data size:", len(str(get_chart_data())))
