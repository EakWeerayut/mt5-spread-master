import glob, re
trades = {}
for file in glob.glob('sbi_trade_*.txt'):
    with open(file, 'r', encoding='utf-8') as f:
        for line in f:
            match = re.match(r'(BU|SL)-[\w-]+\s+(\w+)\s+([\d,]+)\s+[\d\.]+\s+([\d,\.]+)\s+[\d\.]+\s+[\d\.]+\s+[\d\.]+\s+[\d\.]+\s+([\d,\.]+)', line)
            if match:
                side, symbol, qty_str, amt_str, net_amt_str = match.groups()
                qty = int(qty_str.replace(',', ''))
                amt = float(amt_str.replace(',', ''))
                net_amt = float(net_amt_str.replace(',', ''))
                
                if symbol not in trades:
                    trades[symbol] = {'qty': 0, 'thb': 0.0, 'fee': 0.0}
                
                if side == 'BU':
                    fee = net_amt - amt
                    trades[symbol]['qty'] += qty
                    trades[symbol]['thb'] -= net_amt
                    trades[symbol]['fee'] += fee
                elif side == 'SL':
                    fee = amt - net_amt
                    trades[symbol]['qty'] -= qty
                    trades[symbol]['thb'] += net_amt
                    trades[symbol]['fee'] += fee

print('Symbol | Amount Change | THB Amount Change | Fee')
print('---|---|---|---')
for sym, data in sorted(trades.items()):
    print(f"{sym} | {data['qty']} | {data['thb']:.2f} | {data['fee']:.2f}")
