import os
import base64
import pdfplumber
import re
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

def get_gmail_service():
    creds_path = r"C:\Drive\claude-shared\credentials\token.json"
    scopes = ["https://www.googleapis.com/auth/gmail.readonly"]
    creds = Credentials.from_authorized_user_file(creds_path, scopes)
    service = build('gmail', 'v1', credentials=creds)
    return service

def fetch_and_process():
    service = get_gmail_service()
    
    two_months_ago = (datetime.now() - timedelta(days=60)).strftime("%Y/%m/%d")
    
    # 1. Transfer In
    print("Fetching Transfer In...")
    query_in = f'from:KPLUS@kasikornbank.com subject:"Result of Bill Payment (Success)" "SBI THAI ONLINE SECURITIES" after:{two_months_ago}'
    results = service.users().messages().list(userId='me', q=query_in, maxResults=100).execute()
    messages_in = results.get('messages', [])
    total_transfer_in = 0
    for msg in messages_in:
        message = service.users().messages().get(userId='me', id=msg['id']).execute()
        # extract body
        parts = message['payload'].get('parts', [])
        body = ""
        if not parts:
            body_data = message['payload'].get('body', {}).get('data', '')
            if body_data:
                body = base64.urlsafe_b64decode(body_data.encode('UTF-8')).decode('utf-8', errors='ignore')
        else:
            for part in parts:
                if part['mimeType'] == 'text/html' or part['mimeType'] == 'text/plain':
                    body_data = part['body'].get('data', '')
                    if body_data:
                        body += base64.urlsafe_b64decode(body_data.encode('UTF-8')).decode('utf-8', errors='ignore')
        
        # look for amount. usually "Amount: 1,000.00 THB" or something. let's just dump it for debugging
        # Thai format might be "จำนวนเงิน/Amount (Baht) : 10,000.00"
        match = re.search(r'(?:จำนวนเงิน|Amount).*?([\d,]+\.\d{2})', body)
        if match:
            amount = float(match.group(1).replace(',', ''))
            total_transfer_in += amount
        else:
            print("Transfer in amount not found in msg id", msg['id'])

    print(f"Total Transfer In: {total_transfer_in}")

    # 2. Transfer Out
    print("\nFetching Transfer Out...")
    query_out = f'from:no-reply-customer@sbito.co.th subject:"Complete Withdraw ATS" after:{two_months_ago}'
    results = service.users().messages().list(userId='me', q=query_out, maxResults=100).execute()
    messages_out = results.get('messages', [])
    total_transfer_out = 0
    for msg in messages_out:
        message = service.users().messages().get(userId='me', id=msg['id']).execute()
        parts = message['payload'].get('parts', [])
        body = ""
        if not parts:
            body_data = message['payload'].get('body', {}).get('data', '')
            if body_data:
                body = base64.urlsafe_b64decode(body_data.encode('UTF-8')).decode('utf-8', errors='ignore')
        else:
            for part in parts:
                if part['mimeType'] == 'text/html' or part['mimeType'] == 'text/plain':
                    body_data = part['body'].get('data', '')
                    if body_data:
                        body += base64.urlsafe_b64decode(body_data.encode('UTF-8')).decode('utf-8', errors='ignore')
        
        # Look for amount
        match = re.search(r'(?:Amount|จำนวนเงิน).*?([\d,]+\.\d{2})', body, re.IGNORECASE)
        if match:
            amount = float(match.group(1).replace(',', ''))
            total_transfer_out += amount
        else:
            print("Transfer out amount not found in msg id", msg['id'])
            
    print(f"Total Transfer Out: {total_transfer_out}")

    # 3. Trade Activity
    print("\nFetching Trade Activity...")
    # Sender SBI Thai Online, subject Securities Confirmation
    query_trade = f'subject:"Securities Confirmation" after:{two_months_ago}'
    results = service.users().messages().list(userId='me', q=query_trade, maxResults=100).execute()
    messages_trade = results.get('messages', [])
    
    trade_data = {} # symbol -> {'amount': 0, 'thb': 0}
    total_fee = 0
    
    for idx, msg in enumerate(messages_trade):
        msg_id = msg['id']
        message = service.users().messages().get(userId='me', id=msg_id).execute()
        
        headers = message['payload'].get('headers', [])
        sender = next((h['value'] for h in headers if h['name'] == 'From'), '')
        if 'SBI' not in sender and 'sbi' not in sender.lower():
            continue
            
        parts = message['payload'].get('parts', [])
        for part in parts:
            if part['filename'] and part['filename'].endswith('.pdf'):
                att_id = part['body'].get('attachmentId')
                if att_id:
                    att = service.users().messages().attachments().get(
                        userId='me', messageId=msg_id, id=att_id
                    ).execute()
                    
                    data = att['data']
                    file_data = base64.urlsafe_b64decode(data.encode('UTF-8'))
                    
                    pdf_path = f"sbi_temp_{idx}.pdf"
                    with open(pdf_path, 'wb') as f:
                        f.write(file_data)
                        
                    # Extract text
                    password = "04101983"
                    try:
                        with pdfplumber.open(pdf_path, password=password) as pdf:
                            text = ""
                            for page in pdf.pages:
                                text += page.extract_text() + "\n"
                                
                        # Parse trade data
                        # We need to extract Symbol, Amount Change (+buy, -sell), THB Amount Change (-buy, +sell), Fee
                        lines = text.split('\n')
                        for line in lines:
                            print(f"DEBUG_PDF: {line}")
                    except Exception as e:
                        print(f"Failed to read PDF {pdf_path}: {e}")

if __name__ == '__main__':
    fetch_and_process()
