import os
import json
import time
import datetime
from collections import defaultdict
from dotenv import load_dotenv
import MetaTrader5 as mt5

DB_FILE = '.mt5_balances_db.json'
OUT_FILE = 'C:\\Users\\asus\\.gemini\\antigravity\\brain\\b7db3e8d-7e2c-4b31-9e15-261d21c7e9cf\\mt5_daily_log.md'
START_DATE = '2026-05-17'

def load_json(filepath):
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r') as f: return json.load(f)
        except: pass
    return {}

def save_json(data, filepath):
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)

def fetch_account_data(login, password, server, account_name):
    print(f"\n--- Fetching data for Account: {account_name} ({login}) ---")
    if not mt5.initialize(login=int(login), password=password, server=server):
        print(f"Failed to initialize MT5 for account {login}")
        return None

    # 1. Fetch Live Balance
    acc_info = mt5.account_info()
    if acc_info is None:
        print("Failed to get account info")
        mt5.shutdown()
        return None
    live_balance = acc_info.balance

    # 2. Fetch Deals
    date_from = datetime.datetime(2020, 1, 1)
    date_to = datetime.datetime.now() + datetime.timedelta(days=1)
    deals = mt5.history_deals_get(date_from, date_to)
    
    if deals is None:
        print("Failed to get deals")
        deals = []

    mt5.shutdown()
    
    return {
        'live_balance': live_balance,
        'deals': deals
    }

def process_mt5():
    load_dotenv()
    
    accounts = [
        {'login': os.environ.get("MT5_LOGIN"), 'pass': os.environ.get("MT5_PASSWORD"), 'server': os.environ.get("MT5_SERVER"), 'name': os.environ.get("MT5_NAME", "MTS")},
        {'login': os.environ.get("MT5_LOGIN_2"), 'pass': os.environ.get("MT5_PASSWORD_2"), 'server': os.environ.get("MT5_SERVER_2"), 'name': os.environ.get("MT5_NAME_2", "Vantage")},
        {'login': os.environ.get("MT5_LOGIN_3"), 'pass': os.environ.get("MT5_PASSWORD_3"), 'server': os.environ.get("MT5_SERVER_3"), 'name': os.environ.get("MT5_NAME_3", "MTS_2")}
    ]
    
    db = load_json(DB_FILE)
    out_md = ["# 📈 MT5 Daily Logs (From 17 May 2026)\n"]
    
    today_str = datetime.datetime.now().strftime('%Y-%m-%d')
    
    for acc in accounts:
        if not acc['login']: continue
        
        data = fetch_account_data(acc['login'], acc['pass'], acc['server'], acc['name'])
        if not data: continue
        
        acc_id = str(acc['login'])
        if acc_id not in db:
            db[acc_id] = {}
            
        acc_db = db[acc_id]
        live_bal = data['live_balance']
        
        # Calculate daily flows
        flows = defaultdict(lambda: {'pnl': 0.0, 'fee': 0.0, 'swap': 0.0, 'transfer': 0.0})
        
        for deal in data['deals']:
            # deal.time is broker time in seconds
            dt = datetime.datetime.fromtimestamp(deal.time)
            d_str = dt.strftime('%Y-%m-%d')
            
            pnl = 0.0
            transfer = 0.0
            fee = deal.commission + deal.fee
            swap = deal.swap
            
            # mt5 DEAL_TYPE constants
            if deal.type in (2, 3, 6): # BALANCE, CREDIT, BONUS
                transfer += deal.profit
            elif deal.type in (0, 1): # BUY, SELL
                pnl += deal.profit
            elif deal.type in (4, 5, 7): # CHARGE, CORRECTION, COMMISSION
                fee += deal.profit
            else:
                pnl += deal.profit # Fallback
                
            flows[d_str]['pnl'] += pnl
            flows[d_str]['transfer'] += transfer
            flows[d_str]['fee'] += fee
            flows[d_str]['swap'] += swap
            
        def get_net(d_str):
            f = flows.get(d_str, {})
            return f.get('pnl', 0) + f.get('fee', 0) + f.get('swap', 0) + f.get('transfer', 0)

        # 1. Reverse Calculation Initialization
        if not acc_db:
            print(f"Initializing backwards for {acc['name']}...")
            acc_db[today_str] = live_bal
            
            curr_d = datetime.datetime.strptime(today_str, '%Y-%m-%d')
            while True:
                d_str = curr_d.strftime('%Y-%m-%d')
                if d_str <= START_DATE:
                    break
                prev_d = curr_d - datetime.timedelta(days=1)
                prev_d_str = prev_d.strftime('%Y-%m-%d')
                
                # Balance(T-1) = Balance(T) - NetFlows(Today)
                acc_db[prev_d_str] = acc_db[d_str] - get_net(d_str)
                curr_d = prev_d
                
            del acc_db[today_str] # Remove today so it stays dynamic
            
        else:
            # 2. Forward Calculation (Offline Recovery)
            print(f"Forward calculating for {acc['name']}...")
            db_dates = sorted(acc_db.keys())
            last_date_str = db_dates[-1]
            
            last_d = datetime.datetime.strptime(last_date_str, '%Y-%m-%d')
            today_d = datetime.datetime.strptime(today_str, '%Y-%m-%d')
            
            curr_d = last_d + datetime.timedelta(days=1)
            while curr_d < today_d:
                d_str = curr_d.strftime('%Y-%m-%d')
                prev_str = (curr_d - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
                
                acc_db[d_str] = acc_db[prev_str] + get_net(d_str)
                curr_d += datetime.timedelta(days=1)
                
        # Generate Markdown section for this account
        out_md.append(f"## 📊 Account: {acc['name']} ({acc['login']})")
        out_md.append("| Date | USD Balance | PnL | Fee | Swap | Transfer | Unexplained Flow |")
        out_md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        
        curr_d = datetime.datetime.strptime(START_DATE, '%Y-%m-%d')
        today_d = datetime.datetime.strptime(today_str, '%Y-%m-%d')
        
        while curr_d <= today_d:
            d_str = curr_d.strftime('%Y-%m-%d')
            f = flows.get(d_str, {})
            
            if d_str in acc_db:
                asset = acc_db[d_str]
            else:
                asset = live_bal
                
            prev_str = (curr_d - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
            
            if prev_str in acc_db:
                prev_asset = acc_db[prev_str]
                unexplained = asset - prev_asset - get_net(d_str)
            else:
                unexplained = 0.0

            warn = " ⚠️" if abs(unexplained) > 0.01 else ""
            t_pnl = f.get('pnl',0)
            t_fee = f.get('fee',0)
            t_swap = f.get('swap',0)
            t_trans = f.get('transfer',0)
            
            out_md.append(f"| {d_str} | {asset:.2f} | {t_pnl:.2f} | {t_fee:.2f} | {t_swap:.2f} | {t_trans:.2f} | {unexplained:.2f}{warn} |")
            curr_d += datetime.timedelta(days=1)
            
        out_md.append("\n---\n")
        db[acc_id] = acc_db # Update main db

    save_json(db, DB_FILE)
    
    with open(OUT_FILE, "w", encoding="utf-8") as file:
        file.write("\n".join(out_md))
    print(f"\nLog written to {OUT_FILE}")

if __name__ == '__main__':
    process_mt5()
