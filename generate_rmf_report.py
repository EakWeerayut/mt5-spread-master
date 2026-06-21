import pandas as pd
import subprocess
import os

def run_extractions():
    print("Fetching Kasikorn emails...")
    subprocess.run(["python", "extract_ka_emails.py"], check=True)
    print("Fetching Aberdeen emails...")
    subprocess.run(["python", "extract_ab_emails.py"], check=True)

def parse_date(date_str):
    parts = date_str.split('/')
    y = int(parts[2])
    if y > 2500:
        y -= 543
    return pd.Timestamp(year=y, month=int(parts[1]), day=int(parts[0]))

def generate_report():
    # Load transactions
    ka = pd.read_csv('ka_transactions.csv') if os.path.exists('ka_transactions.csv') else pd.DataFrame()
    ab = pd.read_csv('ab_transactions.csv') if os.path.exists('ab_transactions.csv') else pd.DataFrame()
    
    if ka.empty and ab.empty:
        print("No transactions found.")
        return

    ka['ParsedDate'] = ka['Date'].apply(parse_date) if not ka.empty else []
    ab['ParsedDate'] = ab['Date'].apply(parse_date) if not ab.empty else []
    
    df = pd.concat([ka, ab]).sort_values('ParsedDate', ascending=True)

    # Baseline configuration (01 Dec 2025)
    current_units = {
        'K-S50RMF': 21075.4923,
        'K-SFRMF': 60645.5515,
        'ABSC-RMF': 7165.0401,
        'ABSI-RMF': 141385.5579,
        'SCB': 29647.5212
    }
    
    current_prices = {
        'K-S50RMF': 15.2275,
        'K-SFRMF': 15.2275,
        'ABSC-RMF': 61.8690,
        'ABSI-RMF': 13.2209,
        'SCB': 15.2896
    }
    
    def get_total_value():
        return sum(current_units[fund] * current_prices[fund] for fund in current_units)

    def get_held_symbols():
        return ", ".join(f for f, u in current_units.items() if abs(u) > 0.0001)
        
    history = []
    
    # Baseline entry
    baseline_val = get_total_value()
    history.append({
        'Date': '01 Dec 2025 (Baseline)',
        'TotalValue': baseline_val,
        'PnL': 0.00,
        'Symbols': get_held_symbols()
    })
    
    prev_val = baseline_val
    
    # Process day by day forwards
    for d in df['ParsedDate'].unique():
        day_txns = df[df['ParsedDate'] == d]
        
        # Apply transactions to units and prices
        for _, row in day_txns.iterrows():
            fund = row['Fund']
            if fund not in current_units:
                current_units[fund] = 0.0
                current_prices[fund] = 0.0
                
            current_units[fund] += row['Unit']
            current_prices[fund] = row['Price']
            
        new_val = get_total_value()
        pnl = new_val - prev_val
        
        history.append({
            'Date': pd.to_datetime(d).strftime('%d %b %Y'),
            'TotalValue': new_val,
            'PnL': pnl,
            'Symbols': get_held_symbols()
        })
        
        prev_val = new_val

    # Reverse history so newest is on top
    history.reverse()

    # Generate Markdown Report
    lines = []
    lines.append("# Daily RMF Portfolio Report")
    lines.append("\n## 1. Your Current Portfolio")
    lines.append("| Symbol | Unit | Value (THB) |")
    lines.append("| :--- | :--- | :--- |")
    
    for fund in ['K-S50RMF', 'K-SFRMF', 'ABSI-RMF', 'ABSC-RMF', 'SCB']:
        if fund in current_units and abs(current_units[fund]) > 0.0001:
            u = current_units[fund]
            v = u * current_prices[fund]
            lines.append(f"| **{fund}** | {u:,.4f} | {v:,.2f} |")
            
    lines.append(f"| **TOTAL** | | **{get_total_value():,.2f}** |")
    
    lines.append("\n## 2. Historical Balance & Consolidated P&L")
    lines.append("*The Consolidated P&L column shows the total portfolio growth (market movement + realized gains) since the previous chronological date.*")
    lines.append("\n| Date | Total Value (THB) | Consolidated P&L (THB) | Symbols Held |")
    lines.append("| :--- | :--- | :--- | :--- |")
    
    for idx, h in enumerate(history):
        pnl_str = f"**{h['PnL']:+,.2f}**" if idx < len(history)-1 else "*- Baseline -*"
        lines.append(f"| **{h['Date']}** | {h['TotalValue']:,.2f} | {pnl_str} | {h['Symbols']} |")

    with open('rmf_report.md', 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
        
    print("Report generated successfully as rmf_report.md")

if __name__ == '__main__':
    run_extractions()
    generate_report()
