"""
APX.AUP10 (Gold 10oz Perpetual, long leg) vs CMX.MGC* (dated futures, short leg).

Both symbols live on the SAME mts account (Broker2), so:
  - No cross-broker time offset is needed (identical server clock).
  - Spread = MGC(dated future) - APX(perpetual), in USD/oz. We profit as it shrinks.
  - DTE axis is driven by the MGC contract's expiration (APX has none).

Trading hours of the two legs DIFFER even on the same account, so we restrict the
spread to times when BOTH legs are inside their *safe* session window, applying a
5-minute buffer after each open and before each close - identical logic to the live
Spread Master `is_time_in_safe_window` (open_sec + 300 <= tod <= close_sec - 300).
"""
import MetaTrader5 as mt5
import pandas as pd
import time
import os
import json
from datetime import datetime, timezone

DATA_DIR = "historical_data/apx"
META_FILE = os.path.join(DATA_DIR, "meta.json")

LONG_SYM = "APX.AUP10"           # perpetual, long leg
SHORT_PREFIX = "CMX.MGC"         # dated futures, short leg
SESSION_BARS = 6000              # ~20.8 days of M5 used to infer the current session schedule
SAFE_BUFFER = 300                # 5-minute buffer at each session edge (matches live master)


def load_env():
    env = {}
    if os.path.exists(".env"):
        with open(".env", "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
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


def compute_sessions(times):
    """Infer weekly trading sessions from a list of unix M5 timestamps.

    Returns {weekday_str: [[open_sec, close_sec], ...]} using server (UTC) time of day.
    Same gap heuristic as mt5_worker.handle_subscribe (a >30min gap splits a session).
    """
    by_day = {}
    for t in times:
        st = time.gmtime(int(t))
        wday = st.tm_wday
        tod = st.tm_hour * 3600 + st.tm_min * 60
        by_day.setdefault(wday, set()).add(tod)

    sessions = {}
    for wday, times_set in by_day.items():
        tods = sorted(times_set)
        if not tods:
            continue
        day_sessions = []
        start_t = tods[0]
        prev_t = tods[0]
        for tod in tods[1:]:
            if tod - prev_t > 1800:  # gap > 30 minutes -> new session block
                day_sessions.append([start_t, prev_t + 300])
                start_t = tod
            prev_t = tod
        day_sessions.append([start_t, prev_t + 300])
        sessions[str(wday)] = day_sessions
    return sessions


def is_time_in_safe_window(t_sec, sessions):
    """True if t falls inside a session with a 5-min buffer trimmed off both edges."""
    if not sessions:
        return True
    st = time.gmtime(int(t_sec))
    wday_str = str(st.tm_wday)
    if wday_str not in sessions:
        return False
    tod = st.tm_hour * 3600 + st.tm_min * 60 + st.tm_sec
    for open_sec, close_sec in sessions[wday_str]:
        if open_sec + SAFE_BUFFER <= tod <= close_sec - SAFE_BUFFER:
            return True
    return False


def _append_csv(df_new, csv_path):
    if os.path.exists(csv_path):
        df_old = pd.read_csv(csv_path)
        df = pd.concat([df_old, df_new]).drop_duplicates(subset=['time'], keep='last')
    else:
        df = df_new
    df.sort_values('time', inplace=True)
    df.to_csv(csv_path, index=False)
    return df


def fetch_and_store():
    """Connect once to mts, fetch APX.AUP10 + all active CMX.MGC*, merge into local CSVs."""
    os.makedirs(DATA_DIR, exist_ok=True)
    env = load_env()
    meta = load_meta()

    path_mts = "C:\\MT5_Broker2\\terminal64.exe"
    login_mts = int(env.get("MT5_LOGIN", 0))
    pass_mts = env.get("MT5_PASSWORD", "")
    server_mts = env.get("MT5_SERVER", "")

    print("Connecting to MTS...")
    if not mt5.initialize(path=path_mts, login=login_mts, password=pass_mts, server=server_mts):
        raise Exception("MTS init failed: " + str(mt5.last_error()))

    try:
        # 1. APX.AUP10 (perpetual long leg)
        mt5.symbol_select(LONG_SYM, True)
        rates_apx = mt5.copy_rates_from_pos(LONG_SYM, mt5.TIMEFRAME_M5, 0, 50000)
        if rates_apx is None or len(rates_apx) == 0:
            raise Exception(f"Failed to get {LONG_SYM} data")
        df_apx = _append_csv(pd.DataFrame(rates_apx)[['time', 'close']],
                             os.path.join(DATA_DIR, f"{LONG_SYM}.csv"))
        meta[LONG_SYM] = {"sessions": compute_sessions([r['time'] for r in rates_apx[-SESSION_BARS:]])}
        print(f"Saved {LONG_SYM} - Total records: {len(df_apx)}")

        # 2. CMX.MGC* dated futures (short legs)
        mgc_symbols = mt5.symbols_get(group=f"*{SHORT_PREFIX}*")
        if not mgc_symbols:
            raise Exception(f"No {SHORT_PREFIX} symbols found")

        for s in mgc_symbols:
            if s.expiration_time == 0:
                continue
            print(f"Fetching {s.name}...")
            mt5.symbol_select(s.name, True)
            rates = mt5.copy_rates_from_pos(s.name, mt5.TIMEFRAME_M5, 0, 50000)
            if rates is None or len(rates) == 0:
                continue
            df_cmx = _append_csv(pd.DataFrame(rates)[['time', 'close']],
                                os.path.join(DATA_DIR, f"{s.name}.csv"))
            meta[s.name] = {
                "expiration_time": s.expiration_time,
                "sessions": compute_sessions([r['time'] for r in rates[-SESSION_BARS:]]),
            }
            print(f"Saved {s.name} - Total records: {len(df_cmx)}")
    finally:
        mt5.shutdown()

    save_meta(meta)
    return {"status": "success"}


def get_chart_data():
    """Read local CSVs, build the 3 spread traces (DTE / chronological / calendar)."""
    if not os.path.exists(DATA_DIR):
        return {"error": "No historical data found. Please fetch data first."}

    meta = load_meta()

    apx_csv = os.path.join(DATA_DIR, f"{LONG_SYM}.csv")
    if not os.path.exists(apx_csv):
        return {"error": f"{LONG_SYM} data missing."}

    rates_apx = pd.read_csv(apx_csv).to_dict('records')
    sessions_apx = meta.get(LONG_SYM, {}).get("sessions")

    files = os.listdir(DATA_DIR)
    mgc_symbols = [f[:-4] for f in files if f.startswith(SHORT_PREFIX) and f.endswith('.csv')]
    if not mgc_symbols:
        return {"error": f"No {SHORT_PREFIX} data found."}

    data_mgc = {}
    for sym in mgc_symbols:
        df = pd.read_csv(os.path.join(DATA_DIR, f"{sym}.csv"))
        exp_time = meta.get(sym, {}).get("expiration_time", 0)
        if exp_time > 0:
            data_mgc[sym] = {
                "rates": df.to_dict('records'),
                "expiration_time": exp_time,
                "sessions": meta.get(sym, {}).get("sessions"),
            }

    if not data_mgc:
        return {"error": "No CMX.MGC contracts with known expiration."}

    sorted_syms = sorted(data_mgc.keys(), key=lambda x: data_mgc[x]['expiration_time'])

    # Both legs share the mts server clock -> align directly on timestamp, no offset.
    map_apx = {int(r['time']): r for r in rates_apx}

    spreads_by_sym = {sym: {} for sym in sorted_syms}
    dte_by_sym = {sym: {} for sym in sorted_syms}

    for sym in sorted_syms:
        rates_mgc = data_mgc[sym]['rates']
        exp_time = data_mgc[sym]['expiration_time']
        sessions_mgc = data_mgc[sym]['sessions']
        map_mgc = {int(r['time']): r for r in rates_mgc}

        common_times = sorted(set(map_apx.keys()) & set(map_mgc.keys()))
        for t in common_times:
            # Keep only when BOTH legs are inside their safe (5-min buffered) window
            if not is_time_in_safe_window(t, sessions_apx):
                continue
            if not is_time_in_safe_window(t, sessions_mgc):
                continue
            dte = (exp_time - t) / 86400.0
            if dte < 0:
                continue
            spread = map_mgc[t]['close'] - map_apx[t]['close']  # MGC - APX (shrinks toward expiry)
            spreads_by_sym[sym][t] = spread
            dte_by_sym[sym][t] = dte

    # Chart 1: Spread vs Days-to-Expiration (countdown)
    traces_dte = []
    for sym in sorted_syms:
        times = sorted(spreads_by_sym[sym].keys(), reverse=True)
        x_vals = [round(dte_by_sym[sym][t], 3) for t in times]
        y_vals = [round(spreads_by_sym[sym][t], 2) for t in times]
        if x_vals:
            traces_dte.append({'x': x_vals, 'y': y_vals, 'name': sym, 'mode': 'lines',
                               'type': 'scatter', 'line': {'width': 1.5}})

    # Chart 2: Spread vs chronological time
    traces_time = []
    for sym in sorted_syms:
        times = sorted(spreads_by_sym[sym].keys())
        x_vals = [datetime.fromtimestamp(t).strftime('%Y-%m-%d %H:%M:%S') for t in times]
        y_vals = [round(spreads_by_sym[sym][t], 2) for t in times]
        if x_vals:
            traces_time.append({'x': x_vals, 'y': y_vals, 'name': sym, 'mode': 'lines',
                                'type': 'scatter', 'line': {'width': 1.5}})

    # Chart 3: Inter-delivery calendar spreads vs nearest contract
    traces_calendar = []
    if len(sorted_syms) >= 2:
        nearest_sym = sorted_syms[0]
        colors = ['#f97316', '#8b5cf6', '#ef4444', '#10b981', '#3b82f6', '#f59e0b']
        for i, sym in enumerate(sorted_syms[1:]):
            color = colors[i % len(colors)]
            x_vals, y_vals = [], []
            common_times = sorted(set(spreads_by_sym[sym].keys()) & set(spreads_by_sym[nearest_sym].keys()))
            for t in common_times:
                x_vals.append(datetime.fromtimestamp(t).strftime('%Y-%m-%d %H:%M:%S'))
                y_vals.append(round(spreads_by_sym[sym][t] - spreads_by_sym[nearest_sym][t], 2))
            if x_vals:
                traces_calendar.append({'x': x_vals, 'y': y_vals, 'name': f'{sym} - {nearest_sym}',
                                        'mode': 'lines', 'type': 'scatter',
                                        'line': {'width': 1.5, 'color': color}})

    # Fair-value regression over all DTE points
    all_x, all_y = [], []
    for tr in traces_dte:
        all_x.extend(tr['x'])
        all_y.extend(tr['y'])

    if len(all_x) > 1:
        n = len(all_x)
        sum_x, sum_y = sum(all_x), sum(all_y)
        sum_xx = sum(x * x for x in all_x)
        sum_xy = sum(x * y for x, y in zip(all_x, all_y))
        denominator = n * sum_xx - sum_x ** 2
        if denominator != 0:
            m = (n * sum_xy - sum_x * sum_y) / denominator
            c = (sum_y - m * sum_x) / n
            mean_y = sum_y / n
            ss_tot = sum((y - mean_y) ** 2 for y in all_y)
            ss_res = sum((y - (m * x + c)) ** 2 for x, y in zip(all_x, all_y))
            r2 = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
            with open(os.path.join(DATA_DIR, "regression.json"), "w") as f:
                json.dump({"slope": m, "intercept": c, "r2": r2, "points": n}, f, indent=4)
            min_x, max_x = min(all_x), max(all_x)
            traces_dte.append({
                'x': [max_x, min_x],
                'y': [round(m * max_x + c, 2), round(m * min_x + c, 2)],
                'name': f'Fair Value (y={m:.4f}x{c:+.4f}, R2={r2:.3f})',
                'mode': 'lines',
                'line': {'width': 0.8, 'color': '#facc15', 'dash': 'dash'}
            })

    return {
        "traces_dte": traces_dte,
        "traces_time": traces_time,
        "traces_calendar": traces_calendar,
    }


if __name__ == "__main__":
    fetch_and_store()
    print("Chart data size:", len(str(get_chart_data())))
