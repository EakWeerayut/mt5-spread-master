import json
import csv
import os
import re
from datetime import datetime, timedelta, timezone

def main():
    dates_set = set()
    
    # 1. Binance
    binance_btc = {}
    binance_usd = {}
    if os.path.exists('.binance_balances_db.json'):
        with open('.binance_balances_db.json', 'r') as f:
            data = json.load(f)
            for d, vals in data.items():
                binance_btc[d] = vals.get('btc', 0.0)
                binance_usd[d] = vals.get('usd', 0.0)
                dates_set.add(d)

    # 2. LIB
    lib_thb = {}
    if os.path.exists('.lib_balances_db.json'):
        with open('.lib_balances_db.json', 'r') as f:
            data = json.load(f)
            for d, vals in data.items():
                lib_thb[d] = vals.get('asset', 0.0)
                dates_set.add(d)

    # 3. MT5
    mt5_usd = {}
    if os.path.exists('.mt5_balances_db.json'):
        with open('.mt5_balances_db.json', 'r') as f:
            data = json.load(f)
            for acc, dates_vals in data.items():
                for d, val in dates_vals.items():
                    mt5_usd[d] = mt5_usd.get(d, 0.0) + float(val)
                    dates_set.add(d)

    # 4. SBI
    sbi_thb = {}
    if os.path.exists('daily_simulation.csv'):
        with open('daily_simulation.csv', 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                d = row.get('Date')
                if d:
                    sbi_thb[d] = float(row.get('Total Value', 0.0))
                    dates_set.add(d)

    # 5. RMF
    rmf_thb_sparse = {}
    if os.path.exists('rmf_report.md'):
        with open('rmf_report.md', 'r', encoding='utf-8') as f:
            for line in f:
                # | **13 May 2026** | 4,478,180.36 |
                match = re.search(r'\|\s*\*\*(\d{2}\s+[a-zA-Z]{3}\s+\d{4})\*\*\s*\|\s*([0-9,\.]+)\s*\|', line)
                if match:
                    date_str = match.group(1)
                    val_str = match.group(2).replace(',', '')
                    try:
                        dt = datetime.strptime(date_str, '%d %b %Y')
                        d = dt.strftime('%Y-%m-%d')
                        rmf_thb_sparse[d] = float(val_str)
                        dates_set.add(d)
                    except:
                        pass

    # 6. Deribit
    deribit_btc = {}
    if os.path.exists('.deribit_logs_cache.json'):
        with open('.deribit_logs_cache.json', 'r', encoding='utf-8') as f:
            logs = json.load(f)
            # Sort chronologically to get the last value of the day
            logs.sort(key=lambda x: x.get('timestamp', 0))
            for log in logs:
                if log.get('currency') == 'BTC':
                    ts = log.get('timestamp', 0)
                    dt = datetime.fromtimestamp(ts/1000.0, tz=timezone.utc)
                    d = dt.strftime('%Y-%m-%d')
                    equity = log.get('equity')
                    if equity is None:
                        equity = log.get('balance', 0.0)
                    deribit_btc[d] = float(equity)
                    dates_set.add(d)

    if not dates_set:
        print("No data found.")
        return

    # Create a sorted list of all dates
    sorted_dates = sorted(list(dates_set))
    
    # Forward fill logic
    # We will iterate through dates and carry forward the last known value
    consolidated = []
    
    last_b_btc = 0.0
    last_b_usd = 0.0
    last_l_thb = 0.0
    last_m_usd = 0.0
    last_s_thb = 0.0
    last_r_thb = 0.0
    last_d_btc = 0.0

    for d in sorted_dates:
        if d in binance_btc: last_b_btc = binance_btc[d]
        if d in binance_usd: last_b_usd = binance_usd[d]
        if d in lib_thb: last_l_thb = lib_thb[d]
        if d in mt5_usd: last_m_usd = mt5_usd[d]
        if d in sbi_thb: last_s_thb = sbi_thb[d]
        if d in rmf_thb_sparse: last_r_thb = rmf_thb_sparse[d]
        if d in deribit_btc: last_d_btc = deribit_btc[d]
        
        total_btc = last_b_btc + last_d_btc
        total_thb = last_l_thb + last_s_thb + last_r_thb
        total_usd = last_b_usd + last_m_usd
        
        consolidated.append({
            'Date': d,
            'Total BTC': total_btc,
            'Total THB': total_thb,
            'Total USD': total_usd,
            'Binance BTC': last_b_btc,
            'Deribit BTC': last_d_btc,
            'Binance USD': last_b_usd,
            'MT5 USD': last_m_usd,
            'LIB THB': last_l_thb,
            'SBI THB': last_s_thb,
            'RMF THB': last_r_thb
        })

    # Output to CSV
    with open('consolidated_daily_assets.csv', 'w', newline='') as f:
        fieldnames = ['Date', 'Total BTC', 'Total THB', 'Total USD', 'Binance BTC', 'Deribit BTC', 'Binance USD', 'MT5 USD', 'LIB THB', 'SBI THB', 'RMF THB']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in consolidated:
            writer.writerow(row)
            
    print("Successfully generated consolidated_daily_assets.csv")

    # Output markdown table for recent days (e.g. last 10 days)
    print("\n### Consolidated Daily Assets (Last 10 Days)\n")
    print("| Date | Total BTC | Total THB | Total USD |")
    print("|---|---|---|---|")
    for row in consolidated[-10:]:
        print(f"| {row['Date']} | {row['Total BTC']:.8f} | {row['Total THB']:,.2f} | {row['Total USD']:,.2f} |")

if __name__ == '__main__':
    main()
