import os
import subprocess

def main():
    print("=== Step 1/3: Downloading Latest Funding Rates ===")
    subprocess.run(["python", "download_funding.py"], check=True)
    
    print("\n=== Step 2/3: Generating Daily Summary & Fetching BTC Price ===")
    subprocess.run(["python", "export_daily_summary.py"], check=True)
    
    print("\n=== Step 3/3: Generating Weekly Summary ===")
    subprocess.run(["python", "export_weekly.py"], check=True)
    
    print("\n✅ All done! 'weekly_funding_summary.csv' is now fully updated.")

if __name__ == "__main__":
    # Change into the funding fee directory where the scripts live
    target_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "funding fee")
    os.chdir(target_dir)
    main()
