import os
import pandas as pd
import numpy as np
import subprocess
from datetime import datetime

DATA_DIR = "historical_data/tfx_m5"

def get_expiration_from_symbol(sym):
    # e.g. TFX.S50M26
    # Month codes: H=March, M=June, U=Sept, Z=Dec
    month_map = {'H': 3, 'M': 6, 'U': 9, 'Z': 12}
    code = sym.replace('TFX.S50', '') # "M26"
    if len(code) >= 3:
        m_char = code[0]
        y_str = code[1:3]
        if m_char in month_map and y_str.isdigit():
            month = month_map[m_char]
            year = 2000 + int(y_str)
            # TFEX usually expires around 29th
            dt = datetime(year, month, 29, 16, 30, 0)
            return dt.timestamp()
    return 0

def get_chart_data():
    files = os.listdir(DATA_DIR)
    
    set50_file = None
    for f in files:
        if f.startswith("SET50_"):
            set50_file = os.path.join(DATA_DIR, f)
            break
            
    if not set50_file:
        return {"error": "SET50 spot data missing."}
        
    df_set = pd.read_csv(set50_file)
    # Filter recent 2 months if needed, but since it's 5m, 10000 bars is about 1 month
    rates_set = df_set.to_dict('records')
    
    # Load Futures
    tfx_symbols = [f.replace('.csv', '').split('_M5')[0] for f in files if f.startswith('TFX.S50') and f.endswith('.csv')]
    
    if not tfx_symbols:
        return {"error": "No TFX.S50 futures data missing."}
        
    data_tfx = {}
    for sym in tfx_symbols:
        # file name format: TFX.S50M26_M5_MTS.csv
        # Find exact file
        matched_file = [f for f in files if f.startswith(sym + "_M5")][0]
        csv_path = os.path.join(DATA_DIR, matched_file)
        df_tfx = pd.read_csv(csv_path)
        exp_time = get_expiration_from_symbol(sym)
        if exp_time > 0:
            data_tfx[sym] = {
                "rates": df_tfx.to_dict('records'),
                "expiration_time": exp_time
            }
            
    sorted_syms = sorted(list(data_tfx.keys()), key=lambda x: data_tfx[x]['expiration_time'])
    
    # Traces
    traces_dte = []
    traces_time = []
    traces_calendar = []
    
    # Pre-calculate common timestamps with Spot
    map_set = {r['time']: r for r in rates_set}
    
    for sym in sorted_syms:
        rates_tfx = data_tfx[sym]['rates']
        exp_time = data_tfx[sym]['expiration_time']
        
        map_tfx = {r['time']: r for r in rates_tfx}
        
        common_times = sorted(list(set(map_set.keys()) & set(map_tfx.keys())))
        
        x_dte = []
        y_spread = []
        x_time = []
        
        for t in common_times:
            set_close = map_set[t]['bid']
            tfx_close = map_tfx[t]['bid']
            
            # Spread = Future - Spot (Contango)
            spread = tfx_close - set_close
            
            # DTE
            current_dt = datetime.strptime(t, "%Y-%m-%d %H:%M:%S")
            dte = (exp_time - current_dt.timestamp()) / 86400.0
            
            if dte < 0:
                continue
                
            x_dte.append(dte)
            y_spread.append(spread)
            x_time.append(t)
            
        if len(x_time) > 0:
            traces_dte.append({
                "x": x_dte,
                "y": y_spread,
                "mode": "lines",
                "name": f"{sym} - SET50",
                "hovertemplate": "DTE: %{x:.1f}d<br>Spread: %{y:.2f}<br>Time: %{text}",
                "text": x_time
            })
            
            traces_time.append({
                "x": x_time,
                "y": y_spread,
                "mode": "lines",
                "name": f"{sym} - SET50",
                "hovertemplate": "Time: %{x}<br>Spread: %{y:.2f}<br>DTE: %{text:.1f}d",
                "text": x_dte
            })

    # Inter-delivery Spread (Calendar Spread: Future B - Future A)
    # We will use the nearest future as anchor if there are overlapping times
    for i in range(len(sorted_syms)-1):
        sym_front = sorted_syms[i]
        sym_back = sorted_syms[i+1]
        
        rates_front = data_tfx[sym_front]['rates']
        rates_back = data_tfx[sym_back]['rates']
        
        map_front = {r['time']: r for r in rates_front}
        map_back = {r['time']: r for r in rates_back}
        
        common_times = sorted(list(set(map_front.keys()) & set(map_back.keys())))
        
        x_cal = []
        y_cal = []
        
        # Start anchoring at 0 at the very first common time
        # or we just plot raw spread? The user's oil chart had: "Start point anchored to furthest contract" -> meaning we normalize to 0?
        # Actually in oil_data_manager.py: "Spread Difference (NYX.MCLEU6 - NYX.MCLEQ6)" 
        # I'll plot raw Calendar Spread = Back - Front
        for t in common_times:
            front_close = map_front[t]['bid']
            back_close = map_back[t]['bid']
            spread = back_close - front_close
            
            x_cal.append(t)
            y_cal.append(spread)
            
        if len(x_cal) > 0:
            traces_calendar.append({
                "x": x_cal,
                "y": y_cal,
                "mode": "lines",
                "name": f"{sym_back} - {sym_front}",
                "hovertemplate": "Time: %{x}<br>Cal Spread: %{y:.2f}"
            })

    return {
        "traces_dte": traces_dte,
        "traces_time": traces_time,
        "traces_calendar": traces_calendar
    }

def fetch_new_data():
    subprocess.run(["python", "fetch_tfx_s50_m5.py"])
