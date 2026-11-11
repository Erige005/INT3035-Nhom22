"""Bước 6 — Gộp các quan hệ trích xuất thành đồ thị (nút + cạnh có trọng số và dẫn chứng).

- Một cạnh = bộ ba duy nhất (nguồn, loại quan hệ, đích). Quan hệ đối xứng (COLLABORATED_WITH)
  được chuẩn hóa thứ tự hai đầu.
- Trọng số `support` = số bài báo khác nhau chứa dẫn chứng của cạnh.
- Dẫn chứng (câu, URL, ngày) là metadata của cạnh, KHÔNG được tính là nút/cạnh.
- Câu chứa dấu hiệu tin đồn/phủ nhận bị loại với các quan hệ nhạy cảm (hợp đồng, đại sứ).

Đầu ra: data/graph/nodes.csv, data/graph/edges.csv, data/graph/edges_evidence.jsonl
"""
import csv
import json
from collections import defaultdict

from common import GAZ_DIR, OUT_DIR, PROC_DIR, read_jsonl, write_jsonl

SYMMETRIC = {"COLLABORATED_WITH"}
# Loại quan hệ bị loại khỏi đồ thị sau đánh giá chất lượng (mẫu 35 cạnh: LEGAL_ACTION đúng 18/35 = 51%).
# Luật trích xuất vẫn được giữ trong extract.py để cải tiến ở bài cuối kỳ.
EXCLUDED_RELS = {"LEGAL_ACTION"}
RUMOR_SENSITIVE = {"SIGNED_WITH", "RENEWED_CONTRACT", "LEFT_COMPANY", "LEFT_GROUP", "BRAND_AMBASSADOR",
                   "DEBUTED_UNDER"}


def main():
    gaz = {e["id"]: e for e in read_jsonl(GAZ_DIR / "entities.jsonl")}
    rels = read_jsonl(PROC_DIR / "relations.jsonl")
    edges = {}
    nodes = {}
    dropped = 0
    for r in rels:
        if r["rel"] in EXCLUDED_RELS:
            continue
        if r["negated_or_rumor"] and r["rel"] in RUMOR_SENSITIVE:
            dropped += 1
            continue
        s, d = r["src"], r["dst"]
        st, dt_ = r["src_type"], r["dst_type"]
        sn, dn = r["src_name"], r["dst_name"]
        if r["rel"] in SYMMETRIC and s > d:
            s, d, st, dt_, sn, dn = d, s, dt_, st, dn, sn
        key = (s, r["rel"], d)
        e = edges.setdefault(key, {"src": s, "rel": r["rel"], "dst": d, "urls": set(), "langs": set(),
                                   "sources": set(), "dates": [], "evidence": [],
                                   "direct": 0})
        if r["url"] not in e["urls"] and len(e["evidence"]) < 3:
            e["evidence"].append({"sentence": r["sentence"], "url": r["url"], "date": r["date"],
                                  "trigger": r["trigger"]})
        e["urls"].add(r["url"])
        e["direct"] += not r.get("coref", False)
        e["langs"].add(r["lang"])
        e["sources"].add(r["source"])
        if r["date"]:
            e["dates"].append(r["date"])
        for nid, ntype, name in ((s, st, sn), (d, dt_, dn)):
            if nid not in nodes:
                g = gaz.get(nid, {})
                if ntype in ("Song", "Album") and nid not in gaz:
                    name = nid.split(":", 1)[1].split("|")[0]
                    name = next((x for x in (r["dst_name"], r["src_name"]) if x.lower() == name), name)
                nodes[nid] = {"id": nid, "name": g.get("name", name), "type": ntype,
                              "wikidata": nid if nid.startswith("Q") else "",
                              "popularity": g.get("popularity", 0), "mentions": 0}
            nodes[nid]["mentions"] += 1

    with open(OUT_DIR / "nodes.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "name", "type", "wikidata", "popularity", "mentions"])
        w.writeheader()
        w.writerows(nodes.values())
    ev_rows = []
    with open(OUT_DIR / "edges.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["src", "rel", "dst", "support", "first_date", "last_date", "langs", "sources", "coref_only"])
        for e in edges.values():
            dates = sorted(e["dates"])
            w.writerow([e["src"], e["rel"], e["dst"], len(e["urls"]), dates[0] if dates else "",
                        dates[-1] if dates else "", "|".join(sorted(e["langs"])), "|".join(sorted(e["sources"])),
                        int(e["direct"] == 0)])
            ev_rows.append({"src": e["src"], "rel": e["rel"], "dst": e["dst"], "support": len(e["urls"]),
                            "evidence": e["evidence"]})
    write_jsonl(OUT_DIR / "edges_evidence.jsonl", ev_rows)
    from collections import Counter
    summary = {
        "nodes": len(nodes), "edges": len(edges), "dropped_rumor_mentions": dropped,
        "node_types": Counter(n["type"] for n in nodes.values()),
        "edge_types": Counter(e["rel"] for e in edges.values()),
    }
    json.dump(summary, open(OUT_DIR / "summary.json", "w"), ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
