"""Bước 2 — Thu thập URL bài báo từ sitemap của các trang tin.

Nguồn (đều cho phép User-agent * trong robots.txt):
  - Tiếng Việt: Kênh14, Thanh Niên, Tuổi Trẻ, Znews
  - Tiếng Anh: Soompi
Các trang tiếng Việt đăng mọi chuyên mục nên lọc theo slug URL: giữ bài có slug chứa tên
nghệ sĩ/nhóm/công ty trong từ điển hoặc từ khóa K-pop/US-UK. Soompi chỉ đăng tin giải trí Hàn
nên lọc nhẹ hơn (bỏ bài thuần phim truyền hình).

Đầu ra: data/raw/urls.jsonl  {"url", "source", "lang", "lastmod"}
"""
import argparse
import json
import datetime as dt
import re
import time
from concurrent.futures import ThreadPoolExecutor
from itertools import zip_longest

import requests

from common import GAZ_DIR, RAW_DIR, USER_AGENT, read_jsonl, slugify, write_jsonl

S = requests.Session()
S.headers["User-Agent"] = USER_AGENT

# Từ khóa slug chung (không dấu) gợi ý tin âm nhạc K-pop / US-UK
GENERIC_KW = [
    "kpop", "k-pop", "idol", "nhom-nhac-nu", "nhom-nhac-nam", "girlgroup", "boygroup",
    "ca-si-au-my", "sao-au-my", "nhac-au-my", "us-uk", "sao-han", "nhac-han", "ca-si-han",
    "dai-su-toan-cau", "dai-su-thuong-hieu", "hop-dong-doc-quyen", "tai-ky", "comeback",
    "debut", "grammy", "billboard", "mama", "hybe", "jyp", "yg-entertainment", "sm-entertainment",
]
# Từ khóa slug Soompi chỉ về phim/diễn xuất thuần túy -> loại để tiết kiệm thời gian
SOOMPI_SKIP = re.compile(r"(drama|k-drama|ratings|webtoon|actor|actress|-film-|movie|-cast-|variety-show-ratings)")


def get(url, timeout=40):
    for i in range(3):
        try:
            r = S.get(url, timeout=timeout)
            if r.status_code == 200:
                return r.text
            if r.status_code == 404:
                return ""
        except requests.RequestException:
            pass
        time.sleep(2 * (i + 1))
    return ""


def locs(xml):
    out = []
    for m in re.finditer(r"<url>(.*?)</url>", xml, re.S):
        block = m.group(1)
        loc = re.search(r"<loc>\s*([^<\s]+)", block)
        lm = re.search(r"<lastmod>\s*([^<\s]+)", block)
        if loc:
            out.append((loc.group(1).strip(), lm.group(1)[:10] if lm else None))
    return out


def date_ranges(start, end):
    """Sinh các khoảng ngày theo quy ước sitemap của nhóm VCCorp (1-5, 6-10, ..., 26-cuối tháng)."""
    d = dt.date(start.year, start.month, 1)
    while d <= end:
        nxt = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        last = (nxt - dt.timedelta(days=1)).day
        for a in (1, 6, 11, 16, 21, 26):
            b = last if a == 26 else a + 4
            yield d.year, d.month, a, b
        d = nxt


def sitemap_urls(source, start, end):
    if source == "kenh14":
        return [f"https://kenh14.vn/sitemaps/sitemaps-{y}-{m}-{a}-{b}.xml" for y, m, a, b in date_ranges(start, end)]
    if source == "thanhnien":
        return [f"https://thanhnien.vn/sitemaps/sitemaps-{y}-{m}-{a}-{b}.xml" for y, m, a, b in date_ranges(start, end)]
    if source == "tuoitre":
        return [f"https://tuoitre.vn/StaticSitemaps/sitemaps-{y}-{m}-{a}-{b}.xml" for y, m, a, b in date_ranges(start, end)]
    days = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
    if source == "znews":
        return [f"https://znews.vn/sitemap/sitemap-article-{d:%Y%m%d}.xml" for d in days]
    if source == "soompi":
        return [f"https://www.soompi.com/sitemap.xml?yyyy={d:%Y}&mm={d:%m}&dd={d:%d}" for d in days]
    raise ValueError(source)


VI_FREQ = GAZ_DIR / "vi_slug_token_freq.json"
EXTRA_STOP = {"chan", "theo", "nien", "sung", "miss", "secret", "game", "chai", "highlight", "festival",
              "mini", "victoria", "anne", "young", "haha", "diva", "green", "derby", "nana", "amazon",
              "london", "earth", "sunshine", "golden", "fantasy", "jones", "seal", "baby", "mimi",
              "nicole", "jackson", "chen", "chi-chi", "san-ha", "an-xin", "dong-ho", "luu-diec-phi"}


