"""Bước 1 — Xây dựng từ điển thực thể (gazetteer).

Wikidata chỉ được dùng làm TỪ ĐIỂN để nhận dạng tên thực thể (tên chuẩn, bí danh, loại),
không dùng để sinh cạnh. Mọi cạnh trong đồ thị đều trích xuất từ văn bản báo chí.

Đầu ra: data/gazetteer/entities.jsonl, mỗi dòng:
  {"id", "name", "type", "aliases", "popularity", "source", "groups"}
"""
import json
import re
import time

import requests

from common import CONFIG, GAZ_DIR, USER_AGENT, write_jsonl

SPARQL = "https://query.wikidata.org/sparql"
LABEL_SVC = 'SERVICE wikibase:label { bd:serviceParam wikibase:language "en,ko,vi". }'


def sparql(query, retries=5):
    for i in range(retries):
        try:
            r = requests.post(SPARQL, data={"query": query, "format": "json"},
                              headers={"User-Agent": USER_AGENT}, timeout=180)
            r.raise_for_status()
            return r.json()["results"]["bindings"]
        except Exception as e:  # noqa: BLE001
            print("  SPARQL lỗi, thử lại:", e)
            time.sleep(5 * (i + 1))
    return []


DESCRIPTIVE = re.compile(r"\b(singer|rapper|group|band|actor|actress|musician|producer|song|album|"
                         r"record label|company|South Korean|American|British)\b|\(", re.I)


def qid(uri):
    return uri.rsplit("/", 1)[-1]


# Mỗi truy vấn trả về ?x (thực thể), ?sl (số sitelinks ~ độ phổ biến)
QUERIES = {
    # Nhóm nhạc K-pop
    "kpop_groups": ("Group", """
        SELECT DISTINCT ?x ?sl WHERE {
          ?x wdt:P136 wd:Q213665 ; wdt:P31/wdt:P279* wd:Q215380 ; wikibase:sitelinks ?sl .
          FILTER(?sl >= 4)
        }"""),
    # Nghệ sĩ solo K-pop (con người, thể loại K-pop)
    "kpop_soloists": ("Artist", """
        SELECT DISTINCT ?x ?sl WHERE {
          ?x wdt:P31 wd:Q5 ; wdt:P136 wd:Q213665 ; wikibase:sitelinks ?sl .
          FILTER(?sl >= 6)
        }"""),
    # Ca sĩ / rapper Mỹ, Anh có độ phổ biến cao
    "usuk_soloists": ("Artist", """
        SELECT DISTINCT ?x ?sl WHERE {
          VALUES ?c { wd:Q30 wd:Q145 wd:Q16 wd:Q408 wd:Q27 }
          VALUES ?occ { wd:Q177220 wd:Q2252262 wd:Q639669 wd:Q488205 wd:Q753110 }
          ?x wdt:P31 wd:Q5 ; wdt:P27 ?c ; wdt:P106 ?occ ; wikibase:sitelinks ?sl .
          FILTER(?sl >= 45)
          OPTIONAL { ?x wdt:P570 ?dod }
          FILTER(!BOUND(?dod) || YEAR(?dod) >= 2000)
        }"""),
    # Ban nhạc / nhóm nhạc Mỹ, Anh
    "usuk_groups": ("Group", """
        SELECT DISTINCT ?x ?sl WHERE {
          VALUES ?c { wd:Q30 wd:Q145 wd:Q16 wd:Q408 wd:Q27 }
          ?x wdt:P31/wdt:P279* wd:Q215380 ; wdt:P495 ?c ; wikibase:sitelinks ?sl .
          FILTER(?sl >= 45)
        }"""),
}


