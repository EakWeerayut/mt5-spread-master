import os
import json
import time
import datetime
from collections import defaultdict
from dotenv import load_dotenv
from binance.client import Client

DB_FILE = '.binance_balances_db.json'
CACHE_FILE = '.binance_logs_cache.json'
OUT_FILE = 'C:\\Users\\asus\\.gemini\\antigravity\\brain\\b7db3e8d-7e2c-4b31-9e15-261d21c7e9cf\\binance_daily_log.md'
START_DATE = '2026-05-17'

usd_coins = {'USDT', 'USDC', 'BUSD', 'FDUSD'}

def load_json(filepath):
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r') as f: return json.load(f)
        except: pass
    return {}

def save_json(data, filepath):
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)

def fetch_flows_cache(client, cache, days_back=30):
    print("Fetching flow data from Binance API...")
    end_time = int(time.time() * 1000)
    start_time = end_time - (days_back * 24 * 60 * 60 * 1000)

    # 1. Spot Trades
    print("Fetching Spot Trades...")
    account_info = client.get_account()
    symbols_to_check = set()
    for bal in account_info.get('balances', []):
        asset = bal['asset']
        if asset.startswith('LD'): asset = asset[2:]
        if asset not in ('USDT', 'USDC', 'BUSD', 'BTC'):
            symbols_to_check.add(f"{asset}USDT")
            symbols_to_check.add(f"{asset}USDC")
            symbols_to_check.add(f"{asset}BTC")
    
    trade_data = []
    for sym in list(symbols_to_check)[:20]:
        try:
            trades = client.get_my_trades(symbol=sym, startTime=start_time, endTime=end_time)
            trade_data.extend(trades)
        except: pass
    try:
        trade_data.extend(client.get_my_trades(symbol='BTCUSDT', startTime=start_time, endTime=end_time))
        trade_data.extend(client.get_my_trades(symbol='BTCUSDC', startTime=start_time, endTime=end_time))
    except: pass

    existing_trades = {f"{t['symbol']}_{t['id']}": t for t in cache.get('spot_trades', [])}
    for t in trade_data: existing_trades[f"{t['symbol']}_{t['id']}"] = t
    cache['spot_trades'] = sorted(list(existing_trades.values()), key=lambda x: x['time'])

    # 2. Futures Income
    print("Fetching Futures Income...")
    try:
        inc = client.futures_income_history(startTime=start_time, endTime=end_time, limit=1000)
        existing_inc = {f"{i['time']}_{i['tranId']}": i for i in cache.get('futures_income', [])}
        for i in inc: existing_inc[f"{i['time']}_{i['tranId']}"] = i
        cache['futures_income'] = sorted(list(existing_inc.values()), key=lambda x: x['time'])
    except Exception as e:
        print("Futures API not enabled or error:", e)

    # 3. Deposits & Withdrawals
    print("Fetching Deposits & Withdrawals...")
    try:
        deps = client.get_deposit_history(startTime=start_time, endTime=end_time)
        existing_deps = {d['txId']: d for d in cache.get('deposits', []) if 'txId' in d}
        for d in deps: existing_deps[d['txId']] = d
        cache['deposits'] = sorted(list(existing_deps.values()), key=lambda x: x['insertTime'])

        wds = client.get_withdraw_history(startTime=start_time, endTime=end_time)
        existing_wds = {w['id']: w for w in cache.get('withdrawals', [])}
        for w in wds: existing_wds[w['id']] = w
        cache['withdrawals'] = sorted(list(existing_wds.values()), key=lambda x: x.get('applyTime', ''))
    except Exception as e:
        print("Transfer error:", e)

    # 4. Earn Rewards
    print("Fetching Simple Earn Rewards...")
    earn_data = []
    for t in ['BONUS', 'REALTIME', 'REWARDS']:
        try:
            res = client._request_margin_api('get', 'simple-earn/flexible/history/rewardsRecord', signed=True, data={'type': t, 'size': 100})
            if res and 'rows' in res: earn_data.extend(res['rows'])
        except: pass
    existing_earn = {f"{i['time']}_{i['asset']}": i for i in cache.get('earn_rewards', [])}
    for i in earn_data: existing_earn[f"{i['time']}_{i['asset']}"] = i
    cache['earn_rewards'] = sorted(list(existing_earn.values()), key=lambda x: x['time'])

    cache['last_fetch'] = time.time()
    save_json(cache, CACHE_FILE)
    return cache

def get_live_balance(client):
    print("Fetching Live Balances...")
    btc_bal = 0.0
    usd_bal = 0.0
    
    # 1. Spot (ignoring LD tokens)
    try:
        acc = client.get_account()
        for b in acc.get('balances', []):
            asset = b['asset']
            if asset.startswith('LD'): continue # Ignore LD tokens, we'll get real values from Flex API
            total = float(b['free']) + float(b['locked'])
            if total == 0: continue
            if asset == 'BTC': btc_bal += total
            elif asset in usd_coins: usd_bal += total
    except Exception as e: print("Spot error:", e)

    # 2. Simple Earn Flexible
    try:
        flex = client.get_simple_earn_flexible_product_position()
        if 'rows' in flex:
            for r in flex['rows']:
                asset = r['asset']
                total = float(r['totalAmount'])
                if total == 0: continue
                if asset == 'BTC': btc_bal += total
                elif asset in usd_coins: usd_bal += total
    except Exception as e: print("Earn error:", e)

    # 3. Futures
    try:
        f_acc = client.futures_account()
        for a in f_acc.get('assets', []):
            asset = a['asset']
            total = float(a['walletBalance'])
            if total == 0: continue
            if asset == 'BTC': btc_bal += total
            elif asset in usd_coins: usd_bal += total
    except Exception as e: print("Futures error:", e)

    return btc_bal, usd_bal

