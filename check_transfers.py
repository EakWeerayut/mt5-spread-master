from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
creds = Credentials.from_authorized_user_file(r'C:\Drive\claude-shared\credentials\token.json', ['https://www.googleapis.com/auth/gmail.readonly'])
service = build('gmail', 'v1', credentials=creds)

print('--- TRANSFER IN ---')
query_in = 'from:KPLUS@kasikornbank.com subject:"Result of Bill Payment (Success)" "SBI THAI ONLINE SECURITIES" after:2026/04/17'
messages = service.users().messages().list(userId='me', q=query_in, maxResults=100).execute().get('messages', [])
for msg in messages:
    message = service.users().messages().get(userId='me', id=msg['id']).execute()
    headers = message['payload'].get('headers', [])
    date_str = next((h['value'] for h in headers if h['name'] == 'Date'), '')
    print(msg['id'], date_str)

print('--- TRANSFER OUT ---')
query_out = 'from:no-reply-customer@sbito.co.th subject:"Complete Withdraw ATS" after:2026/04/17'
messages = service.users().messages().list(userId='me', q=query_out, maxResults=100).execute().get('messages', [])
for msg in messages:
    message = service.users().messages().get(userId='me', id=msg['id']).execute()
    headers = message['payload'].get('headers', [])
    date_str = next((h['value'] for h in headers if h['name'] == 'Date'), '')
    print(msg['id'], date_str)
