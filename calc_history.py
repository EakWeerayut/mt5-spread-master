import pandas as pd
import csv

# Current portfolio
current_units = {
    'K-S50RMF': 80935.1904,
    'K-SFRMF': 2487.3549,
    'ABSC-RMF': 0.0,
    'ABSI-RMF': 210964.168
}

# Current known prices (latest from transactions)
latest_prices = {
    'K-S50RMF': 14.6537,
    'K-SFRMF': 15.2582,
    'ABSC-RMF': 74.8152,  # from 26/02
    'ABSI-RMF': 13.2768   # from 26/02
}

# Load transactions
ka = pd.read_csv('ka_transactions.csv')
ab = pd.read_csv('ab_transactions.csv')

# Combine and sort by date
# Date format for KA: DD/MM/YYYY (Thai year 2569)
# Date format for AB: DD/MM/YYYY (CE year 2025/2026)

def parse_date(row):
    d = row['Date']
    parts = d.split('/')
    y = int(parts[2])
    if y > 2500:
        y -= 543
    return pd.Timestamp(year=y, month=int(parts[1]), day=int(parts[0]))

ka['ParsedDate'] = ka.apply(parse_date, axis=1)
ab['ParsedDate'] = ab.apply(parse_date, axis=1)

df = pd.concat([ka, ab]).sort_values('ParsedDate', ascending=False) # Reverse chronological

# We will calculate the beginning balances before each date
# To do PnL, the user's example `PnL = 77728.6967*(15.2582-15.2275)` means:
# For the transaction on 13 May (where K-SFRMF was sold), the buy price used was 15.2275 (from 25 Mar).
# This implies tracking the cost basis.
# But since we are going backward, we don't know the cost basis for units held before our history.
# Let's just calculate backwards units and values. We can also calculate PnL for the switch outs.

dates = df['ParsedDate'].unique()

history = []

curr_u = current_units.copy()
curr_p = latest_prices.copy()

for d in dates:
    day_txns = df[df['ParsedDate'] == d]
    
    # Process PnL for this day
    # PnL = sum of (sell_amount - sell_units * cost_basis)
    # But wait, cost basis is tricky. Let's just report the day's transactions and the beginning balance.
    
    # Calculate beginning balance (before this day's transactions)
    prev_u = curr_u.copy()
    
    for _, row in day_txns.iterrows():
        fund = row['Fund']
        unit = row['Unit']
        price = row['Price']
        
        # update the price to this day's price
        curr_p[fund] = price
        
        # Revert the transaction to get the 'before' balance
        # If we bought (unit > 0), the previous balance was lower: prev_u = curr_u - unit
        prev_u[fund] -= unit
        
    # Formatting output for this day
    # End of day balance is curr_u
    # Beginning of day balance is prev_u
    
    # We will record the beginning of day balance, just like the user asked: "25 Mar (begining)"
    history.append({
        'DateStr': pd.to_datetime(d).strftime('%d %b %Y') + ' (beginning)',
        'Units': prev_u.copy(),
        'Prices': curr_p.copy(), # Prices before this day? Actually let's just use the latest known price up to that day
    })
    
    curr_u = prev_u.copy()

# Print as markdown
print("| Date | K-S50RMF Unit | K-SFRMF Unit | ABSC-RMF Unit | ABSI-RMF Unit | K-S50RMF Val | K-SFRMF Val | ABSC-RMF Val | ABSI-RMF Val |")
print("|---|---|---|---|---|---|---|---|---|")
for h in history:
    u = h['Units']
    p = h['Prices']
    print(f"| {h['DateStr']} | {u['K-S50RMF']:.4f} | {u['K-SFRMF']:.4f} | {u['ABSC-RMF']:.4f} | {u['ABSI-RMF']:.4f} | "
          f"{u['K-S50RMF']*p['K-S50RMF']:,.2f} | {u['K-SFRMF']*p['K-SFRMF']:,.2f} | {u['ABSC-RMF']*p['ABSC-RMF']:,.2f} | {u['ABSI-RMF']*p['ABSI-RMF']:,.2f} |")