def calculate_daily_flows(cache):
    flows = defaultdict(lambda: {
        'btc_trade': 0.0, 'btc_fee': 0.0, 'btc_transfer': 0.0, 'btc_earn': 0.0,
        'usd_trade': 0.0, 'usd_fee': 0.0, 'usd_funding': 0.0, 'usd_pnl': 0.0, 'usd_transfer': 0.0, 'usd_earn': 0.0
    })

    # 1. Spot Trades
    for tr in cache.get('spot_trades', []):
        dt = datetime.datetime.fromtimestamp(tr['time']/1000.0, tz=datetime.timezone.utc)
        d_str = dt.strftime('%Y-%m-%d')
        
        sym, is_buyer = tr['symbol'], tr['isBuyer']
        qty, quote_qty = float(tr['qty']), float(tr['quoteQty'])
        comm, comm_asset = float(tr['commission']), tr['commissionAsset']
        
        base_asset, quote_asset = None, None
        for q in usd_coins:
            if sym.endswith(q):
                quote_asset, base_asset = q, sym[:-len(q)]
                break
        if not quote_asset and sym.endswith('BTC'):
            quote_asset, base_asset = 'BTC', sym[:-3]
        
        if base_asset == 'BTC': flows[d_str]['btc_trade'] += (qty if is_buyer else -qty)
        elif base_asset in usd_coins: flows[d_str]['usd_trade'] += (qty if is_buyer else -qty)
            
        if quote_asset == 'BTC': flows[d_str]['btc_trade'] += (-quote_qty if is_buyer else quote_qty)
        elif quote_asset in usd_coins: flows[d_str]['usd_trade'] += (-quote_qty if is_buyer else quote_qty)
            
        if comm_asset == 'BTC': flows[d_str]['btc_fee'] -= comm
        elif comm_asset in usd_coins: flows[d_str]['usd_fee'] -= comm

    # 2. Futures Income
    for inc in cache.get('futures_income', []):
        dt = datetime.datetime.fromtimestamp(inc['time']/1000.0, tz=datetime.timezone.utc)
        d_str = dt.strftime('%Y-%m-%d')
        asset, val, itype = inc['asset'], float(inc['income']), inc['incomeType']
        
        if asset in usd_coins:
            if itype == 'FUNDING_FEE': flows[d_str]['usd_funding'] += val
            elif itype == 'REALIZED_PNL': flows[d_str]['usd_pnl'] += val
            elif itype == 'COMMISSION': flows[d_str]['usd_fee'] += val

    # 3. Transfers
    for dep in cache.get('deposits', []):
        dt = datetime.datetime.fromtimestamp(dep['insertTime']/1000.0, tz=datetime.timezone.utc)
        d_str, asset, val = dt.strftime('%Y-%m-%d'), dep['coin'], float(dep['amount'])
        if asset == 'BTC': flows[d_str]['btc_transfer'] += val
        elif asset in usd_coins: flows[d_str]['usd_transfer'] += val
            
    for wd in cache.get('withdrawals', []):
        if 'applyTime' not in wd: continue
        dt = datetime.datetime.strptime(wd['applyTime'], "%Y-%m-%d %H:%M:%S").replace(tzinfo=datetime.timezone.utc)
        d_str, asset, val = dt.strftime('%Y-%m-%d'), wd['coin'], float(wd['amount'])
        if asset == 'BTC': flows[d_str]['btc_transfer'] -= val
        elif asset in usd_coins: flows[d_str]['usd_transfer'] -= val

    # 4. Earn Rewards
    for earn in cache.get('earn_rewards', []):
        dt = datetime.datetime.fromtimestamp(earn['time']/1000.0, tz=datetime.timezone.utc)
        d_str, asset, val = dt.strftime('%Y-%m-%d'), earn['asset'], float(earn['rewards'])
        if asset == 'BTC': flows[d_str]['btc_earn'] += val
        elif asset in usd_coins: flows[d_str]['usd_earn'] += val

    return dict(flows)

