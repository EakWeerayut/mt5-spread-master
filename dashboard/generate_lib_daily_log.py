import os
import re
import json
import base64
import datetime
from collections import defaultdict
import pdfplumber
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv

DB_FILE = '.lib_balances_db.json'
CACHE_FILE = '.lib_email_cache.json'
OUT_FILE = 'C:\\Users\\asus\\.gemini\\antigravity\\brain\\b7db3e8d-7e2c-4b31-9e15-261d21c7e9cf\\lib_daily_log.md'
START_DATE = '2026-05-15'

def load_json(filepath):
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r') as f: return json.load(f)
        except: pass
    return {}

def save_json(data, filepath):
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)

def get_gmail_service():
    creds_path = r"C:\Drive\claude-shared\credentials\token.json"
    if not os.path.exists(creds_path):
        print(f"Error: Credentials not found at {creds_path}")
        return None
    scopes = ["https://www.googleapis.com/auth/gmail.readonly"]
    creds = Credentials.from_authorized_user_file(creds_path, scopes)
    return build('gmail', 'v1', credentials=creds)

def parse_float(val_str):
    if not val_str: return 0.0
    val_str = val_str.replace(',', '').strip()
    try: return float(val_str)
    except: return 0.0

def parse_confirm_pdf(pdf_path, password):
    data = {}
    with pdfplumber.open(pdf_path, password=password) as pdf:
        text = ""
        for page in pdf.pages:
            text += page.extract_text() + "\n"
            
    # Date
    date_match = re.search(r'Trading Date\s+(\d{2}/\d{2}/\d{4})', text)
    if date_match:
        data['date'] = datetime.datetime.strptime(date_match.group(1), '%d/%m/%Y').strftime('%Y-%m-%d')
        
    # Statement of Account row
    statement_match = re.search(r'^([\d,\.-]+)\s+([\d,\.-]+)\s+([\d,\.-]+)\s+([\d,\.-]+)\s+([\d,\.-]+)\s+([\d,\.-]+)\s+([\d,\.-]+)\s+([\d,\.-]+)\s+([\d,\.-]+)$', text, re.MULTILINE)
    if statement_match:
        data['beginning'] = parse_float(statement_match.group(1))
        data['ending'] = parse_float(statement_match.group(2))
        
    def get_multiplier(code):
        if code.startswith('S50'): return 200
        if code.startswith('USD'): return 1000
        return 1000

    # Options Value based on Cost Price
    data['opt_long'] = 0.0
    data['opt_short'] = 0.0
    outstanding_idx = text.find("Outstanding Position as of")
    if outstanding_idx != -1:
        end_idx = text.find("Statement of Account", outstanding_idx)
        if end_idx == -1: end_idx = len(text)
        outstanding_text = text[outstanding_idx:end_idx]
        
        for line in outstanding_text.split('\n'):
            m = re.match(r'^([A-Za-z0-9\.]+)\s+(\d{2}/\d{2}/\d{4})\s+(\d+)\s+(\d+)\s+([\d,\.-]+)\s+([\d,\.-]+)', line.strip())
            if m:
                code = m.group(1)
                is_opt = 'C' in code[-8:] or 'P' in code[-8:]
                if is_opt:
                    long_qty = parse_float(m.group(3))
                    short_qty = parse_float(m.group(4))
                    cost_price = parse_float(m.group(5))
                    mult = get_multiplier(code)
                    
                    if long_qty > 0:
                        data['opt_long'] += long_qty * cost_price * mult
                    if short_qty > 0:
                        data['opt_short'] += short_qty * cost_price * mult

    trades = []
    trading_idx = text.find("Trading Transaction")
    if trading_idx != -1:
        end_idx = text.find("Position Closing", trading_idx)
        if end_idx == -1: end_idx = len(text)
        trading_text = text[trading_idx:end_idx]
        
        for line in trading_text.split('\n'):
            m = re.match(r'^([A-Za-z0-9\.]+)\s+(?:NET|NEW|CLOSE|Net|New|Close)\s+(?:Long|Short)\s+(\d+)\s+([\d,\.-]+)\s+([\d,\.-]+)\s+([\d,\.-]+)\s+([\d,\.-]+)\s+([\d,\.-]+)\s+([\d,\.-]+)', line.strip())
            if m:
                code = m.group(1)
                qty = parse_float(m.group(2))
                comm = parse_float(m.group(5))
                vat = parse_float(m.group(6))
                trades.append({
                    'code': code,
                    'qty': qty,
                    'fee_paid': comm + vat
                })
    data['trades'] = trades
    return data

