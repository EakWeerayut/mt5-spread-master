import pandas as pd
import os

def load_and_rename(filepath, prefix, shift_hours=0):
    if not os.path.exists(filepath):
        return pd.DataFrame()
    df = pd.read_csv(filepath)
    df['time'] = pd.to_datetime(df['time'])
    
    # Adjust time zone shift
    if shift_hours != 0:
        df['time'] = df['time'] - pd.Timedelta(hours=shift_hours)
    
    # Calculate mid price if not exists
    if 'mid' not in df.columns:
        if 'bid' in df.columns and 'offer' in df.columns:
            df['price'] = (df['bid'] + df['offer']) / 2
        elif 'close' in df.columns:
            df['price'] = df['close']
    else:
        df['price'] = df['mid']
        
    cols_to_keep = ['time', 'price']
    rename_dict = {'price': prefix}
    
    if 'contract' in df.columns:
        cols_to_keep.append('contract')
        rename_dict['contract'] = f'{prefix}_contract'
        
    df = df[cols_to_keep].rename(columns=rename_dict)
    return df

def merge_group(name, file_configs):
    dfs = []
    for filepath, prefix, shift in file_configs:
        df = load_and_rename(filepath, prefix, shift)
        if not df.empty:
            dfs.append(df)
            
    if not dfs:
        print(f"No data found for {name}.")
        return

    merged_df = dfs[0]
    for df in dfs[1:]:
        merged_df = pd.merge(merged_df, df, on='time', how='inner')
        
    merged_df = merged_df.sort_values('time').reset_index(drop=True)
    
    output_path = f'historical_data/{name}_H1_Merged_Aligned.csv'
    merged_df.to_csv(output_path, index=False)
    print(f"Successfully merged and ALIGNED {name}! Total valid rows: {len(merged_df)}")
    print(f"Saved to {output_path}")

def main():
    gold_files = [
        ('historical_data/CMX.MGC_Continuous_H1.csv', 'CMX.MGC', 0),
        ('historical_data/XAUUSD.sc_H1_Vantage.csv', 'XAUUSD.sc', 3)
    ]
    
    oil_files = [
        ('historical_data/NYX.MCLE_Continuous_H1.csv', 'NYX.MCLE', 0),
        ('historical_data/USOUSD.sc_H1_Vantage.csv', 'USOUSD.sc', 3),
        ('historical_data/UKOUSD.sc_H1_Vantage.csv', 'UKOUSD.sc', 3)
    ]

    print("--- Processing Gold (Time Aligned) ---")
    merge_group('Gold', gold_files)
    
    print("\n--- Processing Oil (Time Aligned) ---")
    merge_group('Oil', oil_files)

if __name__ == '__main__':
    main()
