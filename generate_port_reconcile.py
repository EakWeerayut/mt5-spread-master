import sys
import os
import json
from datetime import datetime
import re

sys.path.insert(0, r"C:\Git\credentials")
sys.path.insert(0, r"C:\Git\portfolio-tracker")

import pandas as pd
from central_creds import get_credentials
import gspread

from connectors.binance import fetch as fetch_binance
from connectors.deribit import fetch as fetch_deribit
from connectors.mt5 import fetch as fetch_mt5

def get_ledger_positions():
    creds = get_credentials(["https://www.googleapis.com/auth/spreadsheets.readonly"])
    gc = gspread.authorize(creds)
    doc_id = "1WKhr9-7rCIPTLrzHi06aQJiKobp2QRnmuETC2gx8Y4I"
    sh = gc.open_by_key(doc_id)
    ws = sh.worksheet("Ledger")
    vals = ws.get_all_values()
    
    positions = {}
    for row in vals[2:]:
        col_o = row[14] if len(row) > 14 else ""
        if col_o.strip() == "":
            sym = row[2] if len(row) > 2 else ""
            price_str = row[4] if len(row) > 4 else "0"
            size_str = row[5] if len(row) > 5 else "0"
            if sym.strip() and size_str.strip():
                try:
                    size_val = float(size_str.replace(",", ""))
                except:
                    continue
                try:
                    price_val = float(price_str.replace(",", ""))
                except:
                    price_val = 0.0
                if sym not in positions:
                    positions[sym] = {"size": 0.0, "price": price_val}
                positions[sym]["size"] += size_val
    return positions

def clean_symbol(sym):
    sym = str(sym)
    sym_clean = re.sub(r'\s*\([^)]*\)', '', sym)
    return re.sub(r'[\(\)（）]', '', sym_clean).strip()

def get_actual_positions():
    actuals = {}
    
    print("Fetching Binance...")
    try:
        b_data = fetch_binance()
        for p in b_data.get("futures_positions", []):
            sym = p["symbol"] + ".P"
            if sym.startswith("LD"): continue
            amt = float(p["position_amt"])
            price = float(p.get("entryPrice", p.get("markPrice", 0)))
            if sym not in actuals:
                actuals[sym] = {"size": 0.0, "price": price}
            actuals[sym]["size"] += amt
            
        for p in b_data.get("spot_balances", []):
            sym = p["asset"]
            if sym.startswith("LD"): continue
            amt = float(p["free"]) + float(p["locked"])
            if amt > 0:
                if sym not in actuals:
                    actuals[sym] = {"size": 0.0, "price": 0.0}
                actuals[sym]["size"] += amt
    except Exception as e:
        print("Binance error:", e)

    print("Fetching Deribit...")
    try:
        d_data = fetch_deribit()
        for p in d_data.get("open_positions", []):
            sym = p["instrument"]
            amt = float(p["size"])
            price = float(p.get("average_price", p.get("mark_price", 0)))
            if sym not in actuals:
                actuals[sym] = {"size": 0.0, "price": price}
            actuals[sym]["size"] += amt
    except Exception as e:
        print("Deribit error:", e)

    print("Fetching MT5...")
    try:
        m_data = fetch_mt5()
        for acc in m_data.get("accounts", []):
            for p in acc.get("open_positions", []):
                sym = p["symbol"]
                amt = float(p["volume"])
                if p["type"] == "Sell":
                    amt = -amt
                price = float(p.get("price_open", p.get("price_current", 0)))
                if sym not in actuals:
                    actuals[sym] = {"size": 0.0, "price": price}
                actuals[sym]["size"] += amt
    except Exception as e:
        print("MT5 error:", e)
        
    print("Reading SBI/LIB...")
    try:
        df = pd.read_csv(r"C:\Git\portfolio-tracker\sbi_holdings.csv")
        for _, row in df.iterrows():
            sym = clean_symbol(row['symbol'])
            amt = float(row['amount'])
            
            price = float(row.get('avg', 0))
            if pd.isna(price) or price == 0:
                price = float(row.get('market', 0))
                if pd.isna(price): price = 0.0
            
            is_tfex = sym.startswith("S50") or bool(re.search(r'[FGHJKMNQUVXZ]\d{2}$', sym))
            is_usdm = sym.startswith("USDM")
            if is_tfex or is_usdm:
                multiplier = 200 if sym.startswith("S50") else 1000
                amt = amt * multiplier
                
            side = str(row.get('side', '')).upper()
            if side and side != 'NAN':
                if "SHORT" in side or "SELL" in side:
                    amt = -abs(amt)
            
            if sym not in actuals:
                actuals[sym] = {"size": 0.0, "price": price}
            actuals[sym]["size"] += amt
    except Exception as e:
        print("SBI/LIB error:", e)
        
    print("Reading RMF...")
    try:
        with open(r"C:\Git\portfolio-tracker\rmf_report.md", "r", encoding="utf-8") as f:
            content = f.read()
            
        lines = content.split('\n')
        in_table = False
        for line in lines:
            if "Symbol | Unit | Value" in line:
                in_table = True
                continue
            if in_table and line.startswith("| :---"):
                continue
            if in_table and line.startswith("|") and "TOTAL" not in line:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 4:
                    sym_raw = parts[1].replace("**", "").strip()
                    if not sym_raw: continue
                    sym = clean_symbol(sym_raw)
                    unit_str = parts[2].replace(",", "")
                    val_str = parts[3].replace(",", "")
                    try:
                        amt = float(unit_str)
                        val = float(val_str)
                        price = val / amt if amt != 0 else 0.0
                        
                        if sym not in actuals:
                            actuals[sym] = {"size": 0.0, "price": 0.0}
                        actuals[sym]["size"] += amt
                        actuals[sym]["price"] = price
                    except ValueError:
                        pass
            if in_table and "TOTAL" in line:
                break
    except Exception as e:
        print("RMF error:", e)
        
    return actuals

