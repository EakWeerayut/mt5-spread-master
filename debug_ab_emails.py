import os
import base64
import pdfplumber
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
    
    print("Fetching Aberdeen emails...")
    query = f'from:donotreply@aberdeenplc.com subject:"หนังสือรับรองสิทธิในหน่วยลงทุน"'
    results = service.users().messages().list(userId='me', q=query, maxResults=10).execute()
    messages = results.get('messages', [])
    
    if not messages:
        print("No messages found.")
        return
        
    for idx, msg in enumerate(messages):
        msg_id = msg['id']
        message = service.users().messages().get(userId='me', id=msg_id).execute()
        
        parts = message['payload'].get('parts', [])
        
        def find_pdf_part(parts):
            for part in parts:
                mime_type = part.get('mimeType', '')
                filename = part.get('filename', '')
                if filename and filename.lower().endswith('.pdf'):
                    return part
                if 'parts' in part:
                    res = find_pdf_part(part['parts'])
                    if res: return res
            return None
            
        pdf_part = find_pdf_part(parts)
        if pdf_part:
            print(f"Found PDF part in {msg_id}: {pdf_part.get('filename')}")
            att_id = pdf_part['body'].get('attachmentId')
            if att_id:
                att = service.users().messages().attachments().get(
                    userId='me', messageId=msg_id, id=att_id
                ).execute()
                
                data = att['data']
                file_data = base64.urlsafe_b64decode(data.encode('UTF-8'))
                
                pdf_path = f"ab_temp_{idx}.pdf"
                with open(pdf_path, 'wb') as f:
                    f.write(file_data)
                    
                print(f"Downloaded PDF: {pdf_path}")
                
                # Extract text
                password = "04101983"
                try:
                    with pdfplumber.open(pdf_path, password=password) as pdf:
                        text = ""
                        for page in pdf.pages:
                            text += page.extract_text() + "\n"
                            
                    with open(f'ab_text_{idx}.txt', 'w', encoding='utf-8') as f:
                        f.write(text)
                    print(f"Text extracted to ab_text_{idx}.txt")
                except Exception as e:
                    print(f"Failed to read PDF {pdf_path}: {e}")
        else:
            print(f"No PDF part found in {msg_id}.")

if __name__ == '__main__':
    fetch_and_process()
