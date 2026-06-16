import pandas as pd
import glob

def check_dates(prefix, order):
    print(f"--- Dates for {prefix} ---")
    for suffix in order:
        file_path = f"historical_data/{prefix}{suffix}_H1_MTS.csv"
        try:
            df = pd.read_csv(file_path)
            start_date = df['time'].min()
            end_date = df['time'].max()
            print(f"{suffix}: starts {start_date} | ends {end_date} | count {len(df)}")
        except Exception as e:
            print(f"Error reading {file_path}: {e}")

cmx_order = ["M6", "Q6", "Z6", "G7"]
nyx_order = ["N6", "Q6", "U6", "V6"]

check_dates("CMX.MGC", cmx_order)
check_dates("NYX.MCLE", nyx_order)
