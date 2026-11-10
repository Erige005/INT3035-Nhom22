"""Tìm số trang của từng tiêu đề trong PDF (pdftotext) để dựng mục lục tĩnh."""
import json
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent
pdf = ROOT / "BaoCao_DeTai24_Nhom22.pdf"
heads = json.load(open(ROOT / "headings.json", encoding="utf-8"))
n = int(next(l for l in subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout.splitlines()
             if l.startswith("Pages")).split()[-1])
norm = lambda t: " ".join(unicodedata.normalize("NFC", t).split())  # noqa: E731
pages = [norm(subprocess.run(["pdftotext", "-f", str(i), "-l", str(i), "-layout", str(pdf), "-"],
                             capture_output=True, text=True).stdout) for i in range(1, n + 1)]
out, start = [], 3  # bỏ qua bìa và trang mục lục
for lvl, text in heads:
    if text == "MỤC LỤC":
        continue
    page = next((i + 1 for i in range(start - 1, n) if norm(text) in pages[i]), None)
    if page is None:
        sys.exit(f"Không tìm thấy tiêu đề: {text}")
    start = page
    out.append([lvl, text, page])
json.dump(out, open(ROOT / "toc_pages.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"{len(out)} tiêu đề, {n} trang")