def vi_token_freq():
    """Tần suất token trong slug của toàn bộ bài (mọi chuyên mục) tháng 10/2026 — ước lượng âm tiết thông dụng."""
    if VI_FREQ.exists():
        return json.load(open(VI_FREQ))
    from collections import Counter
    cnt = Counter()
    d0, d1 = dt.date(2026, 10, 1), dt.date(2026, 10, 31)
    for src in ("kenh14", "thanhnien", "tuoitre"):
        for sm in sitemap_urls(src, d0, d1):
            for url, _ in locs(get(sm)):
                cnt.update(set(slug_of(url).strip("-").split("-")))
    json.dump(cnt, open(VI_FREQ, "w"))
    return cnt


def build_slug_matcher():
    """Ánh xạ slug tên thực thể -> có được dùng để lọc URL hay không.

    - Tên 1 token: thực thể phải đủ nổi tiếng (popularity >= 25) và token không phải âm tiết/từ
      thông dụng trong slug báo Việt (tần suất < 15/tháng), trừ thực thể rất nổi tiếng (>= 60).
    - Tên nhiều token: popularity >= 10 và không phải mọi token đều là từ thông dụng.
    """
    freq = vi_token_freq()
    ents = read_jsonl(GAZ_DIR / "entities.jsonl")
    pop = {}
    for e in ents:
        if e["type"] not in ("Artist", "Group", "Company"):
            continue
        p_ = e.get("popularity", 0) if e["source"] != "manual" else 60
        for a in e["aliases"]:
            s = slugify(a)
            if len(s) >= 4 and not s.isdigit():
                pop[s] = max(pop.get(s, 0), p_)
    keys = set()
    for k, p_ in pop.items():
        toks = k.split("-")
        common = [freq.get(t, 0) >= 15 for t in toks]
        if k in EXTRA_STOP:
            continue
        if len(toks) == 1:
            if p_ >= 60 or (p_ >= 25 and not common[0] and len(k) >= 4):
                keys.add(k)
        elif p_ >= 10 and not all(common):
            keys.add(k)
    return keys


def slug_of(url):
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    tail = re.sub(r"(-\d{8,})?\.(chn|htm|html)$", "", tail)
    tail = re.sub(r"-post\d+$", "", tail)
    return "-" + tail.lower() + "-"


def keep_vi(url, keys):
    s = slug_of(url)
    if any(k in s for k in GENERIC_KW):
        return True
    toks = s.strip("-").split("-")
    # So khớp n-gram slug (1..4 token) với tập tên thực thể
    for n in (1, 2, 3, 4):
        for i in range(len(toks) - n + 1):
            if "-".join(toks[i:i + n]) in keys:
                return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2024-11-01")
    ap.add_argument("--end", default="2026-11-10")
    ap.add_argument("--sources", default="kenh14,thanhnien,tuoitre,znews,soompi")
    args = ap.parse_args()
    start, end = dt.date.fromisoformat(args.start), dt.date.fromisoformat(args.end)
    keys = build_slug_matcher()
    print("Số slug tên thực thể:", len(keys))

    out_path = RAW_DIR / "urls.jsonl"
    seen = {r["url"] for r in read_jsonl(out_path)}
    rows = read_jsonl(out_path)

    def job(args_):
        source, sm = args_
        xml = get(sm)
        res = []
        for url, lm in locs(xml):
            if source == "soompi":
                if "/article/" not in url or SOOMPI_SKIP.search(url):
                    continue
                if not keep_vi(url, keys):
                    continue
                lang = "en"
            else:
                if not keep_vi(url, keys):
                    continue
                lang = "vi"
            res.append({"url": url, "source": source, "lang": lang, "lastmod": lm})
        time.sleep(0.3)
        return source, sm, res

    done_path = RAW_DIR / "sitemaps_done.txt"
    done_sm = set(done_path.read_text().split()) if done_path.exists() else set()
    per_src = [[(src, sm) for sm in sitemap_urls(src, start, end) if sm not in done_sm]
               for src in args.sources.split(",")]
    # Xen kẽ các nguồn để không dồn tải vào một trang
    tasks = [t for grp in zip_longest(*per_src) for t in grp if t]
    print("Số sitemap cần đọc:", len(tasks))
    with ThreadPoolExecutor(max_workers=12) as ex, open(done_path, "a") as dlog:
        for i, (src, sm, res) in enumerate(ex.map(job, tasks), 1):
            dlog.write(sm + "\n")
            for r in res:
                if r["url"] not in seen:
                    seen.add(r["url"])
                    rows.append(r)
            if i % 50 == 0:
                print(f"  {i}/{len(tasks)} sitemap, {len(rows)} URL")
                write_jsonl(out_path, rows)
    write_jsonl(out_path, rows)
    from collections import Counter
    print("Tổng URL:", len(rows), Counter(r["source"] for r in rows))


if __name__ == "__main__":
    main()
