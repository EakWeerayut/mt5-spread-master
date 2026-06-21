import os
import base64
import re
import csv
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from bs4 import BeautifulSoup

def get_gmail_service():
    creds_path = r"C:\Drive\claude-shared\credentials\token.json"
    scopes = ["https://www.googleapis.com/auth/gmail.readonly"]
    creds = Credentials.from_authorized_user_file(creds_path, scopes)
    service = build('gmail', 'v1', credentials=creds)
    return service

def fetch_and_process():
    service = get_gmail_service()
    
    three_months_ago = (datetime.now() - timedelta(days=90)).strftime("%Y/%m/%d")
    
    print(f"Fetching KA emails after {three_months_ago}...")
    query = f'from:ka.CyberInvest@kasikornasset.com subject:"Confirming investment unit transactions" after:{three_months_ago}'
    results = service.users().messages().list(userId='me', q=query, maxResults=100).execute()
    messages = results.get('messages', [])
    
    if not messages:
        print("No messages found.")
        return
        
    extracted_data = []
    
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
                        
        soup = BeautifulSoup(body, 'html.parser')
        tables = soup.find_all('table')
        
        # Assume the first table is the Thai table, let's find the correct table by looking for "ราคา ณ วันที่"
        for table in tables:
            rows = table.find_all('tr')
            if not rows:
                continue
                
            headers = [th.get_text(strip=True) for th in rows[0].find_all(['th', 'td'])]
            if "ราคา ณ วันที่" in headers or "ราคา ณ วันที" in headers or "ราคา ณ วันท" in headers[0]:
                for row in rows[1:]:
                    cols = row.find_all('td')
                    if len(cols) >= 11:
                        date = cols[0].get_text(strip=True)
                        txn_type = cols[1].get_text(strip=True)
                        fund = cols[2].get_text(strip=True)
                        unit_str = cols[5].get_text(strip=True).replace(',', '')
                        amount_str = cols[6].get_text(strip=True).replace(',', '')
                        price_str = cols[7].get_text(strip=True).replace(',', '')
                        remark = cols[10].get_text(strip=True)
                        
                        try:
                            unit = float(unit_str)
                        except ValueError:
                            unit = 0.0
                            
                        # Apply logic for + or -
                        if "จาก" in remark:
                            unit_signed = unit
                        elif "ไป" in remark:
                            unit_signed = -unit
                        elif "ซื้อ" in txn_type or "สับเปลี่ยนเข้า" in txn_type:
                            unit_signed = unit
                        elif "ขาย" in txn_type or "สับเปลี่ยนออก" in txn_type:
                            unit_signed = -unit
                        else:
                            unit_signed = unit # default
                            
                        extracted_data.append({
                            'Date': date,
                            'Fund': fund,
                            'Unit': unit_signed,
                            'Price': price_str,
                            'Amount': amount_str,
                            'Remark': remark,
                            'TxnType': txn_type
                        })
                break # We processed the Thai table, skip English table
                
    # Sort by Date
    # Date format is DD/MM/YYYY where YYYY is Thai year (CE + 543)
    def parse_date(d_str):
        try:
            parts = d_str.split('/')
            return datetime(int(parts[2]) - 543, int(parts[1]), int(parts[0]))
        except:
            return datetime(1970, 1, 1)
            
    extracted_data.sort(key=lambda x: parse_date(x['Date']))
    
    # Save to CSV
    with open('ka_transactions.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Date', 'Fund', 'Unit', 'Price', 'Amount', 'Remark', 'TxnType'])
        for row in extracted_data:
            writer.writerow([row['Date'], row['Fund'], row['Unit'], row['Price'], row['Amount'], row['Remark'], row['TxnType']])
            
    print(f"Extracted {len(extracted_data)} rows.")

if __name__ == '__main__':
    fetch_and_process()
