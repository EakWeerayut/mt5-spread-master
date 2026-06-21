import os, base64, pdfplumber
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()
creds_path = r'C:\Drive\claude-shared\credentials\token.json'
creds = Credentials.from_authorized_user_file(creds_path, ['https://www.googleapis.com/auth/gmail.readonly'])
service = build('gmail', 'v1', credentials=creds)

query = 'subject:"LIB ใบรับฝาก"'
results = service.users().messages().list(userId='me', q=query, maxResults=2).execute()
messages = results.get('messages', [])
if not messages:
    print("No messages found")
for idx, msg in enumerate(messages):
    msg_id = msg['id']
    message = service.users().messages().get(userId='me', id=msg_id).execute()
    parts = message['payload'].get('parts', [])
    for part in parts:
        if part['filename'] and part['filename'].endswith('.pdf'):
            att_id = part['body'].get('attachmentId')
            if att_id:
                att = service.users().messages().attachments().get(userId='me', messageId=msg_id, id=att_id).execute()
                data = att['data']
                file_data = base64.urlsafe_b64decode(data.encode('UTF-8'))
                pdf_path = f'temp_dep_{idx}.pdf'
                with open(pdf_path, 'wb') as f: f.write(file_data)
                
                with pdfplumber.open(pdf_path, password=os.environ.get('LIB_PDF_PASSWORD')) as pdf:
                    text = ''
                    for page in pdf.pages: text += page.extract_text() + '\n'
                    with open(f'temp_dep_{idx}.txt', 'w', encoding='utf-8') as f: f.write(text)
                    print(f'Saved temp_dep_{idx}.txt')
