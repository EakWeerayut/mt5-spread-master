import subprocess
import sys
import os

def run_script(script_path):
    print(f"\n==================================================")
    print(f"Running: {script_path}")
    print(f"==================================================")
    
    try:
        # Run the script and stream the output to the console
        result = subprocess.run(
            [sys.executable, script_path],
            check=True,
            text=True
        )
        print(f"\n✅ Successfully completed: {script_path}")
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Error running {script_path}. Exit code: {e.returncode}")
    except Exception as e:
        print(f"\n❌ Failed to execute {script_path}: {e}")

if __name__ == "__main__":
    # Ensure we are in the root directory (where this script is located)
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    scripts_to_run = [
        os.path.join("dashboard", "generate_binance_daily_log.py"),
        os.path.join("dashboard", "generate_deribit_daily_log.py"),
        os.path.join("dashboard", "generate_mt5_daily_log.py"),
        os.path.join("dashboard", "generate_lib_daily_log.py"),
    ]
    
    print("Starting Portfolio Tracker Update...")
    for script in scripts_to_run:
        if os.path.exists(script):
            run_script(script)
        else:
            print(f"\n⚠️ Warning: Script not found - {script}")
            
    print("\n==================================================")
    print("🎉 All updates finished!")
    print("==================================================")