def parse_deposit_pdf(pdf_path, password):
    data = {}
    with pdfplumber.open(pdf_path, password=password) as pdf:
        text = ""
        for page in pdf.pages:
            text += page.extract_text() + "\n"
            
    # Look for TFEX Deposit or just Date + Amount
    for line in text.split('\n'):
        match = re.search(r'(\d{2}/\d{2}/\d{4})\s+([\d,\.-]+)', line)
        if match and ('Deposit' in line or 'Withdrawal' in line or 'TFEX' in line):
            data['date'] = datetime.datetime.strptime(match.group(1), '%d/%m/%Y').strftime('%Y-%m-%d')
            data['amount'] = parse_float(match.group(2))
            if 'Withdrawal' in line:
                data['amount'] = -data['amount']
            break
            
    return data

def get_contract_type(code):
    is_opt = 'C' in code[-8:] or 'P' in code[-8:]
    m = re.match(r'^([A-Za-z0-9]+?)[F-Z]\d{2}', code)
    und = m.group(1) if m else code[:3]
    return f"{und}_{'OPT' if is_opt else 'FUT'}"

def process_lib_emails():
    load_dotenv()
    password = os.environ.get('LIB_PDF_PASSWORD')
    if not password:
        print("Error: LIB_PDF_PASSWORD not found in .env")
        return

    service = get_gmail_service()
    if not service: return

    cache = load_json(CACHE_FILE)
    
    query = '(subject:"LIB E Confirm Tfex" OR subject:"LIB ใบรับฝาก") after:2026/05/14'
    print("Fetching emails...")
    
    messages = []
    page_token = None
    while True:
        results = service.users().messages().list(userId='me', q=query, pageToken=page_token).execute()
        messages.extend(results.get('messages', []))
        page_token = results.get('nextPageToken')
        if not page_token:
            break
            
    print(f"Found {len(messages)} emails.")
    
    for msg in messages:
        msg_id = msg['id']
        if msg_id in cache:
            if cache[msg_id].get('type') == 'confirm' and 'trades' not in cache[msg_id]:
                pass # force re-download to parse trades and options values
            else:
                continue
            
        message = service.users().messages().get(userId='me', id=msg_id).execute()
        headers = message['payload'].get('headers', [])
        subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'Unknown')
        
        is_confirm = "Confirm Tfex" in subject
        is_deposit = "ใบรับฝาก" in subject
        
        parts = message['payload'].get('parts', [])
        for part in parts:
            if part['filename'] and part['filename'].endswith('.pdf'):
                att_id = part['body'].get('attachmentId')
                if att_id:
                    print(f"Processing attachment: {part['filename']}")
                    att = service.users().messages().attachments().get(
                        userId='me', messageId=msg_id, id=att_id
                    ).execute()
                    
                    file_data = base64.urlsafe_b64decode(att['data'].encode('UTF-8'))
                    temp_pdf = f"temp_lib_dl.pdf"
                    with open(temp_pdf, 'wb') as f:
                        f.write(file_data)
                        
                    try:
                        if is_confirm:
                            data = parse_confirm_pdf(temp_pdf, password)
                            data['type'] = 'confirm'
                        elif is_deposit:
                            data = parse_deposit_pdf(temp_pdf, password)
                            data['type'] = 'deposit'
                            
                        cache[msg_id] = data
                    except Exception as e:
                        print(f"Failed to parse {part['filename']}: {e}")
                        
                    if os.path.exists(temp_pdf):
                        os.remove(temp_pdf)
                        
    save_json(cache, CACHE_FILE)
    
    max_fee_per_contract = defaultdict(float)
    for msg_id, data in cache.items():
        if data.get('type') == 'confirm' and 'trades' in data:
            for t in data['trades']:
                if t['qty'] > 0:
                    ctype = get_contract_type(t['code'])
                    fpc = t['fee_paid'] / t['qty']
                    if fpc > max_fee_per_contract[ctype]:
                        max_fee_per_contract[ctype] = fpc

    daily_confirms = {}
    daily_transfers = defaultdict(float)
    
    for msg_id, data in cache.items():
        if 'date' not in data: continue
        d_str = data['date']
        
        if data['type'] == 'confirm':
            daily_confirms[d_str] = data
        elif data['type'] == 'deposit':
            daily_transfers[d_str] += data.get('amount', 0.0)
            
    today_str = datetime.datetime.now().strftime('%Y-%m-%d')
    curr_d = datetime.datetime.strptime(START_DATE, '%Y-%m-%d')
    today_d = datetime.datetime.strptime(today_str, '%Y-%m-%d')
    
    db = load_json(DB_FILE)
    out_md = ["# LIB TFEX Daily Logs (From 15 May 2026)\n"]
    out_md.append("| Date | Asset | Asset adj | Fee | PnL | Transfer | Unexplained Flow |")
    out_md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    
    prev_asset_adj = 0.0
    prev_ending = 0.0
    
    while curr_d <= today_d:
        d_str = curr_d.strftime('%Y-%m-%d')
        
        transfer = daily_transfers.get(d_str, 0.0)
        confirm = daily_confirms.get(d_str)
        
        if confirm and 'beginning' in confirm:
            asset = confirm.get('beginning', 0.0)
            ending = confirm.get('ending', 0.0)
            opt_short = confirm.get('opt_short', 0.0)
            opt_long = confirm.get('opt_long', 0.0)
            
            asset_adj = asset - opt_short + opt_long
            
            daily_fee = 0.0
            for t in confirm.get('trades', []):
                ctype = get_contract_type(t['code'])
                daily_fee -= t['qty'] * max_fee_per_contract[ctype]
                
            unexplained = asset - prev_ending if prev_ending > 0 else 0.0
            
            if prev_asset_adj > 0:
                pnl = asset_adj - prev_asset_adj - daily_fee - transfer
            else:
                pnl = 0.0
                
            prev_asset_adj = asset_adj
            prev_ending = ending
        else:
            daily_fee = 0.0
            pnl = 0.0
            unexplained = 0.0
            
            if prev_asset_adj > 0:
                asset_adj = prev_asset_adj + transfer
                prev_asset_adj = asset_adj
            else:
                asset_adj = transfer
                if transfer > 0:
                    prev_asset_adj = asset_adj
            
            if prev_ending > 0:
                prev_ending += transfer
                asset = prev_ending
            else:
                if transfer > 0:
                    prev_ending = transfer
                    asset = transfer
                else:
                    asset = 0.0
                    
        warn = " ⚠️" if abs(unexplained) > 0.01 else ""
        out_md.append(f"| {d_str} | {asset:,.2f} | {asset_adj:,.2f} | {daily_fee:,.2f} | {pnl:,.2f} | {transfer:,.2f} | {unexplained:,.2f}{warn} |")
        
        db[d_str] = {
            'asset': asset,
            'asset_adj': asset_adj,
            'fee': daily_fee,
            'pnl': pnl,
            'transfer': transfer,
            'unexplained': unexplained
        }
        
        curr_d += datetime.timedelta(days=1)
        
    save_json(db, DB_FILE)
    
    with open(OUT_FILE, "w", encoding="utf-8") as file:
        file.write("\n".join(out_md))
        
    print(f"\nLog written to {OUT_FILE}")

if __name__ == '__main__':
    process_lib_emails()
