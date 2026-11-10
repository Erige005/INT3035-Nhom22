"""Bước 4–5 — Tiền xử lý văn bản, nhận dạng thực thể (NER) và trích xuất quan hệ (RE).

Pipeline cho mỗi bài báo:
  1. Chuẩn hóa Unicode (NFC), thống nhất dấu ngoặc kép, bỏ ký tự điều khiển/emoji, gộp khoảng trắng.
  2. Tách câu bằng luật (dấu kết câu + chữ hoa/ngoặc), có bảo vệ viết tắt (feat., ft., Mr., Inc.).
  3. NER dựa trên từ điển (Aho–Corasick, khớp phân biệt hoa thường theo các biến thể viết hoa),
     khử nhập nhằng tên trùng nhờ ngữ cảnh nhóm nhạc trong cùng bài và độ phổ biến.
  4. NER dựa trên mẫu cho tên bài hát/album: chuỗi trong ngoặc kép đứng sau từ khóa
     (ca khúc, bài hát, single, album, MV, EP, song, track...).
  5. Trích xuất quan hệ bằng luật: từ kích hoạt (trigger) tiếng Việt/Anh + ràng buộc loại thực thể
     + vị trí (chủ thể bên trái, đối tượng bên phải, có luật đảo chiều cho câu bị động).

Đầu ra:
  data/processed/sentences_stats.json  — thống kê tiền xử lý
  data/processed/relations.jsonl        — mỗi dòng là một bộ ba có dẫn chứng (câu, URL, ngày)
"""
import json
import re
import unicodedata
from collections import Counter, defaultdict

import ahocorasick

from common import GAZ_DIR, PROC_DIR, RAW_DIR, nfc, read_jsonl, write_jsonl

# ---------------------------------------------------------------- 1. Tiền xử lý

QUOTE_MAP = str.maketrans({"“": '"', "”": '"', "„": '"', "«": '"', "»": '"', "‘": "'", "’": "'",
                           "＂": '"', "″": '"', " ": " ", "​": "", "﻿": ""})
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️]")
ABBR = ["feat.", "ft.", "Mr.", "Ms.", "Mrs.", "Dr.", "Inc.", "Co.", "Corp.", "Ltd.", "vs.", "No.",
        "Jr.", "Sr.", "St.", "U.S.", "U.K.", "Vol.", "TP.", "Th.S", "PGS.", "TS.", "D.O.", "APT."]


def normalize(text):
    text = nfc(text).translate(QUOTE_MAP)
    text = EMOJI.sub(" ", text)
    text = "".join(c for c in text if unicodedata.category(c)[0] != "C" or c in "\n\t")
    return re.sub(r"\s+", " ", text).strip()


SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+(?=[\"'(\[]?[A-ZÀ-ỸĐ0-9])")


def split_sentences(text):
    protected = text
    for i, a in enumerate(ABBR):
        protected = protected.replace(a, f"§{i}§")
    out = []
    for s in SENT_SPLIT.split(protected):
        for i, a in enumerate(ABBR):
            s = s.replace(f"§{i}§", a)
        s = s.strip()
        if 15 <= len(s) <= 600:
            out.append(s)
    return out


# ---------------------------------------------------------------- 2. NER từ điển

# Từ thông dụng không được dùng làm bí danh nếu đứng một mình
COMMON = set("""
a an the and or of in on at to for with by from as is it be we us you he she they me my our your
love home song star girl boy boys girls time one two red blue black white gold kiss dream angel
queen king hello magic power lucky happy sunny crush jade rain rose lisa joy key kai jin v d.o
summer winter spring fall fire ice wind sky sun moon light dark day night life world music dance
baby honey sugar candy sweet cool hot new old big small good bad best yes no oh ah hey way go
ca hát nhạc nhóm sao người đời tình yêu em anh chị mẹ cha con ngày đêm trời đất nước mây gió
hoa lá xuân hạ thu đông vàng bạc đỏ xanh trắng đen mới cũ hay đẹp vui buồn
like next up down out over under after before more most only just also even still much many
year years week month first last top hit hits chart album single track tour concert show
team crew band group label music awards award grand prize live stage fans fan army
coach guess
""".split())
# Bí danh nhóm/nghệ sĩ ngắn nhưng nổi tiếng, được phép dù ngắn
ALLOW_SHORT = {"BTS", "IU", "EXO", "NCT", "ITZY", "IVE", "TWS", "BoA", "Rain", "Joy", "Key", "Kai",
               "Jin", "Lisa", "Rosé", "V", "SM", "YG", "JYP", "CL", "Zico", "PSY", "Bibi", "BIBI", "Ado",
               "Sia", "SZA", "Lizzo", "Drake", "Adele", "Dua Lipa", "LV", "D.O.", "RM", "DK", "S.Coups",
               "Hoshi", "Woozi", "Mingyu", "Dino", "Vernon", "Joshua", "Jun", "The8", "Seungkwan", "Jeonghan",
               "Wonwoo", "Suga", "J-Hope", "Jimin", "Jungkook", "Jisoo", "Jennie", "Taeyeon", "Wendy",
               "Irene", "Seulgi", "Yeri", "Karina", "Winter", "Giselle", "Ningning", "Ruka", "Asa", "Pharita",
               "Ahyeon", "Rami", "Rora", "Chiquita", "Minji", "Hanni", "Danielle", "Haerin", "Hyein",
               "Yuna", "Ryujin", "Chaeryeong", "Yeji", "Lia", "Wonyoung", "Yujin", "Gaeul", "Leeseo",
               "Liz", "Rei", "Sakura", "Chaewon", "Kazuha", "Eunchae", "Yunjin", "Nayeon", "Jihyo",
               "Momo", "Sana", "Mina", "Dahyun", "Chaeyoung", "Tzuyu", "Jeongyeon", "G-Dragon", "Taeyang",
               "Daesung", "T.O.P", "Seungri", "Taemin", "Minho", "Onew", "Baekhyun", "Chanyeol", "Sehun",
               "Suho", "Xiumin", "Chen", "Lay", "Mark", "Haechan", "Jaehyun", "Taeyong", "Doyoung",
               "Jeno", "Jaemin", "Renjun", "Chenle", "Jisung", "Yeonjun", "Soobin", "Beomgyu", "Taehyun",
               "Hueningkai", "Heeseung", "Jay", "Jake", "Sunghoon", "Sunoo", "Jungwon", "Ni-ki", "Bang Chan",
               "Hyunjin", "Felix", "Changbin", "Seungmin", "I.N", "Lee Know", "Hwasa", "Solar",
               "Moonbyul", "Wheein", "Jessi", "Somi", "Chungha", "Sunmi", "HyunA", "Jeon Somi", "Mamamoo",
               "Aespa", "aespa", "Ive", "BabyMonster", "NewJeans", "Katseye", "KATSEYE", "Illit", "ILLIT"}


# Bí danh bị chặn tuyệt đối (so khớp chính xác): từ chức năng tiếng Việt viết hoa đầu câu,
# tên thể loại nhạc trùng tên nhóm trên Wikidata, ...
STOP_ALIASES = set("""
Theo Sau Trong Khi Với Cùng Năm Ngày Hai Ba Bà Ông Anh Chị Em Cô Như Nhưng Và Còn Tại Từ Đây Đó Nếu
Một Mới Ngoài Bên Hiện Cả Các Những Đến Vào Dù Tuy Do Vì Nên Lúc Giờ Hôm Tối Sáng Chiều Đêm Mùa Tháng
Nam Nữ Bạn Fan Ai Gì Sao Chỉ Đã Đang Sẽ Vẫn Rất Nhiều Lại Nay Xem Được Bị Cho Hay Hoa Mây Nắng Gió Mưa
January February March April May June July August September October November December
K-Pop K-POP K-pop Kpop KPOP K'Pop K'POP J-Pop C-Pop V-Pop US-UK Hallyu Idol Idols Gen Z Show Live Top
""".split())


def variants(alias):
    """Các biến thể viết hoa hợp lệ của bí danh (khớp phân biệt hoa thường)."""
    v = {alias, alias.upper()}
    # Tên Hàn: 'Jang Won-young' -> 'Jang Won Young', 'Jang Wonyoung'
    if re.search(r"[A-Za-z]-[a-z]", alias) and " " in alias:
        v.add(re.sub(r"-([a-z])", lambda m: " " + m.group(1).upper(), alias))
        v.add(alias.replace("-", ""))
    if alias.isupper() and len(alias) > 3:
        v.add(alias.title())
        v.add(alias.capitalize())
    if alias.islower() and len(alias) > 3:
        v.add(alias.capitalize())
    return v


def alias_ok(alias, etype):
    a = alias.strip()
    if a in STOP_ALIASES:
        return False
    if a in ALLOW_SHORT:
        return True
    if len(a) < 3 or a.lower() in COMMON or a.isdigit():
        return False
    if re.fullmatch(r"[\W\d_]+", a):
        return False
    if etype in ("Song", "Album"):
        return len(a) >= 2
    # Tên một từ, toàn chữ thường -> dễ nhầm
    if " " not in a and a.islower():
        return False
    # Họ Hàn/Việt đứng một mình
    if a.lower() in {"kim", "lee", "park", "choi", "jung", "jang", "kang", "cho", "yoon", "han", "shin",
                     "nguyễn", "trần", "lê", "phạm", "hoàng"}:
        return False
    return True


class Gazetteer:
    def __init__(self):
        self.ents = {e["id"]: e for e in read_jsonl(GAZ_DIR / "entities.jsonl")}
        self.auto = ahocorasick.Automaton()       # thực thể không phải tác phẩm
        self.works = ahocorasick.Automaton()      # bài hát/album (chỉ dùng khi có ngữ cảnh)
        table, wtable = defaultdict(set), defaultdict(set)
        for e in self.ents.values():
            for a in e["aliases"]:
                if not alias_ok(a, e["type"]):
                    continue
                for v in variants(nfc(a)):
                    if v in STOP_ALIASES:
                        continue
                    (wtable if e["type"] in ("Song", "Album") else table)[v].add(e["id"])
        for k, ids in table.items():
            manual_ids = {i for i in ids if "manual" in self.ents[i]["source"]
                          and k in {v for a in self.ents[i]["aliases"] for v in variants(nfc(a))}}
            if manual_ids:  # bí danh khai báo thủ công (vd 'SM' -> SM Entertainment) thắng bí danh Wikidata
                ids = manual_ids
            self.auto.add_word(k, (k, tuple(ids)))
        for k, ids in wtable.items():
            self.works.add_word(k.lower(), (k, tuple(ids)))
        self.auto.make_automaton()
        self.works.make_automaton()
        # nghệ sĩ -> các nhóm (để khử nhập nhằng)
        self.groups_of = {e["id"]: set(e.get("groups") or []) for e in self.ents.values()}

    @staticmethod
    def _boundary(text, s, e):
        before = text[s - 1] if s > 0 else " "
        after = text[e] if e < len(text) else " "
        return not (before.isalnum() or before in "_") and not (after.isalnum() or after in "_")

    def find(self, text):
        """Trả về danh sách (start, end, surface, candidate_ids) không chồng lấn, ưu tiên khớp dài."""
        hits = []
        for end, (k, ids) in self.auto.iter(text):
            s = end - len(k) + 1
            if self._boundary(text, s, end + 1) and not (s > 0 and text[s - 1] == "/"):
                hits.append((s, end + 1, k, ids))
        hits.sort(key=lambda h: (-(h[1] - h[0]), h[0]))
        taken, out = [], []
        for h in hits:
            if any(not (h[1] <= a or h[0] >= b) for a, b in taken):
                continue
            taken.append((h[0], h[1]))
            out.append(h)
        out = sorted(out)
        def distinctive(surf):  # BTS, CRAVITY, NewJeans, aespa, G-Dragon
            return surf.isupper() or re.search(r"[a-z][A-Z]|\d|-", surf) or surf[:1].islower()
        spans = [(a, b) for a, b, k, _ in out if " " in k or distinctive(k)]
        return [h for h in out if " " in h[2] or distinctive(h[2])
                or not self._inside_longer_name(text, h, spans)]

    @staticmethod
    def _inside_longer_name(text, h, spans):
        """Tên một từ nằm sát một từ viết hoa khác (không phải thực thể đã nhận dạng) -> là một phần
        của tên dài hơn ('Young' trong 'Jang Won Young') hoặc tiêu đề viết hoa từng chữ -> loại."""
        s, e = h[0], h[1]
        prev = re.search(r"(?:^|\s)(\S+)\s+$", text[max(0, s - 30):s])
        nxt = re.match(r"\s+(\S+)", text[e:e + 30])
        def free(m, base):
            if not m:
                return False
            w = m.group(1).lstrip("([\"'“‘")
            if not w or not w[0].isupper():
                return False
            a = base + m.start(1)
            return not any(x <= a < y for x, y in spans)
        return free(prev, max(0, s - 30)) or free(nxt, e)


# ---------------------------------------------------------------- 3. Tên bài hát / album theo mẫu

WORK_KW = (r"(?:ca khúc|bài hát|bản hit|siêu hit|hit|single|đĩa đơn|album|mini album|full album|EP|MV|"
           r"track|title track|ca khúc chủ đề|nhạc phẩm|song|songs|pre-release|music video|OST)")
WORK_RE = re.compile(WORK_KW + r"(?:\s+(?:mới|đầu tay|thứ \w+|solo|chủ đề|tiếp theo|tiền phát hành|"
                     r"debut|new|latest|hit|title|lead|first|second|third|\d+(?:st|nd|rd|th)|Nhật|tiếng Anh|"
                     r"của (?:họ|cô|anh|nhóm|mình)|đã|vừa|là|mang tên|có tên|titled|called))*"
                     r"\s*[:,]?\s*\"([^\"]{2,48})\"", re.I)
ALBUM_KW = re.compile(r"album|EP\b|mini|full", re.I)
WORK_POSS = re.compile(r"(?:'s|của)\s+(?:(?:new|latest|upcoming|debut|comeback|solo|hit|smash)\s+)*\"([^\"]{2,48})\"")
QUOTED = re.compile(r"\"([^\"]{2,48})\"")
# C) Đại từ / danh từ chỉ người đầu câu -> đồng tham chiếu tới nhân vật chính của bài
PRONOUN = re.compile(r"^(?:Cô(?: nàng| ấy)?|Anh(?: chàng| ấy)?|Nàng|Chàng|Nữ (?:ca sĩ|idol|rapper|nghệ sĩ|ngôi sao|thần tượng|giọng ca)|"
                     r"Nam (?:ca sĩ|idol|rapper|nghệ sĩ|ngôi sao|thần tượng|giọng ca)|Nhóm(?: nhạc)?(?: nữ| nam)?|Giọng ca|"
                     r"Ngôi sao|Thần tượng|She|He|They|The (?:group|singer|star|idol|rapper|artist|band|boy group|girl group))\b")


def find_works(sentence):
    out = []
    for m in WORK_RE.finditer(sentence):
        title = re.sub(r"\s+[.,!]$", "", m.group(1).strip(" ,"))
        if not title or not (title[0].isupper() or title[0].isdigit() or title[0] in "#(["):
            continue
        if len(title.split()) > 7 or re.search(r"[.!?]$", title) and len(title) > 25:
            continue
        kw = m.group(0)[: m.start(1) - m.start(0)]
        etype = "Album" if ALBUM_KW.search(kw) else "Song"
        out.append((m.start(1), m.end(1), title, etype))
    for m in WORK_POSS.finditer(sentence):
        title = re.sub(r"\s+[.,!]$", "", m.group(1).strip(" ,"))
        if title and (title[0].isupper() or title[0].isdigit()) and len(title.split()) <= 7 \
                and not any(o[0] == m.start(1) for o in out):
            out.append((m.start(1), m.end(1), title, "Song"))
    return out


# ---------------------------------------------------------------- 4. Luật quan hệ

ART = ("Artist", "Group")
REL_RULES = [
    # (tên quan hệ, mô tả, regex trigger, loại chủ thể, loại đối tượng, đối xứng?)
    ("RENEWED_CONTRACT", "Tái ký / gia hạn hợp đồng với công ty",
     r"(?<!không )(?<!chưa )(?<!Không )tái ký|(?<!không )(?<!chưa )gia hạn hợp đồng|ký lại hợp đồng|(?<!not )(?<!not to )renew(?:ed|s|ing|al)?(?: (?:their|his|her|its|the))?(?: exclusive)? contracts?|(?<!contemplating her )contract renewal|re-sign(?:ed|s)?",
     ART, ("Company",), False),
    ("LEFT_COMPANY", "Rời công ty / chấm dứt hợp đồng",
     r"rời (?:khỏi )?(?:công ty|nhà|mái nhà|ngôi nhà)|chấm dứt hợp đồng|kết thúc hợp đồng|hết hợp đồng|đáo hạn hợp đồng|không (?:gia hạn|tái ký)|chia tay|parted ways|part ways|depart(?:s|ed|ure)? from|(?:left|leaves|leaving|leave)\b|contracts? (?:with \S+ )?(?:has |have )?(?:ended|expired|expires|end)|terminat(?:e|ed|es|ion)(?: of)?(?: (?:their|his|her|its))?(?: exclusive)? contracts?|not (?:to )?renew|did not renew",
     ART, ("Company",), False),
    ("SIGNED_WITH", "Ký hợp đồng / đầu quân cho công ty",
     r"(?<!không )(?<!chưa )(?<!cấm )ký (?:kết )?hợp đồng|đầu quân|gia nhập|về chung nhà|về nhà mới|công ty mới|sign(?:s|ed|ing)? (?:an? )?(?:exclusive |new |record(?:ing)? |global )?(?:contract|deal)?\s*with|signs? with|inks?|inked|joins?|joined|new (?:home|agency|label)",
     ART, ("Company",), False),
    ("DEBUTED_UNDER", "Ra mắt dưới trướng công ty",
     r"ra mắt|debut(?:s|ed|ing)?|tân binh|rookie|nhóm nhạc (?:nữ |nam )?mới|new (?:girl |boy )?group",
     ART, ("Company",), False),
    ("LEFT_GROUP", "Rời nhóm / rút khỏi nhóm / hoạt động solo",
     r"rời nhóm|rút khỏi|rời khỏi|tách nhóm|leave(?:s)? the group|left the group|leaving the group|depart(?:s|ed|ure)? from|withdraw(?:s|n|al)? from|no longer (?:be )?(?:a member|part)|exit(?:s|ed)?",
     ("Artist",), ("Group",), False),
    ("MEMBER_OF", "Là thành viên của nhóm",
     r"thành viên|trưởng nhóm|em út|giọng ca chính|main vocal|rapper chính|member|leader|maknae|của nhóm|nhóm",
     ("Artist",), ("Group",), False),
    ("LEGAL_ACTION", "Kiện tụng / tranh chấp pháp lý",
     r"(?<!sự )(?<!điều )(?<!Sự )kiện|khởi kiện|đâm đơn|đệ đơn|tranh chấp pháp lý|tố cáo|lawsuit|sue[ds]?|suing|filed (?:a )?(?:suit|lawsuit|complaint|injunction|criminal complaint)|legal (?:battle|dispute)|took legal action|injunction",
     ART + ("Company",), ART + ("Company",), False),
    ("COLLABORATED_WITH", "Hợp tác âm nhạc (collab, featuring, song ca)",
     r"hợp tác|kết hợp|bắt tay|song ca|góp giọng|collab|featuring|feat\.?|ft\.|collaborat(?:e|ed|es|ion|ions|ing)|team(?:s|ed)? up|duet|joint (?:single|song|track)|joins? forces",
     ART, ART, True),
    ("BRAND_AMBASSADOR", "Đại sứ / gương mặt đại diện nhãn hàng",
     r"đại sứ|gương mặt đại diện|gương mặt mới|nàng thơ|người đại diện|đại diện (?:cho |của )?thương hiệu|ambassador|face of|muse|endorse(?:s|d|ment)?|campaign|chiến dịch|quảng cáo|house (?:ambassador|friend)|brand friend",
     ART, ("Brand",), False),
    ("RELEASED", "Phát hành bài hát / album",
     r"ra mắt|phát hành|tung|comeback|trở lại|release[ds]?|releasing|drop(?:s|ped)?|unveil(?:s|ed)?|pre-release|title track|ca khúc chủ đề|MV|music video|album|single|ca khúc|bài hát|hát|'s",
     ART, ("Song", "Album"), False),
    ("WON_AWARD", "Giành giải thưởng / chiến thắng chương trình âm nhạc",
     r"giành|thắng|đoạt|nhận (?:được )?(?:giải|cúp)|chiến thắng|ẵm|cúp|won|wins?|take(?:s)? home|took home|bag(?:s|ged)?|claim(?:s|ed)?|trophy|Daesang|Bonsang|vinh danh|honored",
     ART, ("Award", "Event"), False),
    ("NOMINATED_FOR", "Được đề cử giải thưởng",
     r"đề cử|nominat(?:ed|ion|ions|ee|es)",
     ART, ("Award",), False),
    ("PERFORMED_AT", "Biểu diễn tại sự kiện / lễ hội / lễ trao giải",
     r"biểu diễn|trình diễn|góp mặt|xuất hiện|sân khấu|headline(?:r|s|d)?|perform(?:s|ed|ance|ances|ing)?|stage|lineup|line-up|tham dự|attend(?:s|ed)?",
     ART, ("Event", "Award"), False),
    ("SUBSIDIARY_OF", "Công ty con / nhãn trực thuộc tập đoàn",
     r"công ty con|trực thuộc|nhãn con|thuộc (?:sở hữu|quyền quản lý|hệ thống)|công ty mẹ|subsidiar(?:y|ies)|sub-label|label under|parent company|under (?:the )?umbrella|multi-label",
     ("Company",), ("Company",), False),
    ("ACQUIRED_STAKE", "Thâu tóm / mua cổ phần / đầu tư vào công ty",
     r"thâu tóm|mua lại|sáp nhập|cổ phần|thoái vốn|acquir(?:e|ed|es|ing|ition)|stake|merger|takeover|invest(?:s|ed|ment)? in|buyout|bought",
     ("Company",), ("Company",), False),
    ("PRODUCED_FOR", "Sáng tác / sản xuất cho nghệ sĩ",
     r"sản xuất|sáng tác|viết (?:lời|nhạc|bài)|nhà sản xuất|producer|produc(?:ed|es|ing)|wr(?:ote|itten|ites)|penned|compos(?:ed|er)|songwriter|chắp bút",
     ("Artist",), ART + ("Song", "Album"), False),
]
COMPILED = [(n, d, re.compile(r"(?<!\w)(?:" + t + r")(?!\w)", re.I), st, ot, sym)
            for n, d, t, st, ot, sym in REL_RULES]
OBJ_LEFT_OK = {"BRAND_AMBASSADOR"}
SUBJ_RIGHT_OK = {"BRAND_AMBASSADOR", "PERFORMED_AT"}
MEMBER_SENSITIVE = {"BRAND_AMBASSADOR", "SIGNED_WITH", "RENEWED_CONTRACT", "LEFT_COMPANY", "LEGAL_ACTION",
                    "WON_AWARD", "NOMINATED_FOR", "PRODUCED_FOR"}
ROLE_BEFORE = re.compile(r"(?:thành viên|chị cả|em út|trưởng nhóm|giọng ca|cựu thành viên|mỹ nhân|nữ idol|nam idol|"
                         r"members? of|leader of)\s*(?:của\s*|nhóm\s*|nhóm nhạc\s*)*$", re.I)
# Điều kiện bổ sung: đoạn văn bản bao hai thực thể phải chứa dấu hiệu này
REQUIRE = {
    "DEBUTED_UNDER": re.compile(r"dưới trướng|nhà|thuộc|của|công ty|under|'s|from|by", re.I),
    "PRODUCED_FOR": re.compile(r"\bcho\b|\bfor\b|\bby\b|\bcủa\b", re.I),
}
PASSIVE = re.compile(r"(?:\bbị\b|\bđược\b|\bby\b)\s*$", re.I)
MAX_GAP = 160  # ký tự tối đa giữa chủ thể và đối tượng
NEGATION = re.compile(r"\b(?:tin đồn|phủ nhận|bác bỏ|không phải|rumou?rs?|denied|denies|deny|not true|false|likelihood|"
                      r"possibility|considering|contemplating|có khả năng|có ý định|cân nhắc|dự định)\b", re.I)


def mention_types(gz, m):
    return {gz.ents[i]["type"] for i in m["ids"]}


def resolve(gz, ids, article_ctx):
    """Chọn 1 thực thể cho một mention mơ hồ."""
    if len(ids) == 1:
        return ids[0]
    def score(i):
        e = gz.ents[i]
        ctx = len(gz.groups_of.get(i, set()) & article_ctx) * 1000
        return ctx + e.get("popularity", 0)
    return max(ids, key=score)


def mark_appositives(sent, mentions):
    """Đánh dấu nhóm nằm trong ngoặc ngay sau tên nghệ sĩ: 'Jennie (BLACKPINK)' -> BLACKPINK là đồng vị ngữ."""
    for i in range(1, len(mentions)):
        a, b = mentions[i - 1], mentions[i]
        if a["type"] == "Artist" and b["type"] == "Group" and re.fullmatch(r"\s*\(\s*", sent[a["e"]:b["s"]]):
            b["appos"] = True


# Khoảng cách tối đa (ký tự) từ trigger tới chủ thể bên trái / đối tượng bên phải theo từng quan hệ
WINDOW = {"COLLABORATED_WITH": (60, 30), "LEGAL_ACTION": (50, 60), "SIGNED_WITH": (70, 15), "MEMBER_OF": (35, 35),
          "LEFT_COMPANY": (70, 60), "RENEWED_CONTRACT": (70, 60), "ACQUIRED_STAKE": (60, 60),
          "SUBSIDIARY_OF": (60, 40), "PRODUCED_FOR": (60, 60)}
DEFAULT_WINDOW = (100, 100)
# Câu "điểm tin" ghép nhiều tin rời rạc -> bỏ qua
DIGEST = re.compile(r"Một số tin|tin nổi bật|Đọc thêm|Xem thêm|Tin liên quan|Related", re.I)
# Ngữ cảnh phim ảnh/truyền hình -> bỏ qua các quan hệ dễ nhầm
SCREEN = re.compile(r"\b(?:drama|K-drama|bộ phim|phim truyền hình|phim điện ảnh|movie|film|episode of|tập phim|"
                    r"vai diễn|đóng vai|nhân vật|starring|poster|webtoon|biên kịch|screenwriter|diễn viên|actor|actress)\b",
                    re.I)
SCREEN_SENSITIVE = {"COLLABORATED_WITH", "LEGAL_ACTION", "PRODUCED_FOR", "WON_AWARD", "NOMINATED_FOR"}
COLLAB_JOIN = re.compile(r"^\s*(?:và|and|&|x|×|cùng|with|,)\s*$", re.I)
SUB_CHILD = re.compile(r"công ty con|nhãn con|subsidiar|sub-label", re.I)
SUB_PARENT = re.compile(r"công ty mẹ|parent company", re.I)
NEG_BEFORE = re.compile(r"(?:không|chưa|chẳng|not|not to|chose not to|decided not to|did not|won't|contemplating)\s*$", re.I)


def extract_relations(sent, mentions, gz):
    """mentions: list dict {s,e,id,type,text}. Trả về list (rel, subj, obj, trigger)."""
    mentions = [m for m in mentions if not m.get("appos")]
    if DIGEST.search(sent) or sent.count(";") >= 2:
        return []
    screen = bool(SCREEN.search(sent))
    n_art = sum(m["type"] in ART for m in mentions)
    out = []
    used = set()
    for name, _, trig, stypes, otypes, sym in COMPILED:
        if screen and name in SCREEN_SENSITIVE:
            continue
        wl, wr = WINDOW.get(name, DEFAULT_WINDOW)
        for tm in trig.finditer(sent):
            ts, te = tm.start(), tm.end()
            if name in ("RENEWED_CONTRACT", "SIGNED_WITH", "SUBSIDIARY_OF") and NEG_BEFORE.search(sent[max(0, ts - 20):ts]):
                continue
            left = [m for m in mentions if m["e"] <= ts and (ts - m["e"] <= wl or m.get("coref"))]
            right = [m for m in mentions if m["s"] >= te and m["s"] - te <= wr]
            passive = bool(PASSIVE.search(sent[max(0, ts - 12):ts]))
            pairs = []
            if sym:  # COLLABORATED_WITH
                lefts = [m for m in left if m["type"] in stypes]
                rights = [m for m in right if m["type"] in stypes]
                if lefts and rights:
                    # câu liệt kê nhiều nghệ sĩ: chỉ nhận khi đối tượng đứng sát trigger
                    if n_art < 4 or rights[0]["s"] - te <= 4:
                        pairs.append((lefts[-1], rights[0]))
                elif len(lefts) >= 2 and COLLAB_JOIN.match(sent[lefts[-2]["e"]:lefts[-1]["s"]]) \
                        and ts - lefts[-1]["e"] <= 25:
                    pairs.append((lefts[-2], lefts[-1]))  # "X và Y hợp tác"
            elif name == "RELEASED":
                # ghép mỗi tác phẩm với nghệ sĩ gần nhất bên trái (không có tác phẩm khác chen giữa),
                # hoặc mẫu '"Song" by Artist'
                for w in mentions:
                    if w["type"] not in otypes or not (ts <= w["s"] <= te + 60):
                        continue
                    lefts = [m for m in mentions if m["e"] <= w["s"] and w["s"] - m["e"] <= 90]
                    a = None
                    for m in reversed(lefts):
                        if m["type"] in otypes:
                            break
                        if m["type"] in stypes:
                            a = m
                            break
                    by = re.match(r"\s*\"?\s*(?:by|của)\s+", sent[w["e"]:w["e"] + 12], re.I)
                    if by:
                        a = next((m for m in mentions if m["s"] >= w["e"] and m["type"] in stypes
                                  and m["s"] - w["e"] <= 14), a)
                    if a:
                        pairs.append((a, w))
            else:
                cands = [m for m in reversed(left) if m["type"] in stypes]
                if name in MEMBER_SENSITIVE:
                    # ưu tiên nghệ sĩ cá nhân hơn nhóm khi cả hai cùng ở bên trái trigger
                    cands = [m for m in cands if m["type"] != "Group"] + [m for m in cands if m["type"] == "Group"]
                subj = cands[0] if cands else None
                obj = next((m for m in right if m["type"] in otypes), None)
                if name == "DEBUTED_UNDER" and re.search(r"group|nhóm|tân binh|rookie", tm.group(0), re.I):
                    subj = next((m for m in right if m["type"] in stypes and m["s"] - te <= 25), None) or subj
                    obj = next((m for m in reversed(left) if m["type"] in otypes), None) or obj
                if passive and name in ("LEGAL_ACTION", "PRODUCED_FOR"):
                    # "X bị Y kiện" / "produced by Y": đối tượng bên trái, chủ thể bên phải
                    subj = next((m for m in right if m["type"] in stypes), None)
                    obj = next((m for m in reversed(left) if m["type"] in otypes), None)
                if name == "ACQUIRED_STAKE" and (re.match(r"\s*by\b", sent[te:te + 5], re.I)
                                                 or re.search(r"(?:được|bị)\s*$", sent[max(0, ts - 8):ts])):
                    # "Pledis was acquired by Big Hit" / "Source Music được mua lại" -> bị động
                    subj = next((m for m in right if m["type"] in stypes), None)
                    obj = next((m for m in reversed(left) if m["type"] in otypes), None)
                if obj is None and name in OBJ_LEFT_OK:  # "Chanel công bố Jung Kook trở thành đại sứ"
                    obj = next((m for m in reversed(left) if m["type"] in otypes and m is not subj), None)
                if subj is None and name in SUBJ_RIGHT_OK:  # "đại sứ mới của Saint Laurent - Cha Eun Woo"
                    subj = next((m for m in right if m["type"] in stypes and m is not obj), None)
                if subj and subj["type"] == "Group" and name in MEMBER_SENSITIVE | {"DEBUTED_UNDER"}:
                    # 'thành viên BTS ...' hoặc "Red Velvet's Wendy ..." -> chủ thể thật là thành viên
                    if ROLE_BEFORE.search(sent[max(0, subj["s"] - 25):subj["s"]]) or \
                            re.match(r"'s\s+[A-Z]", sent[subj["e"]:subj["e"] + 5]) or \
                            re.match(r"\s+(?:member|thành viên)", sent[subj["e"]:subj["e"] + 12], re.I):
                        subj = None
                if name == "PRODUCED_FOR" and obj and not passive and not re.search(
                        r"\b(?:cho|for)\s+(?:nhóm\s+|các\s+|ca sĩ\s+|nữ ca sĩ\s+|nam ca sĩ\s+)?$", sent[max(0, obj["s"] - 22):obj["s"]], re.I):
                    obj = None  # 'sáng tác cho X' / 'produced for X'
                if name == "LEGAL_ACTION" and obj and obj["s"] >= te and re.search(
                        r"người|tài khoản|netizen|anti|users?|posts?|accounts?|bài viết|những|malicious|bình luận",
                        sent[te:obj["s"]], re.I):
                    obj = None  # kiện người bôi nhọ X, không phải kiện X
                if name == "SIGNED_WITH" and obj and re.search(
                        r"rời|left|leaving|parting|parted|departure|after|sau khi", sent[te:obj["s"]], re.I):
                    obj = None
                if name == "SUBSIDIARY_OF" and subj and obj:
                    between = sent[te:obj["s"]] if obj["s"] >= te else ""
                    has_of = bool(re.search(r"\b(?:của|of)\b", between))
                    if SUB_CHILD.search(tm.group(0)) and obj["s"] >= te and not has_of and obj["s"] - te <= 4:
                        subj, obj = obj, subj  # "công ty con ADOR": ADOR là công ty con
                    elif SUB_PARENT.search(tm.group(0)) and has_of:
                        subj, obj = obj, subj  # "HYBE - công ty mẹ của Big Hit"
                if subj and obj:
                    pairs.append((subj, obj))
            for a, b in pairs:
                if a["id"] == b["id"]:
                    continue
                real = [m for m in (a, b) if not m.get("coref")]
                span = max([m["e"] for m in real] + [te]) - min([m["s"] for m in real] + [ts])
                if span > MAX_GAP + (te - ts):
                    continue
                if name in REQUIRE:
                    lo = min([m["s"] for m in real] + [ts])
                    hi = max([m["e"] for m in real] + [te])
                    if not REQUIRE[name].search(sent[lo:hi]):
                        continue
                key = (name, a["id"], b["id"]) if not sym else (name,) + tuple(sorted((a["id"], b["id"])))
                if key in used:
                    continue
                used.add(key)
                out.append((name, a, b, tm.group(0)))
    return out


# Mẫu cấu trúc đặc thù có độ chính xác cao cho MEMBER_OF
PAREN = re.compile(r"\s*\(\s*$")


def structural_member(sent, mentions):
    """'Jennie (BLACKPINK)' và "BLACKPINK's Jennie" / 'BLACKPINK Jennie'."""
    out = []
    for i, m in enumerate(mentions):
        if m["type"] != "Artist":
            continue
        nxt = mentions[i + 1] if i + 1 < len(mentions) else None
        prv = mentions[i - 1] if i > 0 else None
        if nxt and nxt["type"] == "Group":
            between = sent[m["e"]:nxt["s"]]
            if re.fullmatch(r"\s*\(\s*", between) or re.fullmatch(r"\s*(?:của|thuộc|nhóm|-|–)\s*(?:nhóm\s*)?", between):
                out.append(("MEMBER_OF", m, nxt, between.strip() or "()"))
        if prv and prv["type"] == "Group":
            between = sent[prv["e"]:m["s"]]
            if re.fullmatch(r"'s\s+(?:member\s+|leader\s+|maknae\s+)?", between) or re.fullmatch(r"\s+(?:member|thành viên|trưởng nhóm|em út)\s+", between):
                out.append(("MEMBER_OF", m, prv, between.strip()))
    return out


def main():
    gz = Gazetteer()
    arts = read_jsonl(RAW_DIR / "articles.jsonl")
    print("Số bài báo:", len(arts), "| số thực thể từ điển:", len(gz.ents))
    stats = Counter()
    rels = []
    seen_urls = set()
    seen_text = set()
    for a in arts:
        if a["url"] in seen_urls:
            continue
        seen_urls.add(a["url"])
        body_key = (a.get("title", "") + "".join(a["paragraphs"][:2]))[:300]
        if body_key in seen_text:  # trùng lặp nội dung (bài đăng lại)
            stats["dup_articles"] += 1
            continue
        seen_text.add(body_key)
        stats["articles"] += 1
        stats["articles_" + a["lang"]] += 1
        units = [a.get("title", "")] + [a.get("sapo", "")] + a["paragraphs"]
        sents = []
        for u in units:
            sents.extend(split_sentences(normalize(u)))
        stats["sentences"] += len(sents)
        # Lượt 1: thu thập ngữ cảnh nhóm trong bài để khử nhập nhằng
        raw_hits = [(s, gz.find(s)) for s in sents]
        ctx = set()
        for _, hits in raw_hits:
            for h in hits:
                if len(h[3]) == 1:
                    ctx.add(h[3][0])
                    ctx |= gz.groups_of.get(h[3][0], set())
        art_had = False
        main_ent = None
        if raw_hits:
            for st, en, surf, ids in raw_hits[0][1]:  # câu đầu tiên = tiêu đề
                eid = resolve(gz, list(ids), ctx)
                if gz.ents[eid]["type"] in ("Artist", "Group"):
                    main_ent = {"id": eid, "type": gz.ents[eid]["type"], "text": surf}
                    break
        for s, hits in raw_hits:
            mentions = []
            for st, en, surf, ids in hits:
                eid = resolve(gz, list(ids), ctx)
                mentions.append({"s": st, "e": en, "id": eid, "type": gz.ents[eid]["type"], "text": surf})
            # Tác phẩm (bài hát/album) theo mẫu ngoặc kép + từ khóa
            for st, en, title, wtype in find_works(s):
                if any(not (en <= m["s"] or st >= m["e"]) for m in mentions):
                    mentions = [m for m in mentions if en <= m["s"] or st >= m["e"]]
                known = [x for x in gz.works.iter(title.lower()) if x[1][0] == title.lower()]
                wid = known[0][1][1][0] if known else None
                mentions.append({"s": st, "e": en, "id": wid or f"NEW_{wtype}:{title}", "type": wtype,
                                 "text": title, "new": not known})
            # Chuỗi trong ngoặc kép trùng đúng tên tác phẩm đã biết của nghệ sĩ có mặt trong bài
            for qm in QUOTED.finditer(s):
                st, en = qm.start(1), qm.end(1)
                if any(not (en <= m["s"] or st >= m["e"]) for m in mentions):
                    continue
                t = qm.group(1).strip().lower()
                cands = [x[1][1] for x in gz.works.iter(t) if x[1][0].lower() == t]
                cands = [i for ids in cands for i in ids if gz.groups_of.get(i, set()) & ctx]
                if cands:
                    mentions.append({"s": st, "e": en, "id": cands[0], "type": gz.ents[cands[0]]["type"],
                                     "text": qm.group(1).strip()})
            # Đồng tham chiếu đơn giản: đại từ đầu câu -> nhân vật chính (xuất hiện trong tiêu đề)
            pm = PRONOUN.match(s) if main_ent else None
            if pm and not any(m["id"] == main_ent["id"] for m in mentions):
                group_word = re.match(r"Nhóm|They|The (?:group|band|boy group|girl group)", pm.group(0))
                if (main_ent["type"] == "Group") == bool(group_word):
                    mentions.append(dict(main_ent, s=0, e=0, coref=True))
            mentions.sort(key=lambda m: m["s"])
            stats["mentions"] += len(mentions)
            if len(mentions) < 2:
                continue
            mark_appositives(s, mentions)
            found = structural_member(s, mentions) + extract_relations(s, mentions, gz)
            neg = bool(NEGATION.search(s))
            found = [f for f in found if not ((f[1].get("coref") or f[2].get("coref"))
                                              and f[0] in ("MEMBER_OF", "DEBUTED_UNDER", "LEFT_GROUP"))]
            for name, a_, b_, trig in found:
                # Tác phẩm mới phải gắn với nghệ sĩ -> định danh = tiêu đề + nghệ sĩ thể hiện
                def wid(m, other):
                    if m.get("new") or m["id"].startswith("NEW_"):
                        return f"{m['type']}:{m['text'].lower()}|{other['id']}"
                    return m["id"]
                sid = wid(a_, b_) if a_["type"] in ("Song", "Album") else a_["id"]
                oid = wid(b_, a_) if b_["type"] in ("Song", "Album") else b_["id"]
                if b_["type"] in ("Song", "Album") and name not in ("RELEASED", "PRODUCED_FOR"):
                    continue
                if name in ("LEGAL_ACTION", "COLLABORATED_WITH", "SIGNED_WITH") and (
                        b_["id"] in gz.groups_of.get(a_["id"], set()) or a_["id"] in gz.groups_of.get(b_["id"], set())):
                    continue  # nghệ sĩ với chính nhóm của mình
                if name in ("MEMBER_OF", "LEFT_GROUP"):
                    known = gz.groups_of.get(a_["id"], set())
                    if known and b_["id"] not in known:
                        stats["member_conflict_dropped"] += 1
                        continue
                rels.append({
                    "rel": name, "src": sid, "dst": oid,
                    "src_name": gz.ents[a_["id"]]["name"] if a_["id"] in gz.ents else a_["text"],
                    "dst_name": gz.ents[b_["id"]]["name"] if b_["id"] in gz.ents else b_["text"],
                    "src_type": a_["type"], "dst_type": b_["type"], "trigger": trig,
                    "negated_or_rumor": neg, "coref": bool(a_.get("coref") or b_.get("coref")), "sentence": s, "url": a["url"], "source": a["source"],
                    "lang": a["lang"], "date": a.get("published", "")[:10],
                })
                art_had = True
        stats["articles_with_relations"] += art_had
    write_jsonl(PROC_DIR / "relations.jsonl", rels)
    stats["relation_mentions"] = len(rels)
    json.dump(dict(stats), open(PROC_DIR / "preprocess_stats.json", "w"), ensure_ascii=False, indent=2)
    print(dict(stats))
    print(Counter(r["rel"] for r in rels).most_common())


if __name__ == "__main__":
    main()
