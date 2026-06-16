import sys
sys.path.append('.')
from connectors.deribit import fetch

data = fetch()
logs = data.get('transaction_logs', [])

perp_logs = [log for log in logs if log.get('instrument_name') == 'BTC-PERPETUAL' and log.get('type') == 'trade']
for i, log in enumerate(perp_logs):
    print("Log", i+1)
    print("  Change:", log.get("change"))
    print("  Fee:", log.get("fee"))
    print("  Amount:", log.get("amount"))
    print("  Side:", log.get("side"))
    print("  Profit (Realized PnL):", log.get("profit_as_cash"))
