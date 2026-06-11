import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import time
import os
from datetime import datetime

# 1. Load config
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

env = load_env()

path_vantage = "C:\\MT5_Broker1\\terminal64.exe"
login_vantage = int(env.get("MT5_LOGIN_2"))
pass_vantage = env.get("MT5_PASSWORD_2")
server_vantage = env.get("MT5_SERVER_2")

path_mts = "C:\\MT5_Broker2\\terminal64.exe"
login_mts = int(env.get("MT5_LOGIN"))
pass_mts = env.get("MT5_PASSWORD")
server_mts = env.get("MT5_SERVER")

# 2. Fetch Vantage Data (XAUUSD.sc)
print("Connecting to Vantage...")
if not mt5.initialize(path=path_vantage, login=login_vantage, password=pass_vantage, server=server_vantage):
    print("Vantage init failed:", mt5.last_error())
    exit(1)

sym_xau = "XAUUSD.sc"
mt5.symbol_select(sym_xau, True)
rates_xau = mt5.copy_rates_from_pos(sym_xau, mt5.TIMEFRAME_M5, 0, 50000)
mt5.shutdown()

if rates_xau is None or len(rates_xau) == 0:
    print("Failed to get XAUUSD.sc data")
    exit(1)

# 3. Fetch MTS Data (CMX.MGC*)
print("Connecting to MTS...")
if not mt5.initialize(path=path_mts, login=login_mts, password=pass_mts, server=server_mts):
    print("MTS init failed:", mt5.last_error())
    exit(1)

cmx_symbols = mt5.symbols_get(group="*CMX.MGC*")
if not cmx_symbols:
    print("No CMX.MGC symbols found")
    mt5.shutdown()
    exit(1)

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
    exit(1)

# Sort symbols by expiration to ensure consistent mapping
# Expected: Q6 (Nearest), Z6 (Middle), G7 (Furthest)
sorted_syms = sorted(list(data_cmx.keys()), key=lambda x: data_cmx[x]['expiration_time'])
if len(sorted_syms) < 3:
    print("Not enough CMX series found to do Green-Orange and Green-Blue")
    exit(1)

# In matplotlib tab10 default color cycle:
# 1st plot (Blue) = sorted_syms[0] (Q6)
# 2nd plot (Orange) = sorted_syms[1] (Z6)
# 3rd plot (Green) = sorted_syms[2] (G7)
sym_blue = sorted_syms[0]
sym_orange = sorted_syms[1]
sym_green = sorted_syms[2]

# 4. Process and Align Data
latest_t_xau = np.max(rates_xau['time'])

# We will store the valid spread series for each symbol mapped by time
spreads_by_sym = {sym: {} for sym in sorted_syms}

for sym_cmx in sorted_syms:
    rates_cmx = data_cmx[sym_cmx]['rates']
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
            spreads_by_sym[sym_cmx][t] = spread

# Find the start time (First data point of Green line)
if not spreads_by_sym[sym_green]:
    print("No data for Green line.")
    exit(1)
    
start_time = min(spreads_by_sym[sym_green].keys())

# Collect intersections
# Green - Orange (G7 - Z6)
go_times = []
go_diffs = []
for t in sorted(spreads_by_sym[sym_green].keys()):
    if t >= start_time and t in spreads_by_sym[sym_orange]:
        go_times.append(datetime.fromtimestamp(t))
        go_diffs.append(spreads_by_sym[sym_green][t] - spreads_by_sym[sym_orange][t])

# Green - Blue (G7 - Q6)
gb_times = []
gb_diffs = []
for t in sorted(spreads_by_sym[sym_green].keys()):
    if t >= start_time and t in spreads_by_sym[sym_blue]:
        gb_times.append(datetime.fromtimestamp(t))
        gb_diffs.append(spreads_by_sym[sym_green][t] - spreads_by_sym[sym_blue][t])

# Orange - Blue (Z6 - Q6)
ob_times = []
ob_diffs = []
for t in sorted(spreads_by_sym[sym_green].keys()):
    if t >= start_time and t in spreads_by_sym[sym_orange] and t in spreads_by_sym[sym_blue]:
        ob_times.append(datetime.fromtimestamp(t))
        ob_diffs.append(spreads_by_sym[sym_orange][t] - spreads_by_sym[sym_blue][t])

# 5. Plotting
plt.figure(figsize=(14, 8))

if go_times:
    plt.plot(go_times, go_diffs, label=f'Green - Orange ({sym_green} - {sym_orange})', color='tab:red', linewidth=1.5, alpha=0.9)
if gb_times:
    plt.plot(gb_times, gb_diffs, label=f'Green - Blue ({sym_green} - {sym_blue})', color='tab:purple', linewidth=1.5, alpha=0.9)
if ob_times:
    plt.plot(ob_times, ob_diffs, label=f'Orange - Blue ({sym_orange} - {sym_blue})', color='tab:orange', linewidth=1.5, alpha=0.9)

plt.xlabel('Date (Chronological Time)')
plt.ylabel('Spread Difference (Calendar Spread)')
plt.title('Differences Between CMX Spreads (Aligned by XAU, Filtered Rollovers)')

# Format x-axis dates nicely
plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
plt.gca().xaxis.set_major_locator(mdates.AutoDateLocator())
plt.gcf().autofmt_xdate()

plt.legend()
plt.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig('cmx_calendar_spread.png', dpi=300)
print("Saved chart to cmx_calendar_spread.png")
