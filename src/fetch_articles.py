"""Bước 3 — Tải và bóc tách nội dung bài báo.

Mỗi trang được tải với độ trễ lịch sự (mặc định 0,5 giây/yêu cầu/trang), chạy song song giữa
các trang khác nhau. Phần thân bài lấy theo khối HTML chứa nhiều đoạn <p> trực tiếp nhất.

Đầu ra: data/raw/articles.jsonl
  {"url", "source", "lang", "title", "sapo", "published", "paragraphs": [...]}
"""
import argparse
import json
import random
import re
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import requests
from bs4 import BeautifulSoup

from common import RAW_DIR, USER_AGENT, read_jsonl

LOCK = threading.Lock()
OUT = RAW_DIR / "articles.jsonl"

# Dòng rác thường gặp cuối bài
JUNK = re.compile(r"^(Nguồn|Theo|Ảnh|Video|Photo|Source|Xem thêm|Đọc thêm|>>|\(Nguồn|Ảnh:|Photo credit)", re.I)


def parse(html, url):
    s = BeautifulSoup(html, "html.parser")
    for t in s(["script", "style", "noscript", "figure", "figcaption", "table", "iframe"]):
        t.decompose()
    title = s.h1.get_text(" ", strip=True) if s.h1 else ""
    meta = (s.find("meta", property="article:published_time")
            or s.find("meta", attrs={"itemprop": "datePublished"})
            or s.find("meta", attrs={"name": "pubdate"}))
    published = meta.get("content", "")[:19] if meta else ""
    desc = s.find("meta", attrs={"name": "description"}) or s.find("meta", property="og:description")
    sapo = desc.get("content", "").strip() if desc else ""

    cands = s.find_all(["div", "article", "section"])
    if not cands:
        return None
    best = max(cands, key=lambda d: len(d.find_all("p", recursive=False)))
    paras = []
    for p in best.find_all("p", recursive=False):
        txt = re.sub(r"\s+", " ", p.get_text(" ", strip=True)).strip()
        if len(txt) < 25 or JUNK.match(txt):
            continue
        paras.append(txt)
    if not paras:
        return None
    return {"title": title, "sapo": sapo, "published": published, "paragraphs": paras}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delay", type=float, default=0.5)
    ap.add_argument("--limit-per-source", type=int, default=0)
    ap.add_argument("--urls", default=str(RAW_DIR / "urls.jsonl"))
    args = ap.parse_args()

    urls = read_jsonl(args.urls)
    done = {r["url"] for r in read_jsonl(OUT)}
    by_src = defaultdict(list)
    for r in urls:
        if r["url"] not in done:
            by_src[r["source"]].append(r)
    for src in by_src:
        random.Random(0).shuffle(by_src[src])
        if args.limit_per_source:
            by_src[src] = by_src[src][: args.limit_per_source]
    print({k: len(v) for k, v in by_src.items()})

    def worker(src):
        sess = requests.Session()
        sess.headers["User-Agent"] = USER_AGENT
        ok = fail = 0
        for r in by_src[src]:
            try:
                resp = sess.get(r["url"], timeout=30)
                art = parse(resp.text, r["url"]) if resp.status_code == 200 else None
            except Exception:  # noqa: BLE001
                art = None
            if art:
                ok += 1
                art.update(url=r["url"], source=r["source"], lang=r["lang"])
                if not art["published"] and r.get("lastmod"):
                    art["published"] = r["lastmod"]
                with LOCK, open(OUT, "a", encoding="utf-8") as f:
                    f.write(json.dumps(art, ensure_ascii=False) + "\n")
            else:
                fail += 1
            if (ok + fail) % 200 == 0:
                print(f"  {src}: {ok} ok, {fail} lỗi", flush=True)
            time.sleep(args.delay)
        print(f"XONG {src}: {ok} ok, {fail} lỗi", flush=True)

    # Mỗi trang 2 luồng (độ trễ riêng từng luồng) để vừa nhanh vừa lịch sự
    jobs = []
    for src in list(by_src):
        half = by_src[src]
        by_src[src + "#2"] = half[1::2]
        by_src[src] = half[0::2]
        jobs += [src, src + "#2"]
    with ThreadPoolExecutor(max_workers=len(jobs)) as ex:
        list(ex.map(lambda j: worker(j), jobs))


if __name__ == "__main__":
    main()
