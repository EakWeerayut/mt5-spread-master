import csv
from collections import defaultdict
from datetime import datetime, timedelta

def main():
    # 1. Parse current portfolio
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

    # 2. Parse Transfers
    transfers = [
        {'date': '2026-04-27', 'type': 'Transfer In', 'amount': 200.00},
        {'date': '2026-04-28', 'type': 'Transfer In', 'amount': 32000.00},
        {'date': '2026-05-18', 'type': 'Transfer In', 'amount': 28000.00},
        {'date': '2026-05-18', 'type': 'Transfer Out', 'amount': 28000.00},
        {'date': '2026-05-26', 'type': 'Transfer In', 'amount': 10000.00}
    ]

    # 3. Parse Exact Trades from CSV
    trades = []
    with open(r'C:\Drive\claude-shared\portfolio-tracker\SBI Historical Data.csv', 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Trade Date format: 08/06/2026
            date_obj = datetime.strptime(row['Trade Date'], '%d/%m/%Y')
            date_str = date_obj.strftime('%Y-%m-%d')
            side = 'BU' if row['Type'] == 'BUY' else 'SE'
            sym = row['Symbol']
            qty = float(row['Quantity'].replace(',', ''))
            net = float(row['Net Amount'].replace(',', ''))
            amount = float(row['Amount'].replace(',', ''))
            fee = float(row['Commission'].replace(',', '')) + float(row['Charge'].replace(',', '')) + float(row['VAT'].replace(',', ''))
            trades.append({
                'date': date_str,
                'type': side,
                'symbol': sym,
                'qty': qty,
                'net': net,
                'amount': amount,
                'fee': fee
            })
            
    # Calculate exact forward cost basis for all stocks just to be perfectly accurate for PnL
    forward_stocks = defaultdict(lambda: {'qty': 0.0, 'amount': 0.0})
    sell_costs = {} # map (date, symbol, qty) -> cost_basis
    
    # Sort trades ascending for forward pass
    trades_asc = sorted(trades, key=lambda x: x['date'])
    for tx in trades_asc:
        sym = tx['symbol']
        if tx['type'] == 'BU':
            forward_stocks[sym]['qty'] += tx['qty']
            forward_stocks[sym]['amount'] += tx['net']
        elif tx['type'] == 'SE':
            # If we don't have enough qty (bought before file started), just use current avg or fallback
            qty_has = forward_stocks[sym]['qty']
            amt_has = forward_stocks[sym]['amount']
            if qty_has > 0:
                avg = amt_has / qty_has
                cost = tx['qty'] * avg
                forward_stocks[sym]['qty'] -= tx['qty']
                forward_stocks[sym]['amount'] -= cost
            else:
                cost = tx['net'] # Fallback
            sell_costs[(tx['date'], sym, tx['qty'])] = cost

    # 4. Group by date for backwards simulation
    all_txs = transfers + trades
    all_txs.sort(key=lambda x: x['date'], reverse=True)
    daily_txs = defaultdict(list)
    for tx in all_txs:
        daily_txs[tx['date']].append(tx)
        
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
        fee_flow = 0.0
        
        if date_str in daily_txs:
            for tx in daily_txs[date_str]:
                if tx['type'] == 'Transfer In': 
                    net_transfer += tx['amount']
                    if tx['amount'] < 1000:
                        fee_flow -= tx['amount']
                elif tx['type'] == 'Transfer Out': net_transfer -= tx['amount']
                elif tx['type'] == 'BU':
                    stock_cost_flow -= tx['amount']
                    fee_flow -= tx['fee']
                elif tx['type'] == 'SE':
                    sym = tx['symbol']
                    # Get perfectly calculated cost basis
                    cost_to_add = sell_costs.get((tx['date'], sym, tx['qty']), tx['net'])
                    pnl = tx['amount'] - cost_to_add
                    stock_cost_flow += cost_to_add
                    pnl_flow += pnl
                    fee_flow -= tx['fee']
                    
        daily_history.append({
            'date': date_str,
            'end_cash': cash,
            'net_transfer': net_transfer,
            'stock_cost_flow': stock_cost_flow,
            'pnl_flow': pnl_flow,
            'fee_flow': fee_flow,
            'stock_value': stock_value,
            'total': cash + stock_value
        })
        
        if date_str in daily_txs:
            for tx in daily_txs[date_str]:
                if tx['type'] == 'Transfer In':
                    if tx['amount'] >= 1000:
                        cash -= tx['amount']
                elif tx['type'] == 'Transfer Out': cash += tx['amount']
                elif tx['type'] == 'BU':
                    cash += tx['net']
                    sym = tx['symbol']
                    if sym in stocks:
                        stocks[sym]['qty'] -= tx['qty']
                        stocks[sym]['amount'] -= tx['net']
                        if stocks[sym]['qty'] <= 0.001: 
                            stocks[sym]['qty'], stocks[sym]['amount'] = 0, 0
                elif tx['type'] == 'SE':
                    cash -= tx['net']
                    sym = tx['symbol']
                    if sym not in stocks: stocks[sym] = {'qty': 0, 'amount': 0, 'avg': 0}
                    cost_to_add = sell_costs.get((tx['date'], sym, tx['qty']), tx['net'])
                    stocks[sym]['qty'] += tx['qty']
                    stocks[sym]['amount'] += cost_to_add
                    
        current_date -= timedelta(days=1)
        
    daily_history.reverse()
    
    md = '# Detailed Daily Cash Flow (with PnL and Fees Split)\n\n'
    md += '| Date | Starting Cash | Net Transfers | Stock Cost Flow | PnL | Fees | Ending Cash | Stock Value | Total Value |\n'
    md += '|---|---|---|---|---|---|---|---|---|\n'
    for row in daily_history:
        start_cash = row['end_cash'] - row['net_transfer'] - row['stock_cost_flow'] - row['pnl_flow'] - row['fee_flow']
        md += f"| {row['date']} | {start_cash:,.2f} | {row['net_transfer']:,.2f} | {row['stock_cost_flow']:,.2f} | {row['pnl_flow']:,.2f} | {row['fee_flow']:,.2f} | {row['end_cash']:,.2f} | {row['stock_value']:,.2f} | {row['total']:,.2f} |\n"

    with open(r'C:\Users\asus\.gemini\antigravity\brain\3573d85d-05b3-4319-afd2-cefa9cf815fd\detailed_cash_flow.md', 'w', encoding='utf-8') as f:
        f.write(md)

if __name__ == '__main__':
    main()
