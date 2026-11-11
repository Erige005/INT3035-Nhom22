"""Chạy thử pipeline NLP trên một câu, một đoạn văn hoặc một bài báo (không ghi vào dữ liệu chính).

  python demo.py "Jennie (BLACKPINK) trở thành đại sứ toàn cầu của Chanel."
  python demo.py --url https://kenh14.vn/....chn
  python demo.py            # nhập câu trực tiếp, Enter dòng trống để thoát
"""
import argparse

import requests

from common import USER_AGENT
from extract import (Gazetteer, extract_relations, find_works, mark_appositives, normalize, resolve,
                     split_sentences, structural_member)
from fetch_articles import parse


def analyse(gz, text, title=""):
    sents = []
    for u in ([title] if title else []) + [text]:
        sents.extend(split_sentences(normalize(u)))
    hits_all = [(s, gz.find(s)) for s in sents]
    ctx = set()
    for _, hits in hits_all:
        for h in hits:
            if len(h[3]) == 1:
                ctx.add(h[3][0])
                ctx |= gz.groups_of.get(h[3][0], set())
    n_rel = 0
    for s, hits in hits_all:
        mentions = []
        for st, en, surf, ids in hits:
            eid = resolve(gz, list(ids), ctx)
            mentions.append({"s": st, "e": en, "id": eid, "type": gz.ents[eid]["type"], "text": surf})
        for st, en, t, wtype in find_works(s):
            if all(en <= m["s"] or st >= m["e"] for m in mentions):
                mentions.append({"s": st, "e": en, "id": f"{wtype}:{t}", "type": wtype, "text": t})
        mentions.sort(key=lambda m: m["s"])
        mark_appositives(s, mentions)
        rels = structural_member(s, mentions) + extract_relations(s, mentions, gz)
        if not mentions:
            continue
        print(f"\n• {s}")
        print("  Thực thể: " + ", ".join(f"{m['text']} [{m['type']}]" for m in mentions))
        for name, a, b, trig in rels:
            n_rel += 1
            print(f"  → {a['text']} --{name}--> {b['text']}   (từ kích hoạt: \"{trig}\")")
    print(f"\nTổng: {len(sents)} câu, {n_rel} quan hệ.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="?")
    ap.add_argument("--url")
    args = ap.parse_args()
    print("Đang nạp từ điển thực thể...")
    gz = Gazetteer()
    if args.url:
        html = requests.get(args.url, headers={"User-Agent": USER_AGENT}, timeout=30).text
        art = parse(html, args.url)
        if not art:
            print("Không bóc tách được nội dung bài báo.")
            return
        print("Tiêu đề:", art["title"])
        analyse(gz, " ".join([art["sapo"]] + art["paragraphs"]), art["title"])
    elif args.text:
        analyse(gz, args.text)
    else:
        while True:
            t = input("\nNhập câu (Enter để thoát): ").strip()
            if not t:
                break
            analyse(gz, t)


if __name__ == "__main__":
    main()
