import csv
import json
import hashlib
import os
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
import sys
sys.path.insert(0, r"C:\Git\credentials")
from central_creds import get_credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io

load_dotenv()

CACHE_FILE = Path(__file__).parent.parent / ".sbi_cache.json"
TMP_DIR = Path(tempfile.gettempdir()) / "sbi"
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

CSV_SUMMARY = Path(__file__).parent.parent / "sbi_summary.csv"
CSV_HOLDINGS = Path(__file__).parent.parent / "sbi_holdings.csv"
CSV_STOP_ORDERS = Path(__file__).parent.parent / "sbi_stop_orders.csv"


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _load_cache() -> dict:
    if CACHE_FILE.exists():
        with open(CACHE_FILE, "r") as f:
            return json.load(f)
    return {}


def _save_cache(cache: dict):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


def _md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


# ---------------------------------------------------------------------------
# Google Drive helpers
# ---------------------------------------------------------------------------

def _get_drive_service():
    creds = get_credentials(SCOPES)
    return build("drive", "v3", credentials=creds)


def _list_images(service, folder_id: str) -> list[dict]:
    query = (
        f"'{folder_id}' in parents and trashed=false and "
        f"(mimeType = 'image/jpeg' or mimeType = 'image/png')"
    )
    results = service.files().list(
        q=query,
        fields="files(id, name, mimeType)",
        pageSize=200,
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    return results.get("files", [])


def _download_file(service, file_id: str) -> bytes:
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()


# ---------------------------------------------------------------------------
# CSV export / import
# ---------------------------------------------------------------------------

def _export_to_csv(records: list[dict]):
    with open(CSV_SUMMARY, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["filename", "image_type", "total_amount", "line_available"])
        for r in records:
            w.writerow([r["name"], r.get("image_type", ""), r.get("total_amount", ""), r.get("line_available", "")])

    with open(CSV_HOLDINGS, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["filename", "symbol", "side", "amount", "avg", "market", "upnl_pct"])
        for r in records:
            for h in r.get("holdings", []):
                w.writerow([r["name"], h["symbol"], h.get("side", ""), h.get("amount", ""),
                             h.get("avg", ""), h.get("market", ""), h.get("upnl_pct", "")])

    with open(CSV_STOP_ORDERS, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["filename", "symbol", "side", "type", "trigger_price", "volume"])
        for r in records:
            for o in r.get("stop_orders", []):
                w.writerow([r["name"], o["symbol"], o.get("side", ""), o.get("type", ""),
                             o.get("trigger_price", ""), o.get("volume", "")])

    print(f"  [SBI] Exported CSV backup: {CSV_SUMMARY.name}, {CSV_HOLDINGS.name}, {CSV_STOP_ORDERS.name}")


def _load_from_csv(name: str) -> dict | None:
    if not CSV_SUMMARY.exists():
        return None

    result = {"total_amount": None, "line_available": None, "image_type": "unknown", "holdings": [], "stop_orders": []}
    found = False

    with open(CSV_SUMMARY, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["filename"] == name:
                found = True
                result["image_type"] = row.get("image_type", "unknown")
                result["total_amount"] = float(row["total_amount"]) if row.get("total_amount") else None
                result["line_available"] = float(row["line_available"]) if row.get("line_available") else None
                break

    if not found:
        return None

    if CSV_HOLDINGS.exists():
        with open(CSV_HOLDINGS, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row["filename"] == name:
                    result["holdings"].append({
                        "symbol": row["symbol"],
                        "side": row.get("side", ""),
                        "amount": float(row["amount"]) if row.get("amount") else None,
                        "avg": float(row["avg"]) if row.get("avg") else None,
                        "market": float(row["market"]) if row.get("market") else None,
                        "upnl_pct": float(row["upnl_pct"]) if row.get("upnl_pct") else None,
                    })

    if CSV_STOP_ORDERS.exists():
        with open(CSV_STOP_ORDERS, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row["filename"] == name:
                    result["stop_orders"].append({
                        "symbol": row["symbol"],
                        "side": row.get("side", ""),
                        "type": row.get("type", "Stop"),
                        "trigger_price": float(row["trigger_price"]) if row.get("trigger_price") else None,
                        "volume": float(row["volume"]) if row.get("volume") else None,
                    })

    csv_updated = datetime.fromtimestamp(CSV_SUMMARY.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    result["csv_updated"] = csv_updated
    return result


# ---------------------------------------------------------------------------
# Extraction modes
# ---------------------------------------------------------------------------

_KNOWN_CLIS = ["claude", "agy"]
_ai_failed_clis: set[str] = set()

def _extract_ocr(image_path: str) -> dict:
    from connectors.sbi_parser import parse_image
    return parse_image(image_path)


def _extract_ocr_review(image_path: str, ocr_result: dict, ai_reviewer: str = "claude") -> dict:
    """Send OCR JSON + original image to AI for verification."""
    ocr_json = json.dumps(ocr_result, ensure_ascii=False, indent=2)
    prompt = (
        f"Read the image at this path: {image_path}\n\n"
        f"OCR extracted the following JSON from this SBI Securities screenshot:\n{ocr_json}\n\n"
        "Please verify against the original image and return a corrected JSON with the same structure.\n"
        "Focus on: symbol names (case, digit/letter confusion), numeric values, side (Long/Short/Buy/Sell).\n"
        "Crucial OCR fixes to check:\n"
        "- Ensure the stock symbol 'PMC' is read correctly (not PHC, PNIC, PMc, etc.).\n"
        "- For TFEX Options (e.g., S50M26P1000), ensure the strike price uses zeros ('000') and not letters ('OOO').\n"
        "Return ONLY valid JSON, no explanation."
    )

    cli_list = ["agy", "claude"] if ai_reviewer == "agy" else ["claude", "agy"]

    for cli in cli_list:
        if cli in _ai_failed_clis:
            continue

        try:
            result = subprocess.run(
                [cli, "--dangerously-skip-permissions", "-p", prompt],
                capture_output=True, text=True, timeout=30,
                cwd=str(Path(__file__).parent.parent),
            )

            if result.returncode != 0:
                print(f"  [Layer 2] {cli}: error returncode {result.returncode} — trying next ...")
                _ai_failed_clis.add(cli)
                continue

            output = result.stdout.strip()
            if not output:
                print(f"  [Layer 2] {cli}: empty output — trying next ...")
                _ai_failed_clis.add(cli)
                continue

            try:
                return json.loads(output)
            except json.JSONDecodeError:
                match = re.search(r"\{.*\}", output, re.DOTALL)
                if match:
                    return json.loads(match.group())
                print(f"  [Layer 2] {cli}: output is not JSON — trying next ...")
                _ai_failed_clis.add(cli)
                continue

        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            print(f"  [Layer 2] {cli}: system error ({type(e).__name__}) — trying next ...")
            _ai_failed_clis.add(cli)
            continue

    raise RuntimeError(f"All AI CLIs failed to review image: {image_path}")


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch(mode: str = "ocr", ai_reviewer: str = "claude") -> dict:
    """
    mode:
      ocr         — OCR + Python parser only, no Claude (default)
      ocr-review  — OCR + Python parser, then Claude verifies JSON + image
      csv         — read directly from CSV files, skip Drive/OCR entirely
    """
    # CSV-only mode: skip Drive and OCR entirely
    if mode == "csv":
        if not CSV_SUMMARY.exists():
            raise FileNotFoundError(
                "sbi_summary.csv not found. Run with --sbi-mode ocr or ocr-review first."
            )
        print("  [SBI] CSV mode — reading from local CSV files...")
        filenames = []
        with open(CSV_SUMMARY, newline="", encoding="utf-8") as f:
            filenames = [row["filename"] for row in csv.DictReader(f)]

        csv_updated = datetime.fromtimestamp(CSV_SUMMARY.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        extracted_records = []
        for name in filenames:
            data = _load_from_csv(name)
            if data:
                data["name"] = name
                data["source"] = "csv"
                data["csv_updated"] = csv_updated
                extracted_records.append(data)
                print(f"  [SBI] Loaded {name} from CSV")

        return {
            "platform": "SBI",
            "image_paths": [],
            "tmp_dir": "",
            "extracted_records": extracted_records,
        }

    # OCR / OCR-review mode: download from Drive
    folder_id = os.getenv("GOOGLE_DRIVE_SBI_FOLDER_ID", "").strip()
    if not folder_id:
        raise ValueError("GOOGLE_DRIVE_SBI_FOLDER_ID is not set in .env")

    TMP_DIR.mkdir(parents=True, exist_ok=True)

    print("  [SBI] Connecting to Google Drive...")
    service = _get_drive_service()
    cache = _load_cache()
    images = _list_images(service, folder_id)
    print(f"  [SBI] Found {len(images)} image(s) in Drive folder")

    downloaded_paths = []
    extracted_records = []
    skipped = 0

    for img in images:
        name = img["name"]
        file_id = img["id"]
        local_path = TMP_DIR / name

        image_bytes = _download_file(service, file_id)
        digest = _md5(image_bytes)

        cached = cache.get(name, {})
        cached_md5 = cached.get("md5") if isinstance(cached, dict) else cached

        if (cached_md5 == digest and local_path.exists()
                and isinstance(cached, dict) and "data" in cached):
            print(f"  [SBI] Skipping {name} (unchanged, using cached data)")
            record = {"name": name, "source": "cache", "csv_updated": None, **cached["data"]}
            downloaded_paths.append(str(local_path))
            extracted_records.append(record)
            skipped += 1
            continue

        local_path.write_bytes(image_bytes)
        print(f"  [SBI] Downloaded {name} -> {local_path}")

        # Try OCR
        try:
            print(f"  [SBI] OCR processing {name}...")
            ocr_result = _extract_ocr(str(local_path))
            print(f"  [SBI] OCR done: type={ocr_result.get('image_type')}, "
                  f"holdings={len(ocr_result.get('holdings', []))}, "
                  f"stop_orders={len(ocr_result.get('stop_orders', []))}")

            if mode == "ocr-review":
                print(f"  [SBI] AI reviewing {name}...")
                extracted = _extract_ocr_review(str(local_path), ocr_result, ai_reviewer)
                source = "ocr-review"
            else:
                extracted = ocr_result
                source = "ocr"

        except Exception as e:
            print(f"  [SBI] OCR/review failed for {name}: {e}")
            print(f"  [SBI] Trying CSV fallback for {name}...")
            csv_data = _load_from_csv(name)
            if csv_data is None:
                print(f"  [SBI] No CSV fallback found for {name}, skipping")
                continue
            extracted = csv_data
            source = "csv"
            print(f"  [SBI] Using CSV data (updated: {csv_data.get('csv_updated')})")

        record = {"name": name, "source": source, "csv_updated": None, **extracted}
        cache[name] = {"md5": digest, "data": extracted}
        downloaded_paths.append(str(local_path))
        extracted_records.append(record)

    _save_cache(cache)

    # Auto-export CSV backup after successful OCR run
    ocr_records = [r for r in extracted_records if r.get("source") in {"ocr", "ocr-review", "cache"}]
    if ocr_records:
        _export_to_csv(ocr_records)

    print(f"  [SBI] {len(downloaded_paths)} image(s) processed ({skipped} from cache)")

    return {
        "platform": "SBI",
        "image_paths": downloaded_paths,
        "tmp_dir": str(TMP_DIR),
        "extracted_records": extracted_records,
    }
