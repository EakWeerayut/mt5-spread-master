import json
import csv

def main():
    state = {
        'last_update_date': '2026-06-17',
        'current_cash': 30432.11,
        'stocks': {}
    }
    
    with open('sbi_holdings.csv', 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row['symbol'] or row['filename'] != 'SBI.jpg': continue
            sym = row['symbol']
            qty = float(row['amount'])
            avg = float(row['avg'])
            
            image_amounts = {
                'AWC': 8945.84, 'CKP': 19861.40, 'CPNREIT': 19226.85, 'CRC': 17835.64,
                'DUSIT': 19587.17, 'HTECH': 19715.29, 'JMT': 21618.96, 'M': 18376.10,
                'NFC': 12250.74, 'PCC': 9732.53
            }
            if sym in image_amounts: amount = image_amounts[sym]
            elif sym == 'SJWD': amount = 20517.98
            elif sym == 'SCAP': amount = 19457.06 * (14000/18000)
            else: amount = qty * avg
            
            state['stocks'][sym] = {'qty': qty, 'avg': avg, 'amount': amount}

    with open('portfolio_state.json', 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=4)
        
    print("portfolio_state.json created successfully.")

if __name__ == '__main__':
    main()
