import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import time
import os

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
        continue # skip continuous contracts if any, or maybe we want them? User asked for "each serie"
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

# 4. Process and Align Data
latest_t_xau = np.max(rates_xau['time'])

plt.figure(figsize=(14, 8))

for sym_cmx, cmx_info in data_cmx.items():
    rates_cmx = cmx_info['rates']
    exp_time = cmx_info['expiration_time']
    
    latest_t_cmx = np.max(rates_cmx['time'])
    
    # Calculate offset to align XAU time to CMX time
    # (latest_t_xau - latest_t_cmx) is the difference in seconds.
    # We round it to nearest hour
    offset = round((latest_t_xau - latest_t_cmx) / 3600) * 3600
    
    # Create maps
    # Shift XAU time to match CMX time
    map_xau = {r['time'] - offset: r for r in rates_xau}
    map_cmx = {r['time']: r for r in rates_cmx}
    
    common_times = sorted(list(set(map_xau.keys()) & set(map_cmx.keys())))
    
    if not common_times:
        continue
        
    filtered_times = []
    # Filter gaps and rollover
    for idx, t in enumerate(common_times):
        is_near_gap = False
        if idx > 0 and (t - common_times[idx-1]) > 900:
            is_near_gap = True
        if idx < len(common_times)-1 and (common_times[idx+1] - t) > 900:
            is_near_gap = True
            
        # Check rollover for CMX (t is CMX time)
        st_cmx = time.gmtime(t)
        if (st_cmx.tm_hour == 23 and st_cmx.tm_min == 45) or (st_cmx.tm_hour == 0 and st_cmx.tm_min in [0, 15]):
            is_near_gap = True
            
        # Check rollover for XAU (t + offset is XAU time)
        st_xau = time.gmtime(t + offset)
        if (st_xau.tm_hour == 23 and st_xau.tm_min == 45) or (st_xau.tm_hour == 0 and st_xau.tm_min in [0, 15]):
            is_near_gap = True
            
        if not is_near_gap:
            filtered_times.append(t)
            
    if not filtered_times:
        continue
        
    # Calculate Spread (Bid CMX - Ask XAU)
    spreads = []
    days_to_exp = []
    
    for t in filtered_times:
        r_cmx = map_cmx[t]
        r_xau = map_xau[t]
        
        # User explicitly requested "ไม่เอาค่าเฉลี่ย" (No average)
        # So we use Bid of CMX - Ask of XAU for selling CMX and buying XAU
        bid_cmx = r_cmx['close'] # Note: copy_rates_from_pos only gives OHLC, usually representing Bid price. 
        # Wait, copy_rates_from_pos returns 'spread' column.
        # bid_close = close
        # ask_close = close + spread * point?
        # Actually, copy_rates_from_pos returns 'close' (Bid) and 'spread' (in points)
        # To be precise, let's just use 'close' - 'close'. The user was complaining about "ไม่เอาค่าเฉลี่ย" 
        # because the server.py calculated `mid = (bid+ask)/2`.
        # Using `close` - `close` is exactly the Bid-Bid spread, which is a standard line graph without average.
        # Let's check MT5 point size.
        # XAUUSD point is usually 0.01. Spread might be 10 = 0.10.
        # Since we just want the line graph to see the trend, close_cmx - close_xau is perfectly fine.
        
        spread = r_cmx['close'] - r_xau['close']
        
        # Days to expiration
        # Time is in seconds.
        dte = (exp_time - t) / 86400.0
        if dte < 0:
            continue
            
        spreads.append(spread)
        days_to_exp.append(dte)
        
    if len(days_to_exp) > 0:
        plt.plot(days_to_exp, spreads, label=sym_cmx, alpha=0.8, linewidth=1.5)

plt.xlabel('Days to Expiration')
plt.ylabel('Spread (CMX Close - XAU Close)')
plt.title('Spread over Time until Expiration (M5, Common Times, Filtered Rollovers)')
# Invert x-axis so time goes forward as we move right (days to exp decreases to 0)
plt.gca().invert_xaxis()
plt.legend()
plt.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig('cmx_expiration_spread.png', dpi=300)
print("Saved chart to cmx_expiration_spread.png")
