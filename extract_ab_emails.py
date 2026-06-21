import os
import base64
import pdfplumber
import re
import csv
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
    
    print(f"Fetching Aberdeen emails...")
    query = f'from:donotreply@aberdeenplc.com subject:"หนังสือรับรองสิทธิในหน่วยลงทุน"'
    results = service.users().messages().list(userId='me', q=query, maxResults=100).execute()
    messages = results.get('messages', [])
    
    if not messages:
        print("No messages found.")
        return
        
    extracted_data = []
    
    for idx, msg in enumerate(messages):
        msg_id = msg['id']
        message = service.users().messages().get(userId='me', id=msg_id).execute()
        
        parts = message['payload'].get('parts', [])
        
        def find_pdf_part(parts):
            for part in parts:
                filename = part.get('filename', '')
                if filename and filename.lower().endswith('.pdf'):
                    return part
                if 'parts' in part:
                    res = find_pdf_part(part['parts'])
                    if res: return res
            return None
            
        pdf_part = find_pdf_part(parts)
        if pdf_part:
            print(f"Processing PDF from message {msg_id}...")
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
                
                # Extract text
                password = "04101983"
                try:
                    with pdfplumber.open(pdf_path, password=password) as pdf:
                        for page in pdf.pages:
                            text = page.extract_text()
                            if not text:
                                continue
                            
                            lines = text.split('\n')
                            
                            fund_name = ""
                            txn_date = ""
                            
                            for i, line in enumerate(lines):
                                # Look for Fund Name
                                if "Fund Name :" in line or "Fund Name" in line:
                                    match = re.search(r'\((.*?)\)', line)
                                    if match:
                                        fund_name = match.group(1)
                                        
                                # Look for Transaction Date
                                if "Transaction Date" in line or "วนนทษททกกรกยกกร" in line:
                                    match = re.search(r'(\d{2}/\d{2}/\d{4})', line)
                                    if match:
                                        txn_date = match.group(1)
                                        
                                # Look for สับเปลี่ยนเข้า
                                if "สับเปลี่ยนเข้า" in line and "SWI" in line:
                                    parts_line = line.split()
                                    # Expected format: สับเปลี่ยนเข้า (SWI) Amount Price Unit ...
                                    # Sometimes parts_line might be ['สับเปลี่ยนเข้า', '(SWI)', '2,018,605.22', '13.2768', '152,040.0412', '0.00', '0.00', '0.00']
                                    try:
                                        idx_swi = parts_line.index('(SWI)')
                                        amount = parts_line[idx_swi+1].replace(',', '')
                                        price = parts_line[idx_swi+2].replace(',', '')
                                        unit = parts_line[idx_swi+3].replace(',', '')
                                        
                                        extracted_data.append({
                                            'Date': txn_date,
                                            'Fund': fund_name,
                                            'Unit': float(unit), # positive
                                            'Price': price,
                                            'Amount': amount,
                                            'TxnType': 'สับเปลี่ยนเข้า'
                                        })
                                    except Exception as e:
                                        print("Error parsing SWI:", line, e)
                                        
                                # Look for สับเปลี่ยนออก-หน่วย
                                if "สับเปลี่ยนออก-หน่วย" in line:
                                    # The numbers are usually on the next line
                                    if i + 1 < len(lines):
                                        next_line = lines[i+1]
                                        parts_line = next_line.split()
                                        # Expected: Amount Price Unit ...
                                        try:
                                            amount = parts_line[0].replace(',', '')
                                            price = parts_line[1].replace(',', '')
                                            unit = parts_line[2].replace(',', '')
                                            
                                            extracted_data.append({
                                                'Date': txn_date,
                                                'Fund': fund_name,
                                                'Unit': -float(unit), # negative
                                                'Price': price,
                                                'Amount': amount,
                                                'TxnType': 'สับเปลี่ยนออก'
                                            })
                                        except Exception as e:
                                            print("Error parsing SWO:", next_line, e)
                                            
                except Exception as e:
                    print(f"Failed to process PDF {pdf_path}: {e}")
                
                # clean up
                os.remove(pdf_path)
                
    def parse_date(d_str):
        try:
            return datetime.strptime(d_str, "%dd/%mm/%Y")
        except:
            # Maybe Thai year? Let's check if year is > 2500
            try:
                parts = d_str.split('/')
                y = int(parts[2])
                if y > 2500:
                    y -= 543
                return datetime(y, int(parts[1]), int(parts[0]))
            except:
                return datetime(1970, 1, 1)

    extracted_data.sort(key=lambda x: parse_date(x['Date']))
    
    with open('ab_transactions.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Date', 'Fund', 'Unit', 'Price', 'Amount', 'TxnType'])
        for row in extracted_data:
            writer.writerow([row['Date'], row['Fund'], row['Unit'], row['Price'], row['Amount'], row['TxnType']])
            
    print(f"Extracted {len(extracted_data)} rows.")

if __name__ == '__main__':
    fetch_and_process()
