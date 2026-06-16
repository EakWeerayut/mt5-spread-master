import subprocess
import sys
import os

def main():
    # The root project folder is the directory containing this script
    root_dir = os.path.dirname(os.path.abspath(__file__))
    
    print("==================================================")
    print("      Starting Automated Spread Data Update       ")
    print("==================================================")
    
    try:
        print("\n[1/2] Fetching latest data from MT5 (Appending to existing files)...")
        # Run fetch_mt5_h1.py located in the root directory
        fetch_script = os.path.join(root_dir, "fetch_mt5_h1.py")
        subprocess.run([sys.executable, fetch_script], cwd=root_dir, check=True)
        
        print("\n[2/2] Aligning timezones, switching contracts, and calculating spreads...")
        # Run custom_merge.py located in spread/scripts/
        merge_script = os.path.join(root_dir, "spread", "scripts", "custom_merge.py")
        subprocess.run([sys.executable, merge_script], cwd=root_dir, check=True)
        
        print("\n==================================================")
        print(" [SUCCESS]: All files updated successfully! ")
        print(" Final files are ready in the historical_data/ folder:")
        print("  - historical_data/Gold_H1_Final.csv")
        print("  - historical_data/Oil_H1_Final_v3.csv")
        print("==================================================")
        
    except subprocess.CalledProcessError as e:
        print(f"\n[ERROR]: An error occurred while running the scripts.")
        print(f"Error details: {e}")
    except Exception as e:
        print(f"\n[UNEXPECTED ERROR]: {e}")

if __name__ == "__main__":
    main()
