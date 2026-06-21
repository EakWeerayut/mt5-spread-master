import csv
import glob
import re
from collections import defaultdict
from datetime import datetime, timedelta

def main():
    current_stocks = {}
    with open('sbi_holdings.csv', 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row['symbol'] or row['filename'] != 'SBI.jpg': continue
            sym = row['symbol']
            qty = float(row['amount'])
            avg = float(row['avg'])
            image_amounts = {
                'AWC': 8945.84, 'CKP': 19861.40, 'CPNREIT': 19226.85, 'CRC': 17835.64,
                'DUSIT': 19587.17, 'HTECH': 19715.29, 'JMT': 21618.96, 'M': 18376.10,
                'NFC': 12250.74, 'PCC': 9732.53
            }
            if sym in image_amounts: amount = image_amounts[sym]
            elif sym == 'SJWD': amount = 20517.98
            elif sym == 'SCAP': amount = 19457.06 * (14000/18000)
            else: amount = qty * avg
            current_stocks[sym] = {'qty': qty, 'avg': avg, 'amount': amount}

    current_cash = 30432.11
    transactions = []
    transactions.append({'date': '2026-04-27', 'type': 'Transfer In', 'amount': 200.00})
    transactions.append({'date': '2026-04-28', 'type': 'Transfer In', 'amount': 32000.00})
    transactions.append({'date': '2026-05-18', 'type': 'Transfer In', 'amount': 28000.00})
    transactions.append({'date': '2026-05-18', 'type': 'Transfer Out', 'amount': 28000.00})
    transactions.append({'date': '2026-05-26', 'type': 'Transfer In', 'amount': 10000.00})
    
    for file in glob.glob('sbi_trade_*.txt'):
        with open(file, 'r', encoding='utf-8') as f:
            for line in f:
                match = re.match(r'(BU|SE)-(\d{4})(\d{2})(\d{2})-[\w-]+\s+(\w+)\s+([\d,]+)\s+[\d\.]+\s+([\d,\.]+)\s+[\d\.]+\s+[\d\.]+\s+[\d\.]+\s+[\d\.]+\s+([\d,\.]+)', line)
                if match:
                    side, y, m, d, sym, qty, amt, net = match.groups()
                    qty = float(qty.replace(',', ''))
                    net = float(net.replace(',', ''))
                    transactions.append({'date': f'{y}-{m}-{d}', 'type': side, 'symbol': sym, 'qty': qty, 'net': net})
                    
    transactions.sort(key=lambda x: x['date'], reverse=True)
    daily_txs = defaultdict(list)
    for tx in transactions: daily_txs[tx['date']].append(tx)
        
    start_date = datetime(2026, 6, 17)
    end_date = datetime(2026, 4, 17)
    current_date = start_date
    cash = current_cash
    stocks = {k: v.copy() for k, v in current_stocks.items()}
    daily_history = []
    
    while current_date >= end_date:
        date_str = current_date.strftime('%Y-%m-%d')
        stock_value = sum(s['amount'] for s in stocks.values() if s['qty'] > 0)
        
        net_transfer = 0.0
        stock_cost_flow = 0.0
        pnl_flow = 0.0
        
        if date_str in daily_txs:
            for tx in daily_txs[date_str]:
                if tx['type'] == 'Transfer In': net_transfer += tx['amount']
                elif tx['type'] == 'Transfer Out': net_transfer -= tx['amount']
                elif tx['type'] == 'BU': 
                    stock_cost_flow -= tx['net']
                elif tx['type'] == 'SE': 
                    sym = tx['symbol']
                    cost_to_add = tx['net'] # default if we don't know the buy
                    if sym == 'PCC': cost_to_add = tx['qty'] * (9732.53/3400)
                    if sym == 'SCAP': cost_to_add = tx['qty'] * (19457.06/18000)
                    if sym == 'BLC': cost_to_add = 19421.01 * (tx['qty']/4900)
                    pnl = tx['net'] - cost_to_add
                    stock_cost_flow += cost_to_add
                    pnl_flow += pnl
                
        daily_history.append({
            'date': date_str,
            'end_cash': cash,
            'net_transfer': net_transfer,
            'stock_cost_flow': stock_cost_flow,
            'pnl_flow': pnl_flow,
            'stock_value': stock_value,
            'total': cash + stock_value
        })
        
        if date_str in daily_txs:
            for tx in daily_txs[date_str]:
                if tx['type'] == 'Transfer In': cash -= tx['amount']
                elif tx['type'] == 'Transfer Out': cash += tx['amount']
                elif tx['type'] == 'BU':
                    cash += tx['net']
                    sym = tx['symbol']
                    if sym in stocks:
                        stocks[sym]['qty'] -= tx['qty']
                        stocks[sym]['amount'] -= tx['net']
                        if stocks[sym]['qty'] <= 0: stocks[sym]['qty'], stocks[sym]['amount'] = 0, 0
                elif tx['type'] == 'SE':
                    cash -= tx['net']
                    sym = tx['symbol']
                    if sym not in stocks: stocks[sym] = {'qty': 0, 'amount': 0, 'avg': 0}
                    cost_to_add = tx['net']
                    if sym == 'PCC': cost_to_add = tx['qty'] * (9732.53/3400)
                    if sym == 'SCAP': cost_to_add = tx['qty'] * (19457.06/18000)
                    if sym == 'BLC': cost_to_add = 19421.01 * (tx['qty']/4900)
                    stocks[sym]['qty'] += tx['qty']
                    stocks[sym]['amount'] += cost_to_add
                    
        current_date -= timedelta(days=1)
        
    daily_history.reverse()
    
    md = '# Detailed Daily Cash Flow (with PnL Split)\n\n'
    md += '| Date | Starting Cash | Net Transfers | Stock Cost Flow | PnL | Ending Cash | Stock Value | Total Value |\n'
    md += '|---|---|---|---|---|---|---|---|\n'
    for row in daily_history:
        start_cash = row['end_cash'] - row['net_transfer'] - row['stock_cost_flow'] - row['pnl_flow']
        md += f"| {row['date']} | {start_cash:,.2f} | {row['net_transfer']:,.2f} | {row['stock_cost_flow']:,.2f} | {row['pnl_flow']:,.2f} | {row['end_cash']:,.2f} | {row['stock_value']:,.2f} | {row['total']:,.2f} |\n"

    with open(r'C:\Users\asus\.gemini\antigravity\brain\3573d85d-05b3-4319-afd2-cefa9cf815fd\detailed_cash_flow.md', 'w', encoding='utf-8') as f:
        f.write(md)

if __name__ == '__main__':
    main()
