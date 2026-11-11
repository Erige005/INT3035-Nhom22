"""Bước 1b — Bổ sung từ điển thực thể (chạy sau build_gazetteer.py).

1. Ca sĩ / rapper / idol quốc tịch Hàn Quốc trên Wikidata nhưng thiếu thuộc tính thể loại K-pop
   hoặc thành viên nhóm (ví dụ nhiều idol chỉ có nghề nghiệp 'singer').
2. Nghệ sĩ khai báo thủ công trong config/manual_entities.json (mục "Artist" và "ArtistGroups").
"""
import json

from build_gazetteer import DESCRIPTIVE, QUERIES, fetch_labels, qid, sparql
from common import CONFIG, GAZ_DIR, read_jsonl, write_jsonl


def main():
    ents = read_jsonl(GAZ_DIR / "entities.jsonl")
    have = {e["id"] for e in ents}
    rows = sparql("""
        SELECT DISTINCT ?x ?sl WHERE {
          VALUES ?occ { wd:Q177220 wd:Q2252262 wd:Q639669 wd:Q1376469 wd:Q753110 }
          ?x wdt:P31 wd:Q5 ; wdt:P27 wd:Q884 ; wdt:P106 ?occ ; wikibase:sitelinks ?sl .
          FILTER(?sl >= 10)
        }""")
    new = {}
    # Lấy lại thực thể của các truy vấn chính bị rơi do lô nhãn lỗi ở lần chạy đầu
    for key, (etype, q) in QUERIES.items():
        for r in sparql(q):
            x = qid(r["x"]["value"])
            if x not in have and x not in new:
                new[x] = {"id": x, "type": etype, "popularity": int(r["sl"]["value"]),
                          "source": "wikidata:" + key, "groups": []}
    print("Thực thể truy vấn chính bị thiếu:", len(new))
    for r in rows:
        x = qid(r["x"]["value"])
        if x not in have:
            new[x] = {"id": x, "type": "Artist", "popularity": int(r["sl"]["value"]),
                      "source": "wikidata:korean_singers", "groups": []}
    print("Ca sĩ Hàn bổ sung:", len(new))
    labels = fetch_labels(new.keys())
    for q, e in new.items():
        lab = labels.get(q, {})
        name = lab.get("en") or lab.get("vi")
        if not name:
            continue
        aliases = {name} | {a for a in (lab.get("vi"), lab.get("ko")) if a}
        aliases |= {a for a in lab.get("alts", []) if 2 <= len(a) <= 40 and not DESCRIPTIVE.search(a)}
        e.update(name=name, aliases=sorted(aliases))
        ents.append(e)

    for e in ents:
        e["aliases"] = [a for a in e["aliases"] if a == e["name"] or not DESCRIPTIVE.search(a)]
    # thành viên nhóm của các nhóm vừa lấy lại
    gids = [q for q, e in new.items() if e["type"] == "Group"]
    by_id = {e["id"]: e for e in ents}
    for i in range(0, len(gids), 100):
        batch = " ".join("wd:" + g for g in gids[i:i + 100])
        for r in sparql(f"""SELECT DISTINCT ?m ?g WHERE {{ VALUES ?g {{ {batch} }}
                            {{ ?m wdt:P463 ?g }} UNION {{ ?g wdt:P527 ?m }} ?m wdt:P31 wd:Q5 . }}"""):
            m, g = qid(r["m"]["value"]), qid(r["g"]["value"])
            if m in by_id and g not in by_id[m]["groups"]:
                by_id[m]["groups"].append(g)
    manual = json.load(open(CONFIG / "manual_entities.json", encoding="utf-8"))
    by_name = {e["name"].lower(): e for e in ents if e["type"] in ("Artist", "Group")}
    groups = {e["name"].lower(): e["id"] for e in ents if e["type"] == "Group"}
    by_name.update({e["name"].lower(): e for e in ents if e["type"] in ("Brand", "Company", "Award", "Event")})
    for etype in ("Group", "Artist", "Brand", "Company", "Award", "Event"):
      for name, aliases in manual.get(etype, {}).items():
        e = by_name.get(name.lower())
        if e is None:
            e = {"id": f"M_{etype}_{len(ents)}", "name": name, "type": etype, "aliases": [],
                 "popularity": 60, "source": "manual", "groups": []}
            ents.append(e)
            by_name[name.lower()] = e
            if etype == "Group":
                groups[name.lower()] = e["id"]
        e["aliases"] = sorted(set(e["aliases"]) | set(aliases) | {name})
    for name, gname in manual.get("ArtistGroups", {}).items():
        e, g = by_name.get(name.lower()), groups.get(gname.lower())
        if e and g and g not in e["groups"]:
            e["groups"].append(g)
    write_jsonl(GAZ_DIR / "entities.jsonl", ents)
    print("Tổng thực thể sau bổ sung:", len(ents))


if __name__ == "__main__":
    main()
