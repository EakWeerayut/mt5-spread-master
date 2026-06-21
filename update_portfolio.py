import os
import json
import base64
import pdfplumber
import re
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

def get_gmail_service():
    creds = Credentials.from_authorized_user_file(r'C:\Drive\claude-shared\credentials\token.json', ['https://www.googleapis.com/auth/gmail.readonly'])
    return build('gmail', 'v1', credentials=creds)

def main():
    with open('portfolio_state.json', 'r', encoding='utf-8') as f:
        state = json.load(f)
        
    last_update = datetime.strptime(state['last_update_date'], '%Y-%m-%d')
    query_date = last_update.strftime('%Y/%m/%d')
    
    service = get_gmail_service()
    
    transactions = []
    
    # 1. Fetch Transfers In
    query_in = f'from:KPLUS@kasikornbank.com subject:"Result of Bill Payment (Success)" "SBI THAI ONLINE SECURITIES" after:{query_date}'
    messages = service.users().messages().list(userId='me', q=query_in, maxResults=100).execute().get('messages', [])
    for msg in messages:
        message = service.users().messages().get(userId='me', id=msg['id']).execute()
        headers = message['payload'].get('headers', [])
        date_str = next((h['value'] for h in headers if h['name'] == 'Date'), '')
        try:
            date_obj = datetime.strptime(date_str[:25].strip(), '%a, %d %b %Y %H:%M:%S')
        except:
            continue
        if date_obj.date() <= last_update.date(): continue
        
        # Parse Amount
        # It's in the email body or snippet.
        snippet = message.get('snippet', '')
        amt_match = re.search(r'Amount:?\s*([\d,]+\.\d{2})', snippet, re.IGNORECASE)
        if amt_match:
            amt = float(amt_match.group(1).replace(',', ''))
            transactions.append({'date': date_obj.strftime('%Y-%m-%d'), 'type': 'Transfer In', 'amount': amt})
            
    # 2. Fetch Transfers Out
    query_out = f'from:no-reply-customer@sbito.co.th subject:"Complete Withdraw ATS" after:{query_date}'
    messages = service.users().messages().list(userId='me', q=query_out, maxResults=100).execute().get('messages', [])
    for msg in messages:
        message = service.users().messages().get(userId='me', id=msg['id']).execute()
        headers = message['payload'].get('headers', [])
        date_str = next((h['value'] for h in headers if h['name'] == 'Date'), '')
        try:
            date_obj = datetime.strptime(date_str[:25].strip(), '%a, %d %b %Y %H:%M:%S')
        except:
            continue
        if date_obj.date() <= last_update.date(): continue
        
        # Need to parse body text
        import io
        from bs4 import BeautifulSoup
        parts = message['payload'].get('parts', [])
        body_text = ''
        if not parts:
            if 'data' in message['payload']['body']:
                body_text = base64.urlsafe_b64decode(message['payload']['body']['data']).decode('utf-8', errors='ignore')
        else:
            for part in parts:
                if part['mimeType'] == 'text/html' and 'data' in part['body']:
                    html = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='ignore')
                    body_text = BeautifulSoup(html, 'html.parser').get_text()
                    
        matches = re.findall(r'([\d,]+\.\d{2})', body_text)
        if matches:
            amounts = [float(m.replace(',', '')) for m in matches]
            amt = max(amounts)
            transactions.append({'date': date_obj.strftime('%Y-%m-%d'), 'type': 'Transfer Out', 'amount': amt})

    # 3. Fetch Trades (PDFs)
    query_trades = f'(from:SBI Thai Online OR from:no-reply-customer@sbito.co.th) subject:"Securities Confirmation" after:{query_date}'
    messages = service.users().messages().list(userId='me', q=query_trades, maxResults=100).execute().get('messages', [])
    
    def find_attachments(parts):
        attachments = []
        for part in parts:
            if part.get('filename') and part.get('body', {}).get('attachmentId'):
                attachments.append(part)
            if 'parts' in part:
                attachments.extend(find_attachments(part['parts']))
        return attachments

    for msg in messages:
        message = service.users().messages().get(userId='me', id=msg['id']).execute()
        headers = message['payload'].get('headers', [])
        date_str = next((h['value'] for h in headers if h['name'] == 'Date'), '')
        try:
            date_obj = datetime.strptime(date_str[:25].strip(), '%a, %d %b %Y %H:%M:%S')
        except:
            continue
        if date_obj.date() <= last_update.date(): continue

        attachments = find_attachments(message['payload'].get('parts', []))
        for att in attachments:
            if att['filename'].endswith('.pdf'):
                att_id = att['body']['attachmentId']
                attachment = service.users().messages().attachments().get(userId='me', messageId=msg['id'], id=att_id).execute()
                file_data = base64.urlsafe_b64decode(attachment['data'])
                pdf_path = f"temp_trade.pdf"
                with open(pdf_path, 'wb') as f: f.write(file_data)
                
                try:
                    with pdfplumber.open(pdf_path, password='04101983') as pdf:
                        text = ''
                        for page in pdf.pages:
                            text += page.extract_text() + '\n'
                        
                        lines = text.split('\n')
                        for line in lines:
                            match = re.match(r'(B|S)\s+(\w+)\s+([\d,]+)\s+[\d\.]+\s+([\d,\.]+)\s+[\d\.]+\s+[\d\.]+\s+[\d\.]+\s+([\d,\.]+)', line)
                            if match:
                                side_char, sym, qty, amt, net = match.groups()
                                side = 'BU' if side_char == 'B' else 'SE'
                                qty = float(qty.replace(',', ''))
                                net = float(net.replace(',', ''))
                                amt = float(amt.replace(',', ''))
                                fee = net - amt if side == 'BU' else amt - net
                                transactions.append({
                                    'date': date_obj.strftime('%Y-%m-%d'),
                                    'type': side,
                                    'symbol': sym,
                                    'qty': qty,
                                    'net': net,
                                    'amount': amt,
                                    'fee': fee
                                })
                except Exception as e:
                    print(f"Error reading PDF: {e}")
                if os.path.exists(pdf_path): os.remove(pdf_path)

    # If no new transactions, just print the current state and exit
    if not transactions:
        print("No new transactions found since " + state['last_update_date'])
        stocks = state['stocks']
        print('\n# Current Portfolio (No changes)\n')
        print('| Stock | On Hand | Avg Cost | Amount (THB) |')
        print('|---|---|---|---|')
        for sym in sorted(stocks.keys()):
            s = stocks[sym]
            if s['qty'] > 0:
                print(f"| {sym} | {s['qty']:,.0f} | {s['avg']:,.2f} | {s['amount']:,.2f} |")
        return
        
    # Group by date ascending
    transactions.sort(key=lambda x: x['date'])
    from collections import defaultdict
    daily_txs = defaultdict(list)
    for tx in transactions:
        daily_txs[tx['date']].append(tx)
        
    cash = state['current_cash']
    stocks = state['stocks']
    
    print('# Detailed Daily Cash Flow Update\n')
    print('| Date | Starting Cash | Net Transfers | Stock Cost Flow | PnL | Fees | Ending Cash | Stock Value | Total Value |')
    print('|---|---|---|---|---|---|---|---|---|')
    
    for date_str, txs in sorted(daily_txs.items()):
        starting_cash = cash
        net_transfer = 0.0
        stock_cost_flow = 0.0
        pnl_flow = 0.0
        fee_flow = 0.0
        
        for tx in txs:
            if tx['type'] == 'Transfer In':
                net_transfer += tx['amount']
                if tx['amount'] < 1000:
                    fee_flow -= tx['amount'] # Negative fee means positive cash inflow for fees
                    cash += tx['amount']
                else:
                    cash += tx['amount']
            elif tx['type'] == 'Transfer Out':
                net_transfer -= tx['amount']
                cash -= tx['amount']
            elif tx['type'] == 'BU':
                stock_cost_flow -= tx['amount']
                fee_flow -= tx['fee']
                cash -= tx['net']
                sym = tx['symbol']
                if sym not in stocks: stocks[sym] = {'qty': 0, 'avg': 0, 'amount': 0}
                stocks[sym]['qty'] += tx['qty']
                stocks[sym]['amount'] += tx['net'] # Capitalize fees
                stocks[sym]['avg'] = stocks[sym]['amount'] / stocks[sym]['qty']
            elif tx['type'] == 'SE':
                sym = tx['symbol']
                # Cost basis = qty_sold * current_avg
                if sym in stocks and stocks[sym]['qty'] > 0:
                    avg_cost = stocks[sym]['avg']
                else:
                    avg_cost = tx['amount'] / tx['qty'] # Fallback
                
                cost_basis = tx['qty'] * avg_cost
                pnl = tx['amount'] - cost_basis
                
                stock_cost_flow += cost_basis
                pnl_flow += pnl
                fee_flow -= tx['fee']
                cash += tx['net']
                
                if sym in stocks:
                    stocks[sym]['qty'] -= tx['qty']
                    stocks[sym]['amount'] -= cost_basis
                    if stocks[sym]['qty'] <= 0.001:
                        stocks[sym]['qty'] = 0
                        stocks[sym]['amount'] = 0
                        
        stock_value = sum(s['amount'] for s in stocks.values() if s['qty'] > 0)
        total_value = cash + stock_value
        print(f"| {date_str} | {starting_cash:,.2f} | {net_transfer:,.2f} | {stock_cost_flow:,.2f} | {pnl_flow:,.2f} | {fee_flow:,.2f} | {cash:,.2f} | {stock_value:,.2f} | {total_value:,.2f} |")
        
    print('\n# Current Portfolio\n')
    print('| Stock | On Hand | Avg Cost | Amount (THB) |')
    print('|---|---|---|---|')
    for sym in sorted(stocks.keys()):
        s = stocks[sym]
        if s['qty'] > 0:
            print(f"| {sym} | {s['qty']:,.0f} | {s['avg']:,.2f} | {s['amount']:,.2f} |")
            
    # Update state
    state['last_update_date'] = max(daily_txs.keys())
    state['current_cash'] = cash
    state['stocks'] = stocks
    with open('portfolio_state.json', 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=4)
        
if __name__ == '__main__':
    main()
