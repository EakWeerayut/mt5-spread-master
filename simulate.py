import csv
import glob
import re
from collections import defaultdict
from datetime import datetime, timedelta

def main():
    # 1. Parse current portfolio
    current_stocks = {}
    total_stock_value = 0.0
    with open('sbi_holdings.csv', 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row['symbol'] or row['filename'] != 'SBI.jpg': continue
            sym = row['symbol']
            qty = float(row['amount'])
            avg = float(row['avg'])
            
            # Try to match the exact amount from the image for the visible ones
            # For simplicity, we just use the exact values from the user's image where possible
            image_amounts = {
                'AWC': 8945.84, 'CKP': 19861.40, 'CPNREIT': 19226.85, 'CRC': 17835.64,
                'DUSIT': 19587.17, 'HTECH': 19715.29, 'JMT': 21618.96, 'M': 18376.10,
                'NFC': 12250.74, 'PCC': 9732.53
            }
            if sym in image_amounts:
                amount = image_amounts[sym]
                # fix avg cost for precision based on amount
                avg = amount / qty
            else:
                # For SJWD we know exact buy amount
                if sym == 'SJWD': amount = 20517.98
                # SCAP bought 18000 for 19457.06 -> sold 4000 for ... cost basis is proportional
                elif sym == 'SCAP': amount = 19457.06 * (14000/18000)
                else: amount = qty * avg
                
            current_stocks[sym] = {'qty': qty, 'avg': avg, 'amount': amount}
            total_stock_value += amount

    current_cash = 30432.11

    # 2. Parse all transactions
    transactions = []
    
    # 2.1 Transfer In/Out
    # Based on our previous output:
    # 2026-04-27 In 200
    # 2026-04-28 In 32000
    # 2026-05-18 In 28000, Out 28000
    # 2026-05-26 In 10000
    transactions.append({'date': '2026-04-27', 'type': 'Transfer In', 'amount': 200.00})
    transactions.append({'date': '2026-04-28', 'type': 'Transfer In', 'amount': 32000.00})
    transactions.append({'date': '2026-05-18', 'type': 'Transfer In', 'amount': 28000.00})
    transactions.append({'date': '2026-05-18', 'type': 'Transfer Out', 'amount': 28000.00})
    transactions.append({'date': '2026-05-26', 'type': 'Transfer In', 'amount': 10000.00})
    
    # 2.2 Trades
    for file in glob.glob('sbi_trade_*.txt'):
        with open(file, 'r', encoding='utf-8') as f:
            for line in f:
                match = re.match(r'(BU|SE)-(\d{4})(\d{2})(\d{2})-[\w-]+\s+(\w+)\s+([\d,]+)\s+[\d\.]+\s+([\d,\.]+)\s+[\d\.]+\s+[\d\.]+\s+[\d\.]+\s+[\d\.]+\s+([\d,\.]+)', line)
                if match:
                    side, y, m, d, sym, qty, amt, net = match.groups()
                    qty = float(qty.replace(',', ''))
                    net = float(net.replace(',', ''))
                    transactions.append({
                        'date': f"{y}-{m}-{d}",
                        'type': side,
                        'symbol': sym,
                        'qty': qty,
                        'net': net
                    })
                    
    # Sort transactions descending by date
    transactions.sort(key=lambda x: x['date'], reverse=True)
    
    # Group by date for daily simulation
    daily_txs = defaultdict(list)
    for tx in transactions:
        daily_txs[tx['date']].append(tx)
        
    # We want to simulate from today back to 2026-04-17
    # We will generate a daily log
    start_date = datetime(2026, 6, 17)
    end_date = datetime(2026, 4, 17)
    
    current_date = start_date
    cash = current_cash
    stocks = {k: v.copy() for k, v in current_stocks.items()}
    
    daily_history = []
    
    while current_date >= end_date:
        date_str = current_date.strftime("%Y-%m-%d")
        
        # Calculate current stock value
        stock_value = sum(s['amount'] for s in stocks.values() if s['qty'] > 0)
        
        daily_history.append({
            'date': date_str,
            'cash': cash,
            'stock_value': stock_value,
            'total': cash + stock_value
        })
        
        # Undo transactions of this date to get the state for the PREVIOUS day
        if date_str in daily_txs:
            for tx in daily_txs[date_str]:
                if tx['type'] == 'Transfer In':
                    cash -= tx['amount']
                elif tx['type'] == 'Transfer Out':
                    cash += tx['amount']
                elif tx['type'] == 'BU':
                    # Undo buy: increase cash, remove shares and cost
                    cash += tx['net']
                    sym = tx['symbol']
                    if sym in stocks:
                        stocks[sym]['qty'] -= tx['qty']
                        stocks[sym]['amount'] -= tx['net']
                        if stocks[sym]['qty'] <= 0:
                            stocks[sym]['qty'] = 0
                            stocks[sym]['amount'] = 0
                        else:
                            stocks[sym]['avg'] = stocks[sym]['amount'] / stocks[sym]['qty']
                elif tx['type'] == 'SE':
                    # Undo sell: decrease cash, ADD shares and cost back
                    cash -= tx['net']
                    sym = tx['symbol']
                    if sym not in stocks:
                        stocks[sym] = {'qty': 0, 'amount': 0, 'avg': 0}
                    
                    # What was the cost of the sold shares? 
                    # If we don't know the exact historical cost, we assume it's roughly the sell amount or we could just use the current avg if any.
                    # For a perfect simulation, we need the cost basis. 
                    # If the stock was fully sold out (qty currently 0), we don't have its avg cost.
                    # Let's see:
                    # SEAFCO (sold 4100 on 06-08 for 12043.43). We don't have buy data. Let's assume cost = net.
                    # PCC (sold 3500 on 06-04). We know PCC avg cost today is 2.8625 (9732.53/3400). So sold cost was 3500 * 2.8625 = 10018.78
                    # SCAP (sold 4000 on 06-02). Avg cost is 19457.06/18000 = 1.080947. Sold cost = 4000 * 1.080947 = 4323.79
                    # BLC (sold 4900 on 05-12). Buy was 4900 for 19421.01. So sold cost = 19421.01
                    # BAM (sold 2600 on 05-11). Unknown buy. Assume cost = net (17144.95)
                    # BEC (sold 6500 on 05-07). Unknown buy. Assume cost = net (11689.73)
                    
                    cost_to_add = tx['net'] # fallback
                    if sym == 'PCC': cost_to_add = 3500 * (9732.53/3400)
                    if sym == 'SCAP': cost_to_add = 4000 * (19457.06/18000)
                    if sym == 'BLC': cost_to_add = 19421.01
                    
                    stocks[sym]['qty'] += tx['qty']
                    stocks[sym]['amount'] += cost_to_add
                    stocks[sym]['avg'] = stocks[sym]['amount'] / stocks[sym]['qty']
                    
        current_date -= timedelta(days=1)
        
    # Write historical daily balances to a csv
    with open('daily_simulation.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['Date', 'Cash', 'Stock Value', 'Total Value'])
        for row in daily_history:
            writer.writerow([row['date'], f"{row['cash']:.2f}", f"{row['stock_value']:.2f}", f"{row['total']:.2f}"])
            
    # Print the portfolio exactly 2 months ago (which is the state after undoing everything down to 2026-04-17)
    print("Portfolio on 2026-04-17:")
    print(f"{'Stock':<10} | {'On Hand':<10} | {'Avg Cost':<10} | {'Amount':<10}")
    print("-" * 49)
    for sym, data in sorted(stocks.items()):
        if data['qty'] > 0:
            print(f"{sym:<10} | {data['qty']:<10.0f} | {data['avg']:<10.2f} | {data['amount']:<10.2f}")
    
if __name__ == '__main__':
    main()
