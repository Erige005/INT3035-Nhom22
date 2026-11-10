"""Hằng số, đường dẫn và hàm tiện ích dùng chung cho toàn bộ pipeline."""
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CONFIG = ROOT / "config"
GAZ_DIR = DATA / "gazetteer"
RAW_DIR = DATA / "raw"
PROC_DIR = DATA / "processed"
OUT_DIR = DATA / "graph"
for d in (GAZ_DIR, RAW_DIR, PROC_DIR, OUT_DIR):
    d.mkdir(parents=True, exist_ok=True)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36 UET-INT3035-student-project"
)

# Loại nút nghiệp vụ trong đồ thị
NODE_TYPES = ["Artist", "Group", "Company", "Brand", "Award", "Event", "Song", "Album"]


def read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:  # dòng ghi dở khi file đang được ghi song song
                    pass
    return rows


def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def strip_accents(s: str) -> str:
    """Bỏ dấu tiếng Việt: 'Đại sứ' -> 'Dai su'."""
    s = s.replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def slugify(s: str) -> str:
    """Chuyển tên thành slug giống URL báo Việt: 'Rosé (BLACKPINK)' -> 'rose-blackpink'."""
    s = strip_accents(s).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)
