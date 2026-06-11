import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import time
import os
import json
from datetime import datetime, timezone

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

def generate_html():
    env = load_env()

    path_vantage = "C:\\MT5_Broker1\\terminal64.exe"
    login_vantage = int(env.get("MT5_LOGIN_2", 0))
    pass_vantage = env.get("MT5_PASSWORD_2", "")
    server_vantage = env.get("MT5_SERVER_2", "")

    path_mts = "C:\\MT5_Broker2\\terminal64.exe"
    login_mts = int(env.get("MT5_LOGIN", 0))
    pass_mts = env.get("MT5_PASSWORD", "")
    server_mts = env.get("MT5_SERVER", "")

    print("Connecting to Vantage...")
    if not mt5.initialize(path=path_vantage, login=login_vantage, password=pass_vantage, server=server_vantage):
        print("Vantage init failed:", mt5.last_error())
        return

    sym_xau = "XAUUSD.sc"
    mt5.symbol_select(sym_xau, True)
    rates_xau = mt5.copy_rates_from_pos(sym_xau, mt5.TIMEFRAME_M5, 0, 50000)
    mt5.shutdown()

    if rates_xau is None or len(rates_xau) == 0:
        print("Failed to get XAUUSD.sc data")
        return

    print("Connecting to MTS...")
    if not mt5.initialize(path=path_mts, login=login_mts, password=pass_mts, server=server_mts):
        print("MTS init failed:", mt5.last_error())
        return

    cmx_symbols = mt5.symbols_get(group="*CMX.MGC*")
    if not cmx_symbols:
        print("No CMX.MGC symbols found")
        mt5.shutdown()
        return

    data_cmx = {}
    for s in cmx_symbols:
        if s.expiration_time == 0:
            continue 
        print(f"Fetching {s.name}...")
        mt5.symbol_select(s.name, True)
        rates = mt5.copy_rates_from_pos(s.name, mt5.TIMEFRAME_M5, 0, 50000)
        if rates is not None and len(rates) > 0:
            data_cmx[s.name] = {
                "rates": rates,
                "expiration_time": s.expiration_time
            }

    mt5.shutdown()

    if not data_cmx:
        print("No rates fetched for CMX")
        return

    sorted_syms = sorted(list(data_cmx.keys()), key=lambda x: data_cmx[x]['expiration_time'])
    
    latest_t_xau = np.max(rates_xau['time'])

    spreads_by_sym = {sym: {} for sym in sorted_syms}
    dte_by_sym = {sym: {} for sym in sorted_syms}

    for sym_cmx in sorted_syms:
        rates_cmx = data_cmx[sym_cmx]['rates']
        exp_time = data_cmx[sym_cmx]['expiration_time']
        latest_t_cmx = np.max(rates_cmx['time'])
        
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
                    # Explicitly cut out the noisy data block for Q6 as requested
                    if "Q6" in sym_cmx and 145 <= dte <= 155:
                        continue
                    spreads_by_sym[sym_cmx][t] = spread
                    dte_by_sym[sym_cmx][t] = dte

    # Prepare Plotly Traces
    
    # 1. Spread vs DTE
    traces_dte = []
    for sym in sorted_syms:
        times = sorted(spreads_by_sym[sym].keys(), reverse=True) # Sort DTE descending
        x_vals = [round(dte_by_sym[sym][t], 3) for t in times]
        y_vals = [round(spreads_by_sym[sym][t], 2) for t in times]
        if x_vals:
            traces_dte.append({
                'x': x_vals,
                'y': y_vals,
                'name': sym,
                'mode': 'lines',
                'type': 'scatter',
                'line': {'width': 1.5}
            })

    # 2. Spread vs Chronological Time
    traces_time = []
    for sym in sorted_syms:
        times = sorted(spreads_by_sym[sym].keys())
        # Plotly accepts YYYY-MM-DD HH:MM:SS format
        x_vals = [datetime.fromtimestamp(t).strftime('%Y-%m-%d %H:%M:%S') for t in times]
        y_vals = [round(spreads_by_sym[sym][t], 2) for t in times]
        if x_vals:
            traces_time.append({
                'x': x_vals,
                'y': y_vals,
                'name': sym,
                'mode': 'lines',
                'type': 'scatter',
                'line': {'width': 1.5}
            })

    # 3. Calendar Spreads
    traces_calendar = []
    if len(sorted_syms) >= 3:
        sym_blue = sorted_syms[0]
        sym_orange = sorted_syms[1]
        sym_green = sorted_syms[2]

        if spreads_by_sym[sym_green]:
            start_time = min(spreads_by_sym[sym_green].keys())
            
            # Green - Orange (G7 - Z6)
            x_go, y_go = [], []
            for t in sorted(spreads_by_sym[sym_green].keys()):
                if t >= start_time and t in spreads_by_sym[sym_orange]:
                    x_go.append(datetime.fromtimestamp(t).strftime('%Y-%m-%d %H:%M:%S'))
                    y_go.append(round(spreads_by_sym[sym_green][t] - spreads_by_sym[sym_orange][t], 2))
            if x_go:
                traces_calendar.append({
                    'x': x_go, 'y': y_go, 'name': f'Green - Orange ({sym_green} - {sym_orange})',
                    'mode': 'lines', 'type': 'scatter', 'line': {'width': 1.5, 'color': '#ef4444'} # red
                })

            # Green - Blue (G7 - Q6)
            x_gb, y_gb = [], []
            for t in sorted(spreads_by_sym[sym_green].keys()):
                if t >= start_time and t in spreads_by_sym[sym_blue]:
                    x_gb.append(datetime.fromtimestamp(t).strftime('%Y-%m-%d %H:%M:%S'))
                    y_gb.append(round(spreads_by_sym[sym_green][t] - spreads_by_sym[sym_blue][t], 2))
            if x_gb:
                traces_calendar.append({
                    'x': x_gb, 'y': y_gb, 'name': f'Green - Blue ({sym_green} - {sym_blue})',
                    'mode': 'lines', 'type': 'scatter', 'line': {'width': 1.5, 'color': '#8b5cf6'} # purple
                })

            # Orange - Blue (Z6 - Q6)
            x_ob, y_ob = [], []
            for t in sorted(spreads_by_sym[sym_green].keys()):
                if t >= start_time and t in spreads_by_sym[sym_orange] and t in spreads_by_sym[sym_blue]:
                    x_ob.append(datetime.fromtimestamp(t).strftime('%Y-%m-%d %H:%M:%S'))
                    y_ob.append(round(spreads_by_sym[sym_orange][t] - spreads_by_sym[sym_blue][t], 2))
            if x_ob:
                traces_calendar.append({
                    'x': x_ob, 'y': y_ob, 'name': f'Orange - Blue ({sym_orange} - {sym_blue})',
                    'mode': 'lines', 'type': 'scatter', 'line': {'width': 1.5, 'color': '#f97316'} # orange
                })

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>CMX Analytics Dashboard</title>
        <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #0f172a; color: #f1f5f9; margin: 0; padding: 20px; }}
            .container {{ max-width: 1400px; margin: 0 auto; background: #1e293b; padding: 20px; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); }}
            h1 {{ text-align: center; color: #38bdf8; margin-bottom: 30px; }}
            .chart-box {{ margin-bottom: 50px; background: #0f172a; border-radius: 8px; padding: 15px; border: 1px solid #334155; }}
            .chart-title {{ font-size: 1.2rem; color: #cbd5e1; margin-bottom: 10px; text-align: center; }}
            .chart-desc {{ text-align: center; color: #94a3b8; font-size: 0.9em; margin-bottom: 15px; }}
            .plot-container {{ width: 100%; height: 500px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Comprehensive CMX Analytics Dashboard</h1>
            <p style="text-align: center; color: #94a3b8; margin-bottom: 30px;">Data rigorously filtered for Timezone Offsets, Gaps (>15m), and Market Rollovers.</p>

            <div class="chart-box">
                <div class="chart-title">1. Spread vs Days to Expiration</div>
                <div class="chart-desc">X-Axis: Days until expiration (countdown to 0). Y-Axis: Spread (CMX - XAU).</div>
                <div id="chart1" class="plot-container"></div>
            </div>

            <div class="chart-box">
                <div class="chart-title">2. Spread vs Chronological Time</div>
                <div class="chart-desc">X-Axis: Real-time Date. Y-Axis: Spread (CMX - XAU).</div>
                <div id="chart2" class="plot-container"></div>
            </div>

            <div class="chart-box">
                <div class="chart-title">3. Inter-delivery Calendar Spreads</div>
                <div class="chart-desc">X-Axis: Real-time Date. Y-Axis: Price difference between CMX Series. Start point anchored to furthest contract.</div>
                <div id="chart3" class="plot-container"></div>
            </div>
        </div>
        
        <script>
            var layout_base = {{
                plot_bgcolor: '#0f172a',
                paper_bgcolor: '#0f172a',
                font: {{ color: '#f1f5f9' }},
                hovermode: 'closest',
                legend: {{ bgcolor: 'rgba(15, 23, 42, 0.8)', bordercolor: '#334155', borderwidth: 1 }},
                margin: {{ l: 60, r: 30, t: 30, b: 60 }}
            }};

            // Chart 1: Spread vs DTE
            var data1 = {json.dumps(traces_dte)};
            var layout1 = Object.assign({{}}, layout_base, {{
                xaxis: {{ title: 'Days to Expiration', autorange: 'reversed', gridcolor: '#334155', zerolinecolor: '#475569', tickcolor: '#94a3b8' }},
                yaxis: {{ title: 'Spread (CMX - XAU)', gridcolor: '#334155', zerolinecolor: '#475569', tickcolor: '#94a3b8' }}
            }});
            Plotly.newPlot('chart1', data1, layout1);

            // Chart 2: Spread vs Time
            var data2 = {json.dumps(traces_time)};
            var layout2 = Object.assign({{}}, layout_base, {{
                xaxis: {{ title: 'Date', gridcolor: '#334155', zerolinecolor: '#475569', tickcolor: '#94a3b8' }},
                yaxis: {{ title: 'Spread (CMX - XAU)', gridcolor: '#334155', zerolinecolor: '#475569', tickcolor: '#94a3b8' }}
            }});
            Plotly.newPlot('chart2', data2, layout2);

            // Chart 3: Calendar Spreads
            var data3 = {json.dumps(traces_calendar)};
            var layout3 = Object.assign({{}}, layout_base, {{
                xaxis: {{ title: 'Date', gridcolor: '#334155', zerolinecolor: '#475569', tickcolor: '#94a3b8' }},
                yaxis: {{ title: 'Calendar Spread Difference', gridcolor: '#334155', zerolinecolor: '#475569', tickcolor: '#94a3b8' }}
            }});
            Plotly.newPlot('chart3', data3, layout3);
        </script>
    </body>
    </html>
    """
    
    with open('spread_analysis_m5.html', 'w', encoding='utf-8') as f:
        f.write(html_content)
    print("Successfully created spread_analysis_m5.html with 3 charts!")

if __name__ == "__main__":
    generate_html()
