"""
EasyOCR proof-of-concept for SBI screenshots.
รัน: python tests/test_easyocr_sbi.py
"""

import sys
from pathlib import Path

# ---- รูปที่จะทดสอบ ----
TEST_IMAGES = [
    r"C:\Users\asus\AppData\Local\Temp\sbi\stop_orders.jpg",
    r"C:\Users\asus\AppData\Local\Temp\sbi\Screenshot_2026_0521_221911.jpg",
    r"C:\Users\asus\AppData\Local\Temp\sbi\Screenshot_20260521_222044.jpg",
]


def run_ocr(image_path: str):
    import easyocr
    print(f"\n{'='*60}")
    print(f"Image: {Path(image_path).name}")
    print("="*60)

    reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    results = reader.readtext(image_path)

    print("\n[Raw OCR output]")
    print(f"{'Confidence':>10}  Text")
    print("-" * 50)
    for (bbox, text, conf) in results:
        print(f"{conf:>10.2f}  {text}")

    print("\n[Tokens only — ตัดช่องว่าง/newline]")
    tokens = [text.strip() for (_, text, _) in results if text.strip()]
    print("  |  ".join(tokens))

    return results


def main():
    print("Installing easyocr if needed...")
    try:
        import easyocr
    except ImportError:
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "easyocr"], check=True)
        import easyocr

    images = [p for p in TEST_IMAGES if Path(p).exists()]
    if not images:
        print("ไม่พบรูปใน temp folder")
        sys.exit(1)

    for img in images:
        run_ocr(img)

    print("\n\nสรุป: ดูผลด้านบนว่า OCR อ่านตัวเลขและ symbol ได้ถูกต้องไหม")


if __name__ == "__main__":
    main()
