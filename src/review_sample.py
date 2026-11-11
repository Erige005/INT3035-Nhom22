"""Bước 9 — Lấy mẫu cạnh để kiểm tra độ chính xác sơ bộ.

  python review_sample.py export --per-rel 10   -> data/graph/review_sample.csv (cột label để trống)
  python review_sample.py score                 -> data/graph/quality_check.json

Quy ước gán nhãn cột `label`: 1 = câu dẫn chứng thể hiện đúng quan hệ và đúng chiều; 0 = sai.
"""
import csv
import json
import random
import sys
from collections import defaultdict

from common import OUT_DIR, read_jsonl

SAMPLE = OUT_DIR / "review_sample.csv"


def export(per_rel):
    names = {r["id"]: r["name"] for r in csv.DictReader(open(OUT_DIR / "nodes.csv", encoding="utf-8"))}
    by_rel = defaultdict(list)
    for e in read_jsonl(OUT_DIR / "edges_evidence.jsonl"):
        by_rel[e["rel"]].append(e)
    rng = random.Random(2026)
    rows = []
    for rel, es in sorted(by_rel.items()):
        for e in rng.sample(es, min(per_rel, len(es))):
            ev = e["evidence"][0]
            rows.append({"rel": rel, "src": names.get(e["src"], e["src"]), "dst": names.get(e["dst"], e["dst"]),
                         "support": e["support"], "sentence": ev["sentence"], "url": ev["url"], "label": ""})
    with open(SAMPLE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print("Đã xuất", len(rows), "mẫu ->", SAMPLE)


def score():
    rows = [r for r in csv.DictReader(open(SAMPLE, encoding="utf-8")) if r["label"].strip() in ("0", "1")]
    by = defaultdict(lambda: {"n": 0, "ok": 0})
    for r in rows:
        by[r["rel"]]["n"] += 1
        by[r["rel"]]["ok"] += int(r["label"])
    counts = defaultdict(int)
    for e in csv.DictReader(open(OUT_DIR / "edges.csv", encoding="utf-8")):
        counts[e["rel"]] += 1
    # Chỉ tính các loại quan hệ còn trong đồ thị; loại đã bị loại bỏ được báo cáo riêng
    kept = {k for k in by if counts[k]}
    n = sum(by[k]["n"] for k in kept)
    ok = sum(by[k]["ok"] for k in kept)
    # Ước lượng có trọng số: độ chính xác từng loại × tỷ trọng số cạnh của loại đó trong toàn đồ thị
    total = sum(counts[k] for k in kept)
    weighted = sum(by[k]["ok"] / by[k]["n"] * counts[k] for k in kept) / total if total else 0
    res = {"sample": n, "correct": ok, "precision": ok / n if n else 0, "weighted_precision": weighted,
           "excluded_from_graph": sorted(set(by) - kept), "by_rel": dict(sorted(by.items()))}
    json.dump(res, open(OUT_DIR / "quality_check.json", "w"), ensure_ascii=False, indent=2)
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if sys.argv[1] == "export":
        export(int(sys.argv[sys.argv.index("--per-rel") + 1]) if "--per-rel" in sys.argv else 10)
    else:
        score()