def build_html(discrepancies, matched):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Portfolio Reconciliation</title>
    <style>
        :root {{
            --bg-color: #0f172a; --card-bg: rgba(30, 41, 59, 0.7);
            --text-main: #e2e8f0; --text-muted: #94a3b8;
            --accent-green: #10b981; --accent-red: #ef4444;
            --border: rgba(255, 255, 255, 0.08);
        }}
        body {{ font-family: 'Inter', system-ui, sans-serif; background: linear-gradient(135deg, #020617 0%, #0f172a 100%); color: var(--text-main); min-height: 100vh; margin: 0; padding: 20px; display: flex; justify-content: center; font-size: 13px; line-height: 1.4; }}
        .container {{ max-width: 1100px; width: 100%; }}
        h1 {{ font-size: 1.5rem; margin: 0 0 5px 0; color: #38bdf8; }}
        .subtitle {{ color: var(--text-muted); margin-bottom: 20px; font-size: 11px; }}
        table {{ width: 100%; border-collapse: separate; border-spacing: 0; margin-top: 10px; background: var(--card-bg); border-radius: 8px; overflow: hidden; border: 1px solid var(--border); }}
        th, td {{ padding: 12px 15px; text-align: left; border-bottom: 1px solid var(--border); }}
        th {{ background: rgba(0, 0, 0, 0.3); color: var(--text-muted); font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }}
        tr:last-child td {{ border-bottom: none; }}
        .highlight-red {{ color: var(--accent-red); font-weight: bold; }}
        .highlight-green {{ color: var(--accent-green); font-weight: bold; }}
        .section-title {{ font-size: 16px; color: #fff; margin-top: 30px; margin-bottom: 10px; border-bottom: 1px solid var(--border); padding-bottom: 5px; }}
    </style>
</head>
<body>
<div class="container">
    <h1>Portfolio Reconciliation</h1>
    <div class="subtitle">Last Updated: {now}</div>
'''

    if discrepancies:
        html += '<div class="section-title">Discrepancies</div><table>\n'
        html += '<tr><th>Symbol</th><th>Ledger Size</th><th>Actual Size</th><th>Difference</th><th>Notes</th><th>Ledger Price</th><th>Actual Price</th></tr>\n'
        for d in discrepancies:
            sym, exp_s, act_s, diff, notes, exp_p, act_p = d
            color_class = "highlight-red" if diff != 0 else ""
            html += f'<tr><td>{sym}</td><td>{exp_s:,.4f}</td><td>{act_s:,.4f}</td><td class="{color_class}">{diff:,.4f}</td><td class="text-muted">{notes}</td><td>{exp_p:,.4f}</td><td>{act_p:,.4f}</td></tr>\n'
        html += '</table>\n'
    else:
        html += '<p>No discrepancies found!</p>\n'

    if matched:
        html += '<div class="section-title">Matched Positions</div><table>\n'
        html += '<tr><th>Symbol</th><th>Size</th><th>Ledger Price</th><th>Actual Price</th></tr>\n'
        for m in matched:
            sym, size, exp_p, act_p = m
            html += f'<tr><td>{sym}</td><td>{size:,.4f}</td><td>{exp_p:,.4f}</td><td>{act_p:,.4f}</td></tr>\n'
        html += '</table>\n'
        
    html += '''
</div>
</body>
</html>
'''
    return html

def main():
    print("Fetching Ledger...")
    expected = get_ledger_positions()
    actual = get_actual_positions()
    
    all_syms = set(expected.keys()) | set(actual.keys())
    
    discrepancies = []
    matched = []
    log_entries = []
    
    for sym in sorted(all_syms):
        exp = expected.get(sym, {"size": 0.0, "price": 0.0})
        act = actual.get(sym, {"size": 0.0, "price": 0.0})
        
        exp_s = round(exp["size"], 4)
        act_s = round(act["size"], 4)
        exp_p = round(exp["price"], 4)
        act_p = round(act["price"], 4)
        
        if exp_s == 0 and act_s == 0:
            continue
            
        diff_s = round(act_s - exp_s, 4)
        
        if exp_s == 0 and abs(act_s) < 1e-9:
            continue
            
        is_diff = False
        notes = ""
        
        if abs(diff_s) > 1e-9:
            ref_price = exp_p if exp_p > 0 else act_p
            
            is_thb = sym.startswith("K-") or sym.startswith("S50") or sym in ["AWC","CKP","CPNREIT","CRC","DUSIT","HTECH","JMT","M","NFC","PCC","PMC","SCAP","SJWD","THCOM"]
            is_btc = "BTC" in sym or sym == "LDBTC"
            is_usd = "USD" in sym or sym in ["USDT", "USDC"]
            
            if is_thb:
                val = abs(diff_s) * (ref_price if ref_price > 0 else 1.0)
                if val >= 10.0:
                    is_diff = True
            elif is_btc and not is_usd: 
                if abs(diff_s) >= 0.000001:
                    is_diff = True
            else:
                val = abs(diff_s) * (ref_price if ref_price > 0 else 1.0)
                if val >= 1.0:
                    is_diff = True

            if is_diff:
                if act_s == 0 and exp_s != 0:
                    notes = "Missing in actual platforms"
                elif exp_s == 0 and act_s != 0:
                    notes = "Missing in Ledger"
                elif (exp_s > 0 and act_s < 0) or (exp_s < 0 and act_s > 0):
                    notes = "Opposite signs"
                else:
                    notes = "Size mismatch"
                    
        if is_diff:
            discrepancies.append((sym, exp_s, act_s, diff_s, notes, exp_p, act_p))
            log_entries.append({
                "symbol": sym,
                "ledger_size": exp_s,
                "actual_size": act_s,
                "diff": diff_s
            })
        else:
            matched.append((sym, exp_s, exp_p, act_p))

    html_content = build_html(discrepancies, matched)
    
    drive_path = r"C:\Drive\claude-shared\dashboard\port_reconcile.html"
    with open(drive_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"HTML Report generated at {drive_path}")
    
    log_dir = r"C:\Git\Line Bot\data"
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "agents_activity.log")
    
    local_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_message = f"{local_time} | @portfolio-reconciler | Success | Reconciled {len(discrepancies)} discrepancies\n"
    
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(log_message)
    print(f"Logged to {log_file}")

if __name__ == '__main__':
    main()
