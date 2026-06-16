import pandas as pd
import glob
import os

def merge_newest_contract(prefix, output_filename, order_list):
    print(f"Merging {prefix} (Newest Priority)...")
    dfs = []
    
    for suffix in order_list:
        file_path = f"historical_data/{prefix}{suffix}_H1_MTS.csv"
        if not os.path.exists(file_path):
            print(f"File not found: {file_path}")
            continue
            
        df = pd.read_csv(file_path)
        df['time'] = pd.to_datetime(df['time'])
        df['contract'] = f"{prefix}{suffix}"
        dfs.append(df)
        
    if not dfs:
        print("No data to merge.")
        return

    continuous_df = pd.DataFrame()
    
    for i in range(len(dfs)):
        df_current = dfs[i]
        
        # Determine the cut-off date. It is the start date of the NEXT contract.
        if i + 1 < len(dfs):
            next_start = dfs[i+1]['time'].min()
            # Keep data in df_current strictly before next_start
            df_current = df_current[df_current['time'] < next_start]
            
        continuous_df = pd.concat([continuous_df, df_current])
        
    continuous_df = continuous_df.sort_values('time').reset_index(drop=True)
    continuous_df.to_csv(f"historical_data/{output_filename}", index=False)
    print(f"Successfully merged {prefix}! Total rows: {len(continuous_df)}")
    print(f"Saved to historical_data/{output_filename}\n")

if __name__ == "__main__":
    cmx_order = ["M6", "Q6", "Z6", "G7"]
    merge_newest_contract("CMX.MGC", "CMX.MGC_Continuous_H1.csv", cmx_order)
    
    nyx_order = ["N6", "Q6", "U6", "V6"]
    merge_newest_contract("NYX.MCLE", "NYX.MCLE_Continuous_H1.csv", nyx_order)
