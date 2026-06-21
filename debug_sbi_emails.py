import os
import base64
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

def get_gmail_service():
    creds_path = r"C:\Drive\claude-shared\credentials\token.json"
    scopes = ["https://www.googleapis.com/auth/gmail.readonly"]
    creds = Credentials.from_authorized_user_file(creds_path, scopes)
    return build('gmail', 'v1', credentials=creds)

def main():
    service = get_gmail_service()
    two_months_ago = (datetime.now() - timedelta(days=60)).strftime("%Y/%m/%d")

    # Debug Transfer Out
    print("=== Debug Transfer Out ===")
    query_out = f'from:no-reply-customer@sbito.co.th subject:"Complete Withdraw ATS" after:{two_months_ago}'
    results = service.users().messages().list(userId='me', q=query_out, maxResults=3).execute()
    messages_out = results.get('messages', [])
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
        print(f"Message ID: {msg['id']}")
        print(body[:500])
        print("-" * 20)

    # Debug Trade Activity
    print("=== Debug Trade Activity ===")
    # Remove sender filter and just search for subject to see what it is
    query_trade = f'subject:"Securities Confirmation" after:{two_months_ago}'
    results = service.users().messages().list(userId='me', q=query_trade, maxResults=5).execute()
    messages_trade = results.get('messages', [])
    for msg in messages_trade:
        message = service.users().messages().get(userId='me', id=msg['id']).execute()
        headers = message['payload'].get('headers', [])
        subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'Unknown')
        sender = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown')
        print(f"Msg ID: {msg['id']}, Sender: {sender}, Subject: {subject}")

        # Check for attachments
        parts = message['payload'].get('parts', [])
        for part in parts:
            filename = part.get('filename')
            if filename:
                print(f"  Attachment: {filename}")

if __name__ == '__main__':
    main()
