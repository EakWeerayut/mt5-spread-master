import json, datetime

with open('dashboard/.advisor_bundle.json') as f:
    data = json.load(f)

sells = data['OPPORTUNITY_SCREEN']['richest_sell_candidates'][:3]
buys = data['OPPORTUNITY_SCREEN']['cheapest_buy_candidates'][:3]

cards_html = ""
table_rows = ""

for i, opp in enumerate(sells + buys, 1):
    action = 'SELL' if i <= 3 else 'BUY'
    card_class = 'sell' if action == 'SELL' else 'buy'
    badge = 'MISPRICING'
    price = opp['bid'] if action == 'SELL' else opp['ask']
    edge = opp['sell_edge_btc'] if action == 'SELL' else opp['buy_edge_btc']
    edge_abs = abs(edge)
    
    # HTML for card
    html = f'''
        <div class="card {card_class}">
            <div class="card-header">
                <h2 class="card-title">#{i} — {opp['instrument']}</h2>
                <span class="badge mispricing">{badge}</span>
            </div>
            <div class="ticket-row">
                <div class="ticket-box">
                    <div class="snapshot-label">Action</div>
                    <div class="snapshot-value side-{card_class}">{action} 0.1 BTC</div>
                </div>
                <div class="ticket-box">
                    <div class="snapshot-label">Limit</div>
                    <div class="snapshot-value">{price}</div>
                </div>
                <div class="ticket-box">
                    <div class="snapshot-label">Edge</div>
                    <div class="snapshot-value highlight-green">+{edge_abs:.5f} BTC</div>
                </div>
            </div>
            <div class="details-section">
                <p><strong>Why:</strong> ตลาดตั้งราคาไว้ผิดปกติ (Mispricing) ทำให้เราได้เปรียบ {edge_abs:.5f} BTC</p>
                <p><strong>Risk:</strong> มีโอกาสโดน Assignment ถ้าราคาไปถึง {opp['strike']}</p>
                <p><strong>Verify:</strong> เช็คในแท็บ Strategy ว่า Worst Margin จะต้องดีขึ้น</p>
            </div>
        </div>'''
    cards_html += html

    # HTML for table row
    action_html = f'<span class="side-{card_class}">{action}</span>'
    table_rows += f'''
                <tr>
                    <td>{action_html}</td>
                    <td>{opp['instrument']}</td>
                    <td>{price}</td>
                    <td class="highlight-green">+{edge_abs:.5f} BTC</td>
                </tr>'''

template = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Trading Advisor Report</title>
    <style>
        :root {{
            --bg-color: #0f172a; --card-bg: rgba(30, 41, 59, 0.7);
            --text-main: #e2e8f0; --text-muted: #94a3b8;
            --accent-green: #10b981; --accent-red: #ef4444;
            --accent-blue: #3b82f6; --accent-purple: #8b5cf6;
            --border: rgba(255, 255, 255, 0.08);
        }}
        body {{ font-family: 'Inter', system-ui, sans-serif; background: linear-gradient(135deg, #020617 0%, #0f172a 100%); color: var(--text-main); min-height: 100vh; margin: 0; padding: 20px; display: flex; justify-content: center; font-size: 12px; line-height: 1.4; }}
        .container {{ max-width: 1000px; width: 100%; }}
        h1 {{ font-size: 1.5rem; margin: 0 0 15px 0; color: #38bdf8; }}
        .snapshot-bar {{ background: rgba(255, 255, 255, 0.03); border: 1px solid var(--border); border-radius: 8px; padding: 10px 15px; margin-bottom: 20px; display: flex; justify-content: space-between; flex-wrap: wrap; gap: 10px; }}
        .snapshot-item {{ display: flex; flex-direction: column; }}
        .snapshot-label {{ color: var(--text-muted); font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px; }}
        .snapshot-value {{ font-weight: 600; font-size: 13px; }}
        .highlight-green {{ color: var(--accent-green); }} .highlight-red {{ color: var(--accent-red); }}
        .cards-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 15px; margin-bottom: 30px; }}
        .card {{ background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; padding: 15px; position: relative; overflow: hidden; }}
        .card::before {{ content: ''; position: absolute; top: 0; left: 0; width: 3px; height: 100%; }}
        .card.buy::before {{ background: var(--accent-green); }} .card.sell::before {{ background: var(--accent-red); }}
        .card-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; border-bottom: 1px solid var(--border); padding-bottom: 8px; }}
        .card-title {{ font-size: 13px; font-weight: 600; margin: 0; color: #fff; }}
        .badge {{ font-size: 9px; padding: 2px 6px; border-radius: 4px; font-weight: 600; text-transform: uppercase; white-space: nowrap; }}
        .badge.ladder {{ background: rgba(59, 130, 246, 0.2); color: var(--accent-blue); }} .badge.mispricing {{ background: rgba(139, 92, 246, 0.2); color: var(--accent-purple); }}
        .ticket-row {{ display: grid; grid-template-columns: 2fr 1fr 1fr 1fr; gap: 8px; margin-bottom: 10px; background: rgba(0, 0, 0, 0.2); padding: 8px; border-radius: 6px; }}
        .ticket-box {{ display: flex; flex-direction: column; }}
        .details-section p {{ margin: 4px 0; color: #cbd5e1; }} .details-section strong {{ color: #fff; font-weight: 600; }}
        .side-buy {{ color: var(--accent-green); font-weight: bold; }} .side-sell {{ color: var(--accent-red); font-weight: bold; }}
        table {{ width: 100%; border-collapse: separate; border-spacing: 0; margin-top: 10px; background: var(--card-bg); border-radius: 8px; overflow: hidden; border: 1px solid var(--border); }}
        th, td {{ padding: 12px 15px; text-align: left; border-bottom: 1px solid var(--border); }}
        th {{ background: rgba(0, 0, 0, 0.3); color: var(--text-muted); font-weight: 600; font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px; }}
        tr:last-child td {{ border-bottom: none; }}
        .table-title {{ font-size: 14px; color: #fff; font-weight: 600; margin-bottom: 10px; }}
        .table-wrapper {{ overflow-x: auto; -webkit-overflow-scrolling: touch; border: 1px solid var(--border); border-radius: 8px; background: var(--card-bg); }}
        .table-wrapper table {{ margin-top: 0; border: none; border-radius: 0; }}
        @media (max-width: 600px) {{ .ticket-row {{ grid-template-columns: 1fr 1fr; }} .snapshot-bar {{ flex-direction: column; gap: 15px; }} .snapshot-value {{ font-size: 15px; }} }}
    </style>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
</head>
<body>
<div class="container">
    <h1>Trading Advisor Report</h1>
    
    <div class="snapshot-bar">
        <div class="snapshot-item">
            <div class="snapshot-label">Spot Price</div>
            <div class="snapshot-value highlight-green">{data['META']['spot']}</div>
        </div>
    </div>

    <div class="cards-grid">
        {cards_html}
    </div>

    <div class="table-title">Summary Table</div>
    <div class="table-wrapper">
        <table>
            <thead>
                <tr>
                    <th>Action</th>
                    <th>Instrument</th>
                    <th>Limit Price</th>
                    <th>Edge (BTC)</th>
                </tr>
            </thead>
            <tbody>
{table_rows}
            </tbody>
        </table>
    </div>

    <p style="text-align: center; color: var(--text-muted); margin-top: 20px; font-size: 11px;">
        <em>* Place these yourself on Deribit — Trading Advisor does not execute.</em>
    </p>
</div>
</body>
</html>
'''

with open('daily-trading-summary.html', 'w', encoding='utf-8') as f:
    f.write(template)
print('HTML written.')