def generate_log():
    load_dotenv()
    client = Client(os.getenv('BINANCE_API_KEY'), os.getenv('BINANCE_API_SECRET'))
    server_time = client.get_server_time()
    client.timestamp_offset = server_time['serverTime'] - int(time.time() * 1000)
    
    cache = load_json(CACHE_FILE)
    if time.time() - cache.get('last_fetch', 0) > 3600:
        cache = fetch_flows_cache(client, cache, days_back=30)
    
    flows = calculate_daily_flows(cache)
    live_btc, live_usd = get_live_balance(client)
    
    today_str = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d')
    db = load_json(DB_FILE)
    
    def get_net(asset_type, d_str):
        f = flows.get(d_str, {})
        if asset_type == 'btc':
            return f.get('btc_trade',0) + f.get('btc_fee',0) + f.get('btc_transfer',0) + f.get('btc_earn',0)
        else:
            return f.get('usd_trade',0) + f.get('usd_fee',0) + f.get('usd_funding',0) + f.get('usd_pnl',0) + f.get('usd_transfer',0) + f.get('usd_earn',0)

    # 1. Reverse Calculation Initialization
    if not db:
        print("Database is empty. Initializing backwards from today...")
        db[today_str] = {'btc': live_btc, 'usd': live_usd}
        
        curr_d = datetime.datetime.strptime(today_str, '%Y-%m-%d')
        while True:
            d_str = curr_d.strftime('%Y-%m-%d')
            if d_str <= START_DATE:
                break
            prev_d = curr_d - datetime.timedelta(days=1)
            prev_d_str = prev_d.strftime('%Y-%m-%d')
            
            prev_btc = db[d_str]['btc'] - get_net('btc', d_str)
            prev_usd = db[d_str]['usd'] - get_net('usd', d_str)
            db[prev_d_str] = {'btc': prev_btc, 'usd': prev_usd}
            curr_d = prev_d
            
        del db[today_str]
        save_json(db, DB_FILE)
    else:
        # 2. Forward Calculation (Offline Recovery)
        print("Database loaded. Forward calculating if missing days...")
        db_dates = sorted(db.keys())
        last_date_str = db_dates[-1]
        
        last_d = datetime.datetime.strptime(last_date_str, '%Y-%m-%d')
        today_d = datetime.datetime.strptime(today_str, '%Y-%m-%d')
        
        curr_d = last_d + datetime.timedelta(days=1)
        while curr_d < today_d:
            d_str = curr_d.strftime('%Y-%m-%d')
            prev_str = (curr_d - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
            
            new_btc = db[prev_str]['btc'] + get_net('btc', d_str)
            new_usd = db[prev_str]['usd'] + get_net('usd', d_str)
            db[d_str] = {'btc': new_btc, 'usd': new_usd}
            curr_d += datetime.timedelta(days=1)
            
        save_json(db, DB_FILE)

    # 3. Output Markdown
    print("Generating markdown...")
    out = []
    out.append("# 📅 Binance Daily Log (From 17 May 2026)")
    out.append("## 🟠 BTC Log")
    out.append("| Date | Asset (All) | Trade | Deposit/Withdraw | Earn (Actual) | Unexplained Flow |")
    out.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
    
    curr_d = datetime.datetime.strptime(START_DATE, '%Y-%m-%d')
    today_d = datetime.datetime.strptime(today_str, '%Y-%m-%d')
    
    while curr_d <= today_d:
        d_str = curr_d.strftime('%Y-%m-%d')
        f = flows.get(d_str, {})
        asset = db[d_str]['btc'] if d_str in db else live_btc
        prev_str = (curr_d - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
        
        if prev_str in db:
            unexplained = asset - db[prev_str]['btc'] - get_net('btc', d_str)
        else:
            unexplained = 0.0

        warn = " ⚠️" if abs(unexplained) > 0.01 else ""
        t_trade = f.get('btc_trade',0) + f.get('btc_fee',0)
        out.append(f"| {d_str} | {asset:.8f} | {t_trade:.8f} | {f.get('btc_transfer',0):.8f} | {f.get('btc_earn',0):.8f} | {unexplained:.8f}{warn} |")
        curr_d += datetime.timedelta(days=1)

    out.append("")
    out.append("## 💵 USD Log")
    out.append("| Date | Asset (All) | Trade | Funding | Fee | PnL | Dep/With | Earn (Actual) | Unexplained Flow |")
    out.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    
    curr_d = datetime.datetime.strptime(START_DATE, '%Y-%m-%d')
    while curr_d <= today_d:
        d_str = curr_d.strftime('%Y-%m-%d')
        f = flows.get(d_str, {})
        asset = db[d_str]['usd'] if d_str in db else live_usd
        prev_str = (curr_d - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
        
        if prev_str in db:
            unexplained = asset - db[prev_str]['usd'] - get_net('usd', d_str)
        else:
            unexplained = 0.0

        warn = " ⚠️" if abs(unexplained) > 10.0 else ""
        out.append(f"| {d_str} | {asset:.4f} | {f.get('usd_trade',0):.4f} | {f.get('usd_funding',0):.4f} | {f.get('usd_fee',0):.4f} | {f.get('usd_pnl',0):.4f} | {f.get('usd_transfer',0):.4f} | {f.get('usd_earn',0):.4f} | {unexplained:.4f}{warn} |")
        curr_d += datetime.timedelta(days=1)
        
    with open(OUT_FILE, "w", encoding="utf-8") as file:
        file.write("\n".join(out))
    print(f"Log written to {OUT_FILE}")

if __name__ == '__main__':
    generate_log()
