import os
import base64
import re
import pdfplumber
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from bs4 import BeautifulSoup

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

    results_data = {
        'transfer_in': 0,
        'transfer_out': 0,
        'trades': {},
        'total_fee': 0.0
    }

    # 1. Transfer In
    print("Processing Transfer In...")
    query_in = f'from:KPLUS@kasikornbank.com subject:"Result of Bill Payment (Success)" "SBI THAI ONLINE SECURITIES" after:{two_months_ago}'
    messages = service.users().messages().list(userId='me', q=query_in, maxResults=100).execute().get('messages', [])
    for msg in messages:
        message = service.users().messages().get(userId='me', id=msg['id']).execute()
        body = get_body_recursive(message['payload'])
        text = BeautifulSoup(body, 'html.parser').get_text()
        match = re.search(r'(?:จำนวนเงิน|Amount).*?([\d,]+\.\d{2})', text, re.IGNORECASE)
        if match:
            results_data['transfer_in'] += float(match.group(1).replace(',', ''))

    # 2. Transfer Out
    print("Processing Transfer Out...")
    query_out = f'from:no-reply-customer@sbito.co.th subject:"Complete Withdraw ATS" after:{two_months_ago}'
    messages = service.users().messages().list(userId='me', q=query_out, maxResults=100).execute().get('messages', [])
    for msg in messages:
        message = service.users().messages().get(userId='me', id=msg['id']).execute()
        body = get_body_recursive(message['payload'])
        text = BeautifulSoup(body, 'html.parser').get_text()
        
        # Fallback to direct HTML if bs4 fails to find it
        if not re.search(r'([\d,]+\.\d{2})', text):
             text = body
             
        # Look for typical number format 12,345.67
        matches = re.findall(r'([\d,]+\.\d{2})', text)
        if matches:
            # The withdrawal amount is usually the largest number or the only one that makes sense
            amounts = [float(m.replace(',', '')) for m in matches]
            # Print for debug if multiple amounts found
            results_data['transfer_out'] += max(amounts) # naive assumption, refine if needed

    # 3. Trade Activity
    print("Processing Trade Activity...")
    query_trade = f'subject:"Securities Confirmation" after:{two_months_ago}'
    messages = service.users().messages().list(userId='me', q=query_trade, maxResults=100).execute().get('messages', [])
    
    password = "04101983"
    
    for idx, msg in enumerate(messages):
        message = service.users().messages().get(userId='me', id=msg['id']).execute()
        headers = message['payload'].get('headers', [])
        sender = next((h['value'] for h in headers if h['name'] == 'From'), '')
        
        if 'sbi' not in sender.lower(): continue
        
        attachments = get_attachments_recursive(service, 'me', msg['id'], message['payload'])
        for filename, file_data in attachments:
            pdf_path = f"sbi_temp_{idx}.pdf"
            with open(pdf_path, 'wb') as f:
                f.write(file_data)
                
            try:
                with pdfplumber.open(pdf_path, password=password) as pdf:
                    for page in pdf.pages:
                        text = page.extract_text()
                        if text:
                            # Parse trade data.
                            # We just dump the text to a file for analysis because the format is unknown
                            with open(f"sbi_trade_{idx}.txt", "a", encoding="utf-8") as tf:
                                tf.write(text + "\n")
            except Exception as e:
                print(f"Failed to read PDF {pdf_path}: {e}")

    print("--- RESULTS ---")
    print(f"Transfer In: {results_data['transfer_in']}")
    print(f"Transfer Out: {results_data['transfer_out']}")
    print("Trades extracted to sbi_trade_*.txt files. Please analyze them.")

if __name__ == '__main__':
    main()
