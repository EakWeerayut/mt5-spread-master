import os
import base64
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
    
    three_months_ago = (datetime.now() - timedelta(days=90)).strftime("%Y/%m/%d")
    
    print("Fetching KA emails...")
    query = f'from:ka.CyberInvest@kasikornasset.com subject:"Confirming investment unit transactions" after:{three_months_ago}'
    results = service.users().messages().list(userId='me', q=query, maxResults=5).execute()
    messages = results.get('messages', [])
    
    if not messages:
        print("No messages found.")
        return
        
    for msg in messages:
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
        
        with open('ka_email_debug.txt', 'w', encoding='utf-8') as f:
            f.write(f"--- Email ID: {msg['id']} ---\n")
            f.write(body)
            f.write("\n" + "-" * 50 + "\n")
        break # Only print one for now

if __name__ == '__main__':
    fetch_and_process()
