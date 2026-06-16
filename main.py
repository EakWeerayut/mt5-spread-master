import argparse
import sys
from dotenv import load_dotenv

load_dotenv()

PORTFOLIO_SOURCES = ["sbi", "binance", "deribit", "mt5", "lib"]
SOURCES = PORTFOLIO_SOURCES


def run_connector(name: str, **kwargs) -> tuple[bool, dict | None]:
    if name == "sbi":
        from connectors.sbi import fetch
    elif name == "binance":
        from connectors.binance import fetch
    elif name == "deribit":
        from connectors.deribit import fetch
    elif name == "mt5":
        from connectors.mt5 import fetch
    elif name == "lib":
        from connectors.lib import fetch
    else:
        print(f"Unknown source: {name}")
        return False, None

    print(f"\n[{name.upper()}] Fetching data...")
    try:
        data = fetch(**kwargs)
        print(f"[{name.upper()}] Done.")
        return True, data
    except Exception as e:
        error_msg = str(e).encode('ascii', errors='replace').decode('ascii')
        print(f"[{name.upper()}] ERROR: {error_msg}")
        return False, None


def main():
    parser = argparse.ArgumentParser(
        description="Portfolio Tracker — aggregate positions from multiple platforms into Google Sheets"
    )
    parser.add_argument(
        "--source",
        choices=SOURCES + ["all"],
        default="all",
        help="Which platform to fetch (default: all).",
    )
    parser.add_argument(
        "--sbi-mode",
        choices=["ocr-review", "ocr", "csv"],
        default="ocr",
        dest="sbi_mode",
        help="SBI extraction mode: ocr (OCR only, default), ocr-review (OCR+Claude verify), csv (skip Drive/OCR, read local CSV)",
    )
    parser.add_argument(
        "--ai",
        choices=["claude", "agy"],
        default="claude",
        help="AI CLI to use for OCR review (default: claude).",
    )
    args = parser.parse_args()

    if args.source == "all":
        sources = SOURCES
    else:
        sources = [args.source]

    print("=" * 60)
    print("Portfolio Tracker")
    print("=" * 60)

    results = {}
    failed = []

    for source in sources:
        kwargs = {}
        if source == "sbi":
            kwargs["mode"] = args.sbi_mode
            kwargs["ai_reviewer"] = args.ai
        ok, data = run_connector(source, **kwargs)
        if ok and data is not None:
            results[source] = data
        else:
            failed.append(source)

    if not results:
        print("\nNo data collected. Exiting without writing to Sheets.")
        sys.exit(1)

    print("\n[Sheets] Writing collected data to Google Sheets...")
    try:
        from sheets.writer import write_all
        url = write_all(results)
        print(f"\n[Sheets] All done. Spreadsheet: {url}")
    except Exception as e:
        print(f"\n[Sheets] ERROR writing to Sheets: {e}")
        sys.exit(1)

    if failed:
        print(f"\nWarning: the following sources failed and were skipped: {', '.join(failed)}")

    print("\nDone.")


if __name__ == "__main__":
    main()