def fetch_labels(qids):
    """Lấy nhãn en/ko/vi + bí danh tiếng Anh cho danh sách QID (theo lô)."""
    out = {}
    qids = list(qids)
    step = 60
    for i in range(0, len(qids), step):
        batch = " ".join("wd:" + q for q in qids[i:i + step])
        rows = sparql(f"""
            SELECT ?x ?en ?mul ?ko ?vi (GROUP_CONCAT(DISTINCT ?alt; separator="|") AS ?alts) WHERE {{
              VALUES ?x {{ {batch} }}
              OPTIONAL {{ ?x rdfs:label ?en FILTER(LANG(?en)="en") }}
              OPTIONAL {{ ?x rdfs:label ?mul FILTER(LANG(?mul)="mul") }}
              OPTIONAL {{ ?x rdfs:label ?ko FILTER(LANG(?ko)="ko") }}
              OPTIONAL {{ ?x rdfs:label ?vi FILTER(LANG(?vi)="vi") }}
              OPTIONAL {{ ?x skos:altLabel ?alt FILTER(LANG(?alt)="en" || LANG(?alt)="mul") }}
            }} GROUP BY ?x ?en ?mul ?ko ?vi""")
        for r in rows:
            q = qid(r["x"]["value"])
            out[q] = {
                # Wikidata dùng nhãn đa ngữ "mul" thay cho "en" ở nhiều thực thể (từ 2024)
                "en": r.get("en", {}).get("value") or r.get("mul", {}).get("value"),
                "ko": r.get("ko", {}).get("value"),
                "vi": r.get("vi", {}).get("value"),
                "alts": [a for a in r.get("alts", {}).get("value", "").split("|") if a],
            }
        if not rows:
            print(f"  CẢNH BÁO: lô nhãn {i} thất bại")
        if (i // step) % 25 == 0:
            print(f"  nhãn {min(i + step, len(qids))}/{len(qids)}", flush=True)
    return out


def main():
    ents = {}  # qid -> dict

    for key, (etype, q) in QUERIES.items():
        rows = sparql(q)
        print(f"{key}: {len(rows)}")
        for r in rows:
            x = qid(r["x"]["value"])
            sl = int(r["sl"]["value"])
            if x not in ents:
                ents[x] = {"id": x, "type": etype, "popularity": sl, "source": "wikidata:" + key,
                           "groups": []}

    groups = [q for q, e in ents.items() if e["type"] == "Group"]
    # Thành viên của các nhóm (P463 member of hoặc P527 has part)
    for i in range(0, len(groups), 200):
        batch = " ".join("wd:" + g for g in groups[i:i + 200])
        rows = sparql(f"""
            SELECT DISTINCT ?m ?g ?sl WHERE {{
              VALUES ?g {{ {batch} }}
              {{ ?m wdt:P463 ?g }} UNION {{ ?g wdt:P527 ?m }}
              ?m wdt:P31 wd:Q5 ; wikibase:sitelinks ?sl .
            }}""")
        for r in rows:
            m, g, sl = qid(r["m"]["value"]), qid(r["g"]["value"]), int(r["sl"]["value"])
            e = ents.setdefault(m, {"id": m, "type": "Artist", "popularity": sl,
                                    "source": "wikidata:group_members", "groups": []})
            if e["type"] == "Artist" and g not in e["groups"]:
                e["groups"].append(g)
    print("sau khi thêm thành viên:", len(ents))

    # Hãng đĩa / công ty quản lý (P264 record label) của các nghệ sĩ đã có
    artists = [q for q, e in ents.items() if e["type"] in ("Artist", "Group")]
    for i in range(0, len(artists), 300):
        batch = " ".join("wd:" + a for a in artists[i:i + 300])
        rows = sparql(f"""
            SELECT DISTINCT ?l ?sl WHERE {{
              VALUES ?a {{ {batch} }}
              ?a wdt:P264 ?l . ?l wikibase:sitelinks ?sl . FILTER(?sl >= 3)
            }}""")
        for r in rows:
            l = qid(r["l"]["value"])
            if l not in ents:
                ents[l] = {"id": l, "type": "Company", "popularity": int(r["sl"]["value"]),
                           "source": "wikidata:record_label", "groups": []}
    print("sau khi thêm hãng đĩa:", len(ents))

    # Bài hát / album / đĩa đơn của các nghệ sĩ (P175 performer)
    for i in range(0, len(artists), 300):
        batch = " ".join("wd:" + a for a in artists[i:i + 300])
        rows = sparql(f"""
            SELECT DISTINCT ?w ?t ?sl ?a WHERE {{
              VALUES ?a {{ {batch} }}
              VALUES ?t {{ wd:Q7366 wd:Q134556 wd:Q482994 wd:Q169930 wd:Q208569 }}
              ?w wdt:P175 ?a ; wdt:P31 ?t ; wikibase:sitelinks ?sl . FILTER(?sl >= 3)
            }}""")
        for r in rows:
            w = qid(r["w"]["value"])
            t = qid(r["t"]["value"])
            etype = "Album" if t in ("Q482994", "Q169930", "Q208569") else "Song"
            e = ents.setdefault(w, {"id": w, "type": etype, "popularity": int(r["sl"]["value"]),
                                    "source": "wikidata:works", "groups": []})
            a = qid(r["a"]["value"])
            if a not in e["groups"]:
                e["groups"].append(a)  # với tác phẩm, 'groups' = nghệ sĩ thể hiện
        print(f"  tác phẩm {min(i + 300, len(artists))}/{len(artists)}")
    print("sau khi thêm tác phẩm:", len(ents))

    labels = fetch_labels(ents.keys())
    out = []
    for q, e in ents.items():
        lab = labels.get(q, {})
        name = lab.get("en") or lab.get("vi")
        if not name:
            continue
        aliases = {name}
        if lab.get("vi"):
            aliases.add(lab["vi"])
        if lab.get("ko"):
            aliases.add(lab["ko"])
        # Bí danh tiếng Anh: chỉ giữ dạng ngắn gọn, tránh câu mô tả dài
        for a in lab.get("alts", []):
            if 2 <= len(a) <= 40 and not DESCRIPTIVE.search(a):
                aliases.add(a)
        e.update(name=name, aliases=sorted(aliases))
        out.append(e)

    # Thực thể bổ sung thủ công (nhãn hàng, giải thưởng, sự kiện, công ty)
    manual = json.load(open(CONFIG / "manual_entities.json", encoding="utf-8"))
    by_name = {e["name"].lower(): e for e in out}
    for etype, items in manual.items():
        if etype.startswith("_") or etype in ("Artist", "Group", "ArtistGroups"):
            continue  # được xử lý trong gazetteer_supplement.py
        for name, aliases in items.items():
            ex = by_name.get(name.lower())
            if ex and ex["type"] in (etype, "Company"):
                ex["type"] = etype
                ex["aliases"] = sorted(set(ex["aliases"]) | set(aliases) | {name})
                ex["source"] += "+manual"
                continue
            e = {"id": "M_" + etype + "_" + str(len(out)), "name": name, "type": etype,
                 "aliases": sorted(set(aliases) | {name}), "popularity": 50, "source": "manual",
                 "groups": []}
            out.append(e)
            by_name[name.lower()] = e

    write_jsonl(GAZ_DIR / "entities.jsonl", out)
    from collections import Counter
    print("Tổng thực thể:", len(out), Counter(e["type"] for e in out))


if __name__ == "__main__":
    main()
