import base64
import re
import pdfplumber
import os
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from bs4 import BeautifulSoup
from email.utils import parsedate_to_datetime

def get_gmail_service():
    creds_path = r"C:\Drive\claude-shared\credentials\token.json"
    scopes = ["https://www.googleapis.com/auth/gmail.readonly"]
    creds = Credentials.from_authorized_user_file(creds_path, scopes)
    return build('gmail', 'v1', credentials=creds)

def get_body_recursive(payload):
    body_data = ""
    if 'data' in payload.get('body', {}):
        body_data += base64.urlsafe_b64decode(payload['body']['data'].encode('UTF-8')).decode('utf-8', errors='ignore')
    if 'parts' in payload:
        for part in payload['parts']:
            body_data += get_body_recursive(part)
    return body_data

def get_attachments_recursive(service, user_id, msg_id, payload):
    attachments = []
    if 'filename' in payload and payload['filename'].endswith('.pdf'):
        att_id = payload['body'].get('attachmentId')
        if att_id:
            att = service.users().messages().attachments().get(
                userId=user_id, messageId=msg_id, id=att_id
            ).execute()
            data = att['data']
            file_data = base64.urlsafe_b64decode(data.encode('UTF-8'))
            attachments.append((payload['filename'], file_data))
    if 'parts' in payload:
        for part in payload['parts']:
            attachments.extend(get_attachments_recursive(service, user_id, msg_id, part))
    return attachments

def main():
    service = get_gmail_service()
    two_months_ago = (datetime.now() - timedelta(days=60)).strftime("%Y/%m/%d")

    records = [] # list of dicts: {'date': 'YYYY-MM-DD', 'type': 'Transfer In'|'Transfer Out'|'Trade', 'desc': '', 'amount_thb': 0, 'fee': 0, 'qty': 0}

    # 1. Transfer In
    print("Processing Transfer In...")
    query_in = f'from:KPLUS@kasikornbank.com subject:"Result of Bill Payment (Success)" "SBI THAI ONLINE SECURITIES" after:{two_months_ago}'
    messages = service.users().messages().list(userId='me', q=query_in, maxResults=100).execute().get('messages', [])
    for msg in messages:
        message = service.users().messages().get(userId='me', id=msg['id']).execute()
        headers = message['payload'].get('headers', [])
        date_str = next((h['value'] for h in headers if h['name'] == 'Date'), '')
        try:
            dt = parsedate_to_datetime(date_str)
            dt_str = dt.strftime("%Y-%m-%d")
        except:
            dt_str = 'Unknown'

        body = get_body_recursive(message['payload'])
        text = BeautifulSoup(body, 'html.parser').get_text()
        match = re.search(r'(?:จำนวนเงิน|Amount).*?([\d,]+\.\d{2})', text, re.IGNORECASE)
        if match:
            amount = float(match.group(1).replace(',', ''))
            records.append({'date': dt_str, 'type': 'Transfer In', 'desc': 'Transfer In', 'amount_thb': amount, 'fee': 0, 'qty': 0})

    # 2. Transfer Out
    print("Processing Transfer Out...")
    query_out = f'from:no-reply-customer@sbito.co.th subject:"Complete Withdraw ATS" after:{two_months_ago}'
    messages = service.users().messages().list(userId='me', q=query_out, maxResults=100).execute().get('messages', [])
    for msg in messages:
        message = service.users().messages().get(userId='me', id=msg['id']).execute()
        headers = message['payload'].get('headers', [])
        date_str = next((h['value'] for h in headers if h['name'] == 'Date'), '')
        try:
            dt = parsedate_to_datetime(date_str)
            dt_str = dt.strftime("%Y-%m-%d")
        except:
            dt_str = 'Unknown'

        body = get_body_recursive(message['payload'])
        text = BeautifulSoup(body, 'html.parser').get_text()
        
        if not re.search(r'([\d,]+\.\d{2})', text):
             text = body
             
        matches = re.findall(r'([\d,]+\.\d{2})', text)
        if matches:
            amounts = [float(m.replace(',', '')) for m in matches]
            amount = max(amounts)
            records.append({'date': dt_str, 'type': 'Transfer Out', 'desc': 'Transfer Out', 'amount_thb': -amount, 'fee': 0, 'qty': 0})

    # 3. Trade Activity
    # Instead of parsing emails again, we can just read the extracted sbi_trade_*.txt files we made previously,
    # because they have the contract number which has the date!
    import glob
    print("Processing Trade Activity...")
    for file in glob.glob('sbi_trade_*.txt'):
        with open(file, 'r', encoding='utf-8') as f:
            for line in f:
                match = re.match(r'(BU|SL)-(\d{4})(\d{2})(\d{2})-[\w-]+\s+(\w+)\s+([\d,]+)\s+[\d\.]+\s+([\d,\.]+)\s+[\d\.]+\s+[\d\.]+\s+[\d\.]+\s+[\d\.]+\s+([\d,\.]+)', line)
                if match:
                    side, year, month, day, symbol, qty_str, amt_str, net_amt_str = match.groups()
                    qty = int(qty_str.replace(',', ''))
                    amt = float(amt_str.replace(',', ''))
                    net_amt = float(net_amt_str.replace(',', ''))
                    dt_str = f"{year}-{month}-{day}"
                    
                    if side == 'BU':
                        fee = net_amt - amt
                        records.append({
                            'date': dt_str,
                            'type': 'Trade',
                            'desc': f"Buy {symbol}",
                            'amount_thb': -net_amt,
                            'fee': fee,
                            'qty': qty
                        })
                    elif side == 'SL':
                        fee = amt - net_amt
                        records.append({
                            'date': dt_str,
                            'type': 'Trade',
                            'desc': f"Sell {symbol}",
                            'amount_thb': net_amt,
                            'fee': fee,
                            'qty': -qty
                        })

    # Now group by Date
    # For each date, print the list of activities
    from collections import defaultdict
    grouped = defaultdict(list)
    for r in records:
        grouped[r['date']].append(r)
        
    print("\n=== SUMMARY BY DATE ===")
    for dt in sorted(grouped.keys()):
        print(f"\nDate: {dt}")
        print(f"{'Description':<20} | {'Qty Change':<10} | {'THB Change':<12} | {'Fee':<6}")
        print("-" * 57)
        day_thb = 0
        for r in grouped[dt]:
            if r['type'] == 'Trade':
                qty_str = f"{'+' if r['qty'] > 0 else ''}{r['qty']}"
                print(f"{r['desc']:<20} | {qty_str:<10} | {r['amount_thb']:>12,.2f} | {r['fee']:>6,.2f}")
            elif r['type'] == 'Transfer In':
                print(f"Transfer In          | {'-':<10} | {r['amount_thb']:>12,.2f} | {'0.00':>6}")
            elif r['type'] == 'Transfer Out':
                print(f"Transfer Out         | {'-':<10} | {r['amount_thb']:>12,.2f} | {'0.00':>6}")
            day_thb += r['amount_thb']
        print("-" * 57)
        print(f"Daily Net THB Change: {day_thb:,.2f}")

if __name__ == '__main__':
    main()
