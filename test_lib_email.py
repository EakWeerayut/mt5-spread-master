import os
import base64
import pdfplumber
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

def get_gmail_service():
    creds_path = r"C:\Drive\claude-shared\credentials\token.json"
    scopes = ["https://www.googleapis.com/auth/gmail.readonly"]
    creds = Credentials.from_authorized_user_file(creds_path, scopes)
    service = build('gmail', 'v1', credentials=creds)
    return service

def fetch_latest_pdfs():
    service = get_gmail_service()
    
    query = 'subject:"LIB E Confirm Tfex" OR subject:"LIB ใบรับฝาก"'
    results = service.users().messages().list(userId='me', q=query, maxResults=5).execute()
    messages = results.get('messages', [])
    
    if not messages:
        print("No emails found.")
        return
        
    for idx, msg in enumerate(messages):
        msg_id = msg['id']
        message = service.users().messages().get(userId='me', id=msg_id).execute()
        
        # Get subject
        headers = message['payload'].get('headers', [])
        subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'Unknown')
        print(f"\nEmail: {subject}")
        
        # Find attachment
        parts = message['payload'].get('parts', [])
        for part in parts:
            if part['filename'] and part['filename'].endswith('.pdf'):
                att_id = part['body'].get('attachmentId')
                if att_id:
                    print(f"Downloading attachment: {part['filename']}")
                    att = service.users().messages().attachments().get(
                        userId='me', messageId=msg_id, id=att_id
                    ).execute()
                    
                    data = att['data']
                    file_data = base64.urlsafe_b64decode(data.encode('UTF-8'))
                    
                    pdf_path = f"temp_{idx}.pdf"
                    with open(pdf_path, 'wb') as f:
                        f.write(file_data)
                        
                    # Extract text
                    password = os.environ.get('LIB_PDF_PASSWORD')
                    try:
                        with pdfplumber.open(pdf_path, password=password) as pdf:
                            text = ""
                            for page in pdf.pages:
                                text += page.extract_text() + "\n"
                        
                        txt_path = f"temp_{idx}.txt"
                        with open(txt_path, 'w', encoding='utf-8') as f:
                            f.write(text)
                        print(f"Extracted text saved to {txt_path}")
                        
                        # Print first few lines
                        print("--- Preview ---")
                        print("\n".join(text.splitlines()[:15]))
                    except Exception as e:
                        print(f"Failed to read PDF: {e}")

if __name__ == '__main__':
    fetch_latest_pdfs()
