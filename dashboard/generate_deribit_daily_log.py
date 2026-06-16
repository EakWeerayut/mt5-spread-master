import sys
import os
import json
import datetime
from collections import defaultdict

START_DATE = '2026-05-17'
OUT_FILE = 'C:\\Users\\asus\\.gemini\\antigravity\\brain\\b7db3e8d-7e2c-4b31-9e15-261d21c7e9cf\\deribit_daily_log.md'

def generate_daily_log(cache_file='.deribit_logs_cache.json'):
    if not os.path.exists(cache_file):
        print(f"Error: Cache file {cache_file} not found. Run deribit.fetch() first.")
        return

    with open(cache_file, "r", encoding="utf-8") as f:
        all_logs = json.load(f)

    all_logs.sort(key=lambda x: x.get('timestamp', 0))

    # Group logs by date
    logs_by_date = defaultdict(list)
    for log in all_logs:
        if log.get('_currency', log.get('currency')) != 'BTC': 
            continue
        ts = log.get('timestamp', 0)
        dt = datetime.datetime.fromtimestamp(ts/1000.0, tz=datetime.timezone.utc)
        date_str = dt.strftime('%Y-%m-%d')
        logs_by_date[date_str].append(log)

    today_str = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d')
    
    daily_stats = {}
    
    curr_d = datetime.datetime.strptime(START_DATE, '%Y-%m-%d')
    today_d = datetime.datetime.strptime(today_str, '%Y-%m-%d')
    
    prev_asset = 0.0
    prev_asset_adj = 0.0
    
    # Process up to today
    while curr_d <= today_d:
        d_str = curr_d.strftime('%Y-%m-%d')
        daily_stats[d_str] = {'asset': prev_asset, 'asset_adj': prev_asset_adj, 'funding': 0.0, 'transfer': 0.0, 'pnl': 0.0}
        
        if d_str in logs_by_date:
            logs = logs_by_date[d_str]
            for log in logs:
                log_type = log.get('type')
                change = log.get('change', 0.0)
                
                if log_type in ('deposit', 'withdrawal'):
                    daily_stats[d_str]['transfer'] += change
                elif log_type == 'settlement':
                    if 'interest_pl' in log:
                        daily_stats[d_str]['funding'] += log['interest_pl']
                        
            # Use the exact balance and equity from the LAST transaction of the day
            last_log = logs[-1]
            if 'balance' in last_log:
                daily_stats[d_str]['asset'] = last_log['balance']
                daily_stats[d_str]['asset_adj'] = last_log.get('equity', last_log['balance'])
            else:
                # Fallback if old log format doesn't have balance
                daily_stats[d_str]['asset'] = prev_asset + sum(l.get('change', 0) for l in logs)
                daily_stats[d_str]['asset_adj'] = daily_stats[d_str]['asset']
                
        # Calculate PnL (including realized and unrealized) using the mathematical formula:
        # PnL = AssetAdj(T) - AssetAdj(T-1) - Funding - Transfer
        pnl = daily_stats[d_str]['asset_adj'] - prev_asset_adj - daily_stats[d_str]['funding'] - daily_stats[d_str]['transfer']
        # Don't show crazy PnL on the very first day due to missing history
        if prev_asset_adj == 0 and daily_stats[d_str]['asset_adj'] > 0:
            pnl = 0.0
            
        daily_stats[d_str]['pnl'] = pnl
        
        prev_asset = daily_stats[d_str]['asset']
        prev_asset_adj = daily_stats[d_str]['asset_adj']
        
        curr_d += datetime.timedelta(days=1)

    out = []
    out.append('# 📅 Deribit Daily Log (From 17 May 2026)')
    out.append('> **Note:** The `Asset Adj` comes directly from Deribit\'s internal `equity` snapshot at the end of each day. PnL is mathematically derived.')
    out.append('')
    out.append('| Date | Asset | Asset Adj | Funding (Daily) | Realized PnL | Transfer |')
    out.append('| :--- | :--- | :--- | :--- | :--- | :--- |')
    
    curr_d = datetime.datetime.strptime(START_DATE, '%Y-%m-%d')
    while curr_d <= today_d:
        d_str = curr_d.strftime('%Y-%m-%d')
        st = daily_stats[d_str]
        out.append(f"| {d_str} | {st['asset']:.4f} | {st['asset_adj']:.4f} | {st['funding']:.6f} | {st['pnl']:.6f} | {st['transfer']:.4f} |")
        curr_d += datetime.timedelta(days=1)

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print(f"Daily log successfully written to {OUT_FILE}")

if __name__ == '__main__':
    generate_daily_log()
