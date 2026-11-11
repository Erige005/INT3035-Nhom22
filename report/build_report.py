"""Sinh báo cáo .docx từ kết quả pipeline (số liệu đọc trực tiếp từ data/graph/*.json)."""
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT  # noqa: F401
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from common import OUT_DIR, PROC_DIR, RAW_DIR, read_jsonl  # noqa: E402
from extract import REL_RULES  # noqa: E402

GITHUB_URL = (ROOT / "report" / "github_url.txt").read_text().strip() if (ROOT / "report" / "github_url.txt").exists() else "(chưa có — cập nhật sau khi tạo repo)"
ASSIGNMENT = ROOT / "report" / "assignment.json"  # phân công do nhóm cung cấp

st = json.load(open(OUT_DIR / "stats.json", encoding="utf-8"))
summ = json.load(open(OUT_DIR / "summary.json", encoding="utf-8"))
gds = json.load(open(OUT_DIR / "neo4j_gds.json", encoding="utf-8")) if (OUT_DIR / "neo4j_gds.json").exists() else {}
pre = st["preprocess"]
urls = read_jsonl(RAW_DIR / "urls.jsonl")
url_by_src = Counter(r["source"] for r in urls)
arts = read_jsonl(RAW_DIR / "articles.jsonl")
art_by_src = Counter(a["source"] for a in arts)
evid = read_jsonl(OUT_DIR / "edges_evidence.jsonl")
qc = json.load(open(OUT_DIR / "quality_check.json", encoding="utf-8")) if (OUT_DIR / "quality_check.json").exists() else None
_dates = sorted(a["published"][:7] for a in arts if re.match(r"20\d\d-\d\d", a.get("published", "")))
_p5 = _dates[len(_dates) // 200] if _dates else ""  # bỏ 0,5% bài cũ ngoại lệ (bài cũ được cập nhật lại)
DATE_MIN = f"{_p5[5:7]}/{_p5[:4]}" if _p5 else "?"
DATE_MAX = f"{_dates[-1][5:7]}/{_dates[-1][:4]}" if _dates else "?"
gaz_n = sum(1 for _ in open(ROOT / "data" / "gazetteer" / "entities.jsonl", encoding="utf-8"))

SRC_NAME = {"kenh14": "Kênh14 (kenh14.vn)", "thanhnien": "Thanh Niên (thanhnien.vn)",
            "tuoitre": "Tuổi Trẻ (tuoitre.vn)", "znews": "Znews (znews.vn)", "soompi": "Soompi (soompi.com)"}
NODE_DESC = {
    "Artist": ("Nghệ sĩ / idol / ca sĩ solo / nhà sản xuất", "Jennie, Taylor Swift, Jungkook"),
    "Group": ("Nhóm nhạc, ban nhạc", "BLACKPINK, BTS, NewJeans, Coldplay"),
    "Company": ("Tập đoàn giải trí, công ty quản lý, hãng đĩa", "HYBE, ADOR, SM Entertainment, Universal Music Group"),
    "Brand": ("Nhãn hàng thời trang, xa xỉ, mỹ phẩm, tiêu dùng", "Chanel, Dior, Calvin Klein, Samsung"),
    "Award": ("Giải thưởng / lễ trao giải âm nhạc", "MAMA Awards, Grammy Awards, Golden Disc Awards"),
    "Event": ("Sự kiện, lễ hội, show âm nhạc, tuần lễ thời trang", "Coachella, Inkigayo, Met Gala"),
    "Song": ("Bài hát / đĩa đơn", "APT., Supernova, Espresso"),
    "Album": ("Album / EP / mini album", "Born Pink, Rosie"),
}

doc = Document()
sec = doc.sections[0]
sec.page_height, sec.page_width = Cm(29.7), Cm(21)
sec.left_margin, sec.right_margin, sec.top_margin, sec.bottom_margin = Cm(3), Cm(2), Cm(2), Cm(2)
style = doc.styles["Normal"]
style.font.name = "Times New Roman"
style.element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
style.font.size = Pt(13)
style.paragraph_format.space_after = Pt(4)
style.paragraph_format.line_spacing = 1.3
for lvl, size in ((1, 15), (2, 13.5), (3, 13)):
    hs = doc.styles[f"Heading {lvl}"]
    hs.font.name = "Times New Roman"
    hs.element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
    hs.font.size = Pt(size)
    hs.font.bold = True
    hs.font.color.rgb = RGBColor(0x1F, 0x3A, 0x5F)


def p(text, bold=False, italic=False, align=None, size=None):
    para = doc.add_paragraph()
    run = para.add_run(text)
    run.bold, run.italic = bold, italic
    if size:
        run.font.size = Pt(size)
    if align:
        para.alignment = align
    else:
        para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    return para


def bullet(text):
    para = doc.add_paragraph(style="List Bullet")
    para.add_run(text)
    return para


HEADINGS = []


def h(text, lvl=1):
    HEADINGS.append((lvl, text))
    return doc.add_heading(text, level=lvl)


def shade(cell, color="D9E2F3"):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), color)
    tcPr.append(shd)


def table(header, rows, widths=None, size=10.5):
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, x in enumerate(header):
        c = t.rows[0].cells[i]
        c.text = ""
        r = c.paragraphs[0].add_run(str(x))
        r.bold = True
        r.font.size = Pt(size)
        shade(c)
    for row in rows:
        cells = t.add_row().cells
        for i, x in enumerate(row):
            cells[i].text = ""
            r = cells[i].paragraphs[0].add_run(str(x))
            r.font.size = Pt(size)
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Cm(w)
    doc.add_paragraph()
    return t


def fig(name, caption, width=15):
    path = OUT_DIR / "figures" / name
    if not path.exists():
        return
    doc.add_picture(str(path), width=Cm(width))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    p(caption, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER, size=11)


def page_break():
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


TOC_PAGES = ROOT / "report" / "toc_pages.json"


def toc():
    """Mục lục tĩnh: số trang lấy từ lượt xuất PDF trước (make_report.sh chạy 2 lượt)."""
    if TOC_PAGES.exists():
        for lvl, text, page in json.load(open(TOC_PAGES, encoding="utf-8")):
            para = doc.add_paragraph()
            para.paragraph_format.left_indent = Cm(0.8 * (lvl - 1))
            para.paragraph_format.tab_stops.add_tab_stop(Cm(16), alignment=2, leader=1)  # phải, dấu chấm
            r = para.add_run(f"{text}\t{page}")
            r.bold = lvl == 1
        return
    para = doc.add_paragraph()
    run = para.add_run()
    for tag, txt in (("begin", None), (None, 'TOC \\o "1-2" \\h \\z \\u'), ("separate", None),
                     (None, None), ("end", None)):
        if tag:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), tag)
            run._r.append(el)
        elif txt:
            el = OxmlElement("w:instrText")
            el.set(qn("xml:space"), "preserve")
            el.text = txt
            run._r.append(el)
        else:
            t = OxmlElement("w:t")
            t.text = "(Nhấn chuột phải → Update Field để cập nhật mục lục)"
            run._r.append(t)


fmt = lambda x: f"{x:,}".replace(",", ".")  # noqa: E731

# ================================================================ BÌA
for line, sz, b in (("ĐẠI HỌC QUỐC GIA HÀ NỘI", 13, False), ("TRƯỜNG ĐẠI HỌC CÔNG NGHỆ", 14, True),
                    ("KHOA CÔNG NGHỆ THÔNG TIN", 13, True)):
    p(line, bold=b, align=WD_ALIGN_PARAGRAPH.CENTER, size=sz)
for _ in range(4):
    doc.add_paragraph()
p("BÁO CÁO BÀI TẬP", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, size=16)
p("Học phần: Phân tích mạng phương tiện xã hội trong kinh doanh (INT3035)",
  align=WD_ALIGN_PARAGRAPH.CENTER, size=13)
doc.add_paragraph()
p("ĐỀ TÀI 24", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, size=14)
p("XÂY DỰNG MẠNG LƯỚI NGÔI SAO ÂM NHẠC, THẦN TƯỢNG K-POP/US-UK VÀ TẬP ĐOÀN GIẢI TRÍ QUỐC TẾ "
  "TỪ DỮ LIỆU BÁO CHÍ BẰNG KỸ THUẬT XỬ LÝ NGÔN NGỮ TỰ NHIÊN",
  bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, size=15)
for _ in range(4):
    doc.add_paragraph()
table(["Thành viên nhóm 22", "Mã sinh viên"],
      [["Nguyễn Nhật Nam", "23020557"], ["Lưu Đạt Tuấn Nghĩa", "23020559"]], widths=[8, 5], size=12)
p("Giảng viên: TS. Trần Mai Vũ", align=WD_ALIGN_PARAGRAPH.CENTER)
p("Nguồn dữ liệu được phân công: Báo chí (mã báo chí-8)", align=WD_ALIGN_PARAGRAPH.CENTER)
for _ in range(3):
    doc.add_paragraph()
p("Hà Nội, tháng 11 năm 2026", italic=True, align=WD_ALIGN_PARAGRAPH.CENTER)
page_break()

h("MỤC LỤC", 1)
toc()
page_break()

# ================================================================ 1. PHÂN CÔNG
h("1. Phân công công việc trong nhóm", 1)
if ASSIGNMENT.exists():
    asg = json.load(open(ASSIGNMENT, encoding="utf-8"))
    table(["Thành viên", "Nhiệm vụ"], [[a["name"], a["tasks"]] for a in asg], widths=[4.5, 11.5])
else:
    table(["Thành viên", "Nhiệm vụ"],
          [["Nguyễn Nhật Nam (23020557)", "(nhóm điền)"], ["Lưu Đạt Tuấn Nghĩa (23020559)", "(nhóm điền)"]],
          widths=[4.5, 11.5])

# ================================================================ 2. GIỚI THIỆU MẠNG
h("2. Giới thiệu mạng đã xây dựng", 1)
h("2.1. Bài toán và phạm vi", 2)
p("Đề tài 24 yêu cầu xây dựng mạng lưới kết nối các ngôi sao âm nhạc, thần tượng K-Pop và ca sĩ Âu Mỹ "
  "(US-UK) với các tập đoàn giải trí quốc tế (HYBE, SM, YG, JYP, Universal Music…) và các nhãn hàng, "
  "dựa trên tin tức báo chí. Đây là loại mạng thông tin – xã hội đa quan hệ (multi-relational, "
  "heterogeneous network): các nút thuộc nhiều loại thực thể, các cạnh có hướng, có loại và có trọng số.")
p("Phạm vi được nhóm lựa chọn: toàn bộ K-Pop và nhạc US-UK (không thu hẹp), với mục tiêu tối thiểu "
  "2.000 nút, 5.000 cạnh và 10 loại quan hệ. Dữ liệu là bài báo tiếng Việt (nguồn chính) và tiếng Anh "
  f"(bổ sung) đăng trong khoảng {DATE_MIN} – {DATE_MAX}.")
p("Trọng tâm của mạng là lớp lõi nghệ sĩ – công ty – nhãn hàng: nghệ sĩ/nhóm nhạc trực thuộc, ký, tái ký "
  "hoặc rời công ty quản lý nào; các công ty là công ty con của tập đoàn nào; nghệ sĩ nào làm đại sứ cho nhãn "
  "hàng nào. Lớp bài hát/album được giữ làm lớp phụ, mô tả sản phẩm âm nhạc mà nghệ sĩ phát hành.")
p("Ý nghĩa kinh doanh: (1) với nhãn hàng — biết idol nào đang là đại sứ của đối thủ, idol nào có độ trung tâm "
  "cao (PageRank, bậc) để lựa chọn cho chiến dịch influencer marketing; (2) với nhà đầu tư/đối tác — theo dõi "
  "biến động hợp đồng của nghệ sĩ (ký mới, tái ký, rời công ty) và cấu trúc sở hữu giữa các tập đoàn (HYBE, "
  "SM, YG, JYP, Kakao…); (3) phát hiện các cụm cộng đồng nghệ sĩ – công ty – nhãn hàng. Quan hệ tranh chấp "
  "pháp lý đã được thử trích xuất nhưng độ chính xác chưa đạt (mục 8) nên chưa đưa vào đồ thị; theo dõi "
  "tranh chấp được chuyển sang hướng phát triển.")

h("2.2. Lựa chọn nút", 2)
p("Nguyên tắc: mỗi nút là một thực thể có danh tính rõ ràng trong ngành giải trí, và chỉ đưa vào đồ thị khi "
  "tham gia ít nhất một quan hệ nghiệp vụ được trích xuất từ báo. Nhóm KHÔNG dùng bài báo, câu văn hay "
  "từ khóa làm nút; bài báo và câu dẫn chứng chỉ là metadata gắn trên cạnh.")
nt = st["node_types"]
table(["Loại nút", "Lớp", "Ý nghĩa", "Ví dụ", "Số nút"],
      [[k, "Phụ" if k in ("Song", "Album") else "Lõi", NODE_DESC[k][0], NODE_DESC[k][1], fmt(nt.get(k, 0))]
       for k in NODE_DESC], widths=[2, 1.3, 4.7, 6, 2])
_works = nt.get("Song", 0) + nt.get("Album", 0)
p(f"Tổng số nút: {fmt(st['nodes'])}. Lớp lõi (nghệ sĩ, nhóm, công ty, nhãn hàng, giải thưởng, sự kiện) có "
  f"{fmt(st['nodes'] - _works)} nút, trong đó {fmt(st['core_nodes'])} nút có quan hệ với một nút lõi khác; lớp phụ "
  f"có {fmt(_works)} nút bài hát/album ({_works / st['nodes']:.0%}). Lớp phụ giúp nối các nghệ sĩ qua sản phẩm "
  "chung (tương tự ví dụ 'diễn viên nối với nhau qua bộ phim' của đề bài), nhưng phần phân tích kinh doanh tập "
  "trung vào lớp lõi. Thuộc tính của nút: id (mã Wikidata QID nếu có, hoặc mã nội bộ), name (tên chuẩn), type, "
  "popularity (số liên kết Wikipedia – dùng để khử nhập nhằng), mentions (số lần xuất hiện trong quan hệ).")

h("2.3. Lựa chọn cạnh (loại quan hệ)", 2)
p("Cạnh được thiết kế theo nghiệp vụ của đề tài (Ra mắt/Tái ký hợp đồng, Hợp tác toàn cầu, Đại diện thời trang) "
  "và được mở rộng để mô tả vòng đời nghệ sĩ. Mỗi loại cạnh có ràng buộc kiểu nút nguồn → nút đích, nên một cạnh "
  "chỉ được tạo khi hai thực thể đúng loại cùng xuất hiện trong một câu có từ kích hoạt tương ứng.")
et = st["edge_types"]
rows = []
for name, desc, _, stypes, otypes, sym in REL_RULES:
    if name not in et:
        continue
    layer = "Phụ" if set(otypes) <= {"Song", "Album"} else "Lõi"
    rows.append([name, layer, desc, "/".join(stypes) + (" ↔ " if sym else " → ") + "/".join(otypes),
                 fmt(et.get(name, 0))])
table(["Loại quan hệ", "Lớp", "Ý nghĩa", "Nguồn → Đích", "Số cạnh"], rows, widths=[3.8, 1.2, 4.8, 4.4, 1.8],
      size=9.5)
p(f"Tổng số cạnh (bộ ba duy nhất nguồn – quan hệ – đích): {fmt(st['edges'])}, gồm {fmt(st['core_edges'])} cạnh "
  f"giữa các nút lõi và {fmt(st['work_edges'])} cạnh nối tới lớp bài hát/album; số loại quan hệ: "
  f"{st['relation_types']}. Quan hệ LEGAL_ACTION (kiện tụng/tranh chấp) đã được xây dựng luật trích xuất nhưng bị "
  "loại khỏi đồ thị vì độ chính xác trên mẫu chỉ khoảng 51% (mục 8). Như vậy, trong nghiệp vụ 'kiện chấm dứt "
  "hợp đồng' của đề bài, phần 'chấm dứt hợp đồng' vẫn được LEFT_COMPANY đảm nhận (ví dụ NewJeans → ADOR); chỉ "
  "phần 'kiện' là chưa có trong đồ thị. Thuộc tính cạnh: support (số bài báo khác "
  "nhau làm dẫn chứng), first_date/last_date (ngày bài báo sớm/muộn nhất), langs, sources, evidence_sentences "
  "và evidence_urls (tối đa 3 câu dẫn chứng kèm URL).")

h("2.4. Ví dụ cạnh kèm dẫn chứng", 2)
p("Các ví dụ dưới đây được chọn trong số những cạnh đã được kiểm tra là đúng ở mục 8 (mỗi loại quan hệ một ví "
  "dụ, ưu tiên câu ngắn).")
import csv  # noqa: E402
rev = [r for r in csv.DictReader(open(OUT_DIR / "review_sample.csv", encoding="utf-8")) if r.get("label") == "1"]
ex_rows = []
for rel in [r[0] for r in REL_RULES]:
    cands = [r for r in rev if r["rel"] == rel and rel in st["edge_types"]]
    if not cands:
        continue
    r = min(cands, key=lambda x: (not 40 <= len(x["sentence"]) <= 200, int(x["support"]) < 2, len(x["sentence"])))
    s = r["sentence"]
    ex_rows.append([f"{r['src']} –[{rel}]→ {r['dst']}", (s[:230] + "…") if len(s) > 230 else s, r["support"]])
table(["Cạnh", "Câu dẫn chứng (trích từ báo)", "Support"], ex_rows, widths=[5, 9.5, 1.5], size=9.5)

# ================================================================ 3. STACK
h("3. Stack công nghệ thu thập và xử lý dữ liệu", 1)
p("Lưu ý: mẫu báo cáo của đề bài nhắc tới Wikipedia, nhưng đề tài 24 được phân công nguồn BÁO CHÍ. Toàn bộ "
  "quan hệ trong đồ thị được trích xuất từ văn bản bài báo. Wikidata chỉ được dùng làm từ điển tên thực thể "
  "(gazetteer) phục vụ bước nhận dạng thực thể, không dùng để sinh cạnh.")
table(["Thành phần", "Công nghệ", "Vai trò"], [
    ["Ngôn ngữ", "Python 3.15", "Toàn bộ pipeline"],
    ["Thu thập", "requests, sitemap XML, robots.txt", "Liệt kê và tải bài báo; độ trễ lịch sự 0,5 s/yêu cầu"],
    ["Bóc tách HTML", "BeautifulSoup4", "Lấy tiêu đề, sapo, ngày đăng, các đoạn thân bài"],
    ["Từ điển thực thể", "Wikidata SPARQL + danh sách thủ công", f"{fmt(gaz_n)} thực thể ứng viên kèm bí danh"],
    ["NER", "pyahocorasick (Aho–Corasick) + luật biên từ + mẫu regex", "Nhận dạng tên nghệ sĩ, nhóm, công ty, nhãn hàng, giải thưởng, sự kiện, bài hát/album"],
    ["Trích xuất quan hệ", "Luật trigger song ngữ Việt–Anh + ràng buộc kiểu", "Phân loại 16 loại quan hệ"],
    ["CSDL đồ thị", "Neo4j Community 2026.10 + GDS + APOC", "Lưu trữ, truy vấn Cypher, chạy thuật toán đồ thị"],
    ["Phân tích", "NetworkX, Matplotlib", "Thống kê mạng, biểu đồ"],
    ["Báo cáo / mã nguồn", "python-docx, Git/GitHub", "Sinh báo cáo, quản lý mã"],
], widths=[3.2, 5.8, 7])
p("Lý do chọn Neo4j: (1) mô hình property graph phù hợp đồ thị dị thể nhiều loại cạnh; (2) Cypher thuận tiện "
  "cho truy vấn đường đi, láng giềng nhiều bước; (3) thư viện Graph Data Science có sẵn PageRank, Louvain, "
  "Betweenness, Node Similarity, Link Prediction — đáp ứng các thuật toán cho bài tập cuối kỳ (phát hiện cộng "
  "đồng, dự đoán liên kết, tìm người ảnh hưởng).")
h("3.1. Kiến trúc pipeline", 2)
for i, s in enumerate([
    "build_gazetteer.py — dựng từ điển thực thể từ Wikidata (nhóm K-pop, nghệ sĩ K-pop, nghệ sĩ/ban nhạc US-UK-CA-AU-IE, thành viên nhóm, hãng đĩa, bài hát/album) và danh sách thủ công (nhãn hàng, giải thưởng, sự kiện, công ty Hàn).",
    "collect_urls.py — đọc sitemap theo ngày của 5 trang báo, lọc URL theo slug chứa tên thực thể/từ khóa K-pop – US-UK.",
    "fetch_articles.py — tải bài, bóc tách nội dung.",
    "extract.py — tiền xử lý, tách câu, NER, trích xuất quan hệ, lưu bộ ba kèm dẫn chứng.",
    "build_graph.py — gộp bộ ba, tính support, loại câu tin đồn/phủ nhận, xuất nodes.csv/edges.csv.",
    "load_neo4j.py — nạp vào Neo4j, chạy PageRank/Louvain/Degree bằng GDS.",
    "stats.py — thống kê mạng và vẽ biểu đồ; report/build_report.py — sinh báo cáo này.",
], 1):
    p(f"Bước {i}. {s}")

# ================================================================ 4. THU THẬP + TIỀN XỬ LÝ
h("4. Thu thập dữ liệu", 1)
p("Các trang được chọn đều cho phép thu thập với User-agent chung trong robots.txt. Nhóm không thu thập "
  "Billboard và VnExpress vì robots.txt của hai trang này hạn chế nhiều loại bot thu thập tự động. Mỗi luồng "
  "tải nghỉ 0,5–0,8 giây giữa hai yêu cầu.")
table(["Nguồn", "Ngôn ngữ", "URL sau lọc", "Bài tải thành công"],
      [[SRC_NAME[s], "Anh" if s == "soompi" else "Việt", fmt(url_by_src.get(s, 0)), fmt(art_by_src.get(s, 0))]
       for s in SRC_NAME] + [["Tổng", "", fmt(len(urls)), fmt(len(arts))]], widths=[5.5, 2, 3.5, 4])
fig("edge_sources.png", "Hình 1. Số cạnh có dẫn chứng theo từng nguồn báo", 13)

h("5. Các bước tiền xử lý dữ liệu", 1)
steps = [
    ("Lọc URL theo slug", "Slug URL (không dấu) được tách n-gram 1–4 từ và so với tập slug của tên thực thể "
     "trong từ điển + từ khóa (kpop, idol, sao-au-my, dai-su-toan-cau…) để giữ bài đúng chủ đề."),
    ("Bóc tách nội dung", "Bỏ script/style/figure/caption/bảng/iframe; lấy khối HTML có nhiều đoạn <p> trực "
     "tiếp nhất làm thân bài; bỏ đoạn < 25 ký tự và dòng 'Nguồn/Ảnh/Video/Xem thêm'."),
    ("Khử trùng lặp", "Loại URL trùng và bài đăng lại có cùng tiêu đề + đoạn mở đầu."),
    ("Chuẩn hóa văn bản", "Chuẩn Unicode NFC (tránh lỗi tiếng Việt tổ hợp), thống nhất ngoặc kép cong → thẳng, "
     "bỏ emoji, ký tự điều khiển, khoảng trắng không ngắt, gộp khoảng trắng."),
    ("Tách câu", "Tách theo dấu . ! ? … khi theo sau là chữ hoa/số/ngoặc; bảo vệ viết tắt (feat., ft., Inc., "
     "U.S., D.O., APT.…); giữ câu dài 15–600 ký tự."),
    ("Nhận dạng thực thể", "Khớp từ điển Aho–Corasick có kiểm tra biên từ, ưu tiên khớp dài nhất, không chồng "
     "lấn; chỉ khớp các biến thể viết hoa hợp lệ (BLACKPINK/Blackpink) để tránh nhầm từ thường; loại bí danh "
     "quá ngắn hoặc là từ thông dụng; khử nhập nhằng tên trùng bằng ngữ cảnh nhóm trong cùng bài rồi độ phổ biến."),
    ("Nhận dạng bài hát/album", "Mẫu regex: chuỗi trong ngoặc kép đứng sau từ khóa (ca khúc, bài hát, single, "
     "album, MV, EP, song, track…). Tác phẩm mới được định danh bằng tiêu đề + nghệ sĩ thể hiện để tránh gộp "
     "nhầm các bài trùng tên."),
    ("Đồng tham chiếu đơn giản", "Câu mở đầu bằng đại từ/danh từ chỉ người (Cô, Anh, Nữ ca sĩ, Nhóm, She, They, "
     "The group…) được gán chủ thể là nhân vật chính của bài (nghệ sĩ/nhóm đầu tiên trong tiêu đề), có kiểm tra "
     "khớp loại (Nhóm ↔ Group, Cô/Anh ↔ Artist); không áp dụng cho MEMBER_OF, DEBUTED_UNDER, LEFT_GROUP. Cạnh "
     "sinh ra theo cách này được gắn cờ coref."),
    ("Lọc tin đồn", "Câu chứa 'tin đồn, phủ nhận, bác bỏ, rumor, denied…' không được dùng làm dẫn chứng cho các "
     "quan hệ hợp đồng, rời nhóm, đại sứ."),
]
table(["Bước", "Mô tả"], steps, widths=[3.8, 12.2], size=10.5)
table(["Chỉ số tiền xử lý", "Giá trị"], [
    ["Bài báo sau khử trùng lặp", fmt(pre.get("articles", 0))],
    ["  – tiếng Việt / tiếng Anh", f"{fmt(pre.get('articles_vi', 0))} / {fmt(pre.get('articles_en', 0))}"],
    ["Bài trùng nội dung bị loại", fmt(pre.get("dup_articles", 0))],
    ["Số câu sau tách", fmt(pre.get("sentences", 0))],
    ["Số lượt nhận dạng thực thể (mention)", fmt(pre.get("mentions", 0))],
    ["Số lượt quan hệ trích xuất (trước gộp)", fmt(pre.get("relation_mentions", 0))],
    ["Bài báo có ít nhất 1 quan hệ", fmt(pre.get("articles_with_relations", 0))],
    ["Lượt quan hệ bị loại do tin đồn/phủ nhận", fmt(summ.get("dropped_rumor_mentions", 0))],
], widths=[10, 6])

h("5.1. Trích xuất quan hệ", 2)
p("Với mỗi câu có ít nhất hai thực thể, hệ thống duyệt 15 luật ứng với 15 loại quan hệ của đồ thị. Mỗi luật gồm biểu thức trigger song ngữ, "
  "tập loại nút nguồn và tập loại nút đích. Chủ thể là thực thể đúng loại gần nhất bên trái trigger, đối tượng "
  "là thực thể đúng loại gần nhất bên phải; với câu bị động ('produced by', 'được … mua lại', 'was acquired by') chiều được đảo. "
  "Khoảng cách giữa hai thực thể không quá 160 ký tự. Riêng MEMBER_OF còn có mẫu cấu trúc độ chính xác cao "
  "đặc trưng của báo chí: 'Jennie (BLACKPINK)' và \"BLACKPINK's Jennie\". Quan hệ COLLABORATED_WITH là đối "
  "xứng. Các lượt trích xuất giống nhau được gộp, support là số bài báo khác nhau.")

# ================================================================ 6. NEO4J
h("6. Lưu trữ trong Neo4j", 1)
p("Mỗi nút có hai nhãn: :Entity và nhãn loại (:Artist, :Group, :Company, :Brand, :Award, :Event, :Song, "
  ":Album); ràng buộc duy nhất trên Entity.id. Mỗi loại quan hệ là một relationship type của Neo4j, có các "
  "thuộc tính support, first_date, last_date, langs, sources, evidence_sentences, evidence_urls.")
p("Ví dụ truy vấn Cypher:", bold=True)
for q in [
    "// Các nhãn hàng có nhiều đại sứ K-pop nhất\nMATCH (a)-[r:BRAND_AMBASSADOR]->(b:Brand)\nRETURN b.name, count(a) AS so_dai_su ORDER BY so_dai_su DESC LIMIT 10;",
    "// Mạng lưới quanh HYBE trong 2 bước\nMATCH p=(c:Company {name:'HYBE'})-[*1..2]-(x) RETURN p LIMIT 200;",
    "// Nghệ sĩ/nhóm rời công ty kèm câu dẫn chứng\nMATCH (a)-[r:LEFT_COMPANY]->(b:Company) RETURN a.name, b.name, r.support, r.evidence_sentences[0] ORDER BY r.support DESC LIMIT 20;",
]:
    para = doc.add_paragraph()
    run = para.add_run(q)
    run.font.name = "Consolas"
    run.font.size = Pt(9.5)
if gds and "error" not in gds:
    p(f"Chạy thử GDS trên Neo4j: Louvain tìm được {gds.get('louvain_communities')} cộng đồng "
      f"(modularity {gds.get('louvain_modularity', 0):.3f}). Top PageRank (có trọng số support):")
    p("Lưu ý khi so với mục 7: GDS chạy trên phép chiếu vô hướng giữ nguyên cạnh song song (hai thực thể có "
      "nhiều loại quan hệ được đếm nhiều lần trong bậc), PageRank có trọng số support và chưa chuẩn hóa (giá trị "
      "khởi đầu 0,15 mỗi nút); NetworkX ở mục 7 dùng đồ thị vô hướng đơn để tính bậc và Louvain, PageRank trên "
      "đồ thị có hướng không trọng số, chuẩn hóa tổng = 1. Louvain là thuật toán có yếu tố ngẫu nhiên và hai "
      "đầu vào khác nhau nên số cộng đồng lệch nhau một chút. Vì vậy số liệu hai mục không so trực tiếp được, "
      "chỉ thứ hạng là tương đồng.", italic=True)
    table(["Thực thể", "Loại", "PageRank", "Bậc"],
          [[x["name"], x["type"], x["pagerank"], x["degree"]] for x in gds.get("top_pagerank", [])[:12]],
          widths=[6, 3, 3, 2])
elif gds.get("error"):
    p("Ghi chú: chạy GDS gặp lỗi: " + gds["error"][:300])

# ================================================================ 7. THỐNG KÊ
h("7. Thống kê mạng đã xây dựng", 1)
table(["Chỉ số", "Giá trị"], [
    ["Số nút", fmt(st["nodes"])],
    ["Số cạnh (có hướng, có loại)", fmt(st["edges"])],
    ["Số loại quan hệ", st["relation_types"]],
    ["Số cạnh có support ≥ 2 bài báo", fmt(st["edges_support_ge2"])],
    ["Số cặp nút kề nhau (đồ thị vô hướng đơn)", fmt(st["undirected_simple_edges"])],
    ["Mật độ (vô hướng)", f"{st['density']:.5f}"],
    ["Bậc trung bình / bậc lớn nhất", f"{st['avg_degree']:.2f} / {st['max_degree']}"],
    ["Số thành phần liên thông", fmt(st["connected_components"])],
    ["Thành phần liên thông lớn nhất", f"{fmt(st['largest_component_nodes'])} nút ({st['largest_component_ratio']:.1%})"],
    ["Hệ số phân cụm trung bình", f"{st['avg_clustering']:.4f}"],
    ["Transitivity", f"{st['transitivity']:.4f}"],
    ["Độ dài đường đi ngắn nhất TB (TPLT lớn nhất, lấy mẫu 300 nút)", f"{st['avg_shortest_path_lcc_sampled']:.2f}"],
    ["Số cộng đồng Louvain (NetworkX) / modularity",
     f"{st.get('louvain_communities', '-')} / {st.get('louvain_modularity', 0):.3f}"],
], widths=[10, 6])
p("Vì lớp bài hát/album chiếm nhiều nút, nhóm thống kê riêng đồ thị lõi — phần phục vụ trực tiếp bài toán "
  "nghệ sĩ – công ty – nhãn hàng:")
table(["Đồ thị lõi (không gồm bài hát/album)", "Giá trị"], [
    ["Số nút có quan hệ lõi", fmt(st["core_nodes"])],
    ["  – theo loại", ", ".join(f"{k} {fmt(v)}" for k, v in st["core_node_types"].items())],
    ["Số cạnh lõi", fmt(st["core_edges"])],
    ["Số loại quan hệ lõi", len(st["core_edge_types"])],
    ["Lớp phụ: nút bài hát/album / cạnh nối tới lớp phụ", f"{fmt(st['work_nodes'])} / {fmt(st['work_edges'])}"],
], widths=[8, 8], size=10)
fig("node_types.png", "Hình 2. Số nút theo loại thực thể", 13)
fig("edge_types.png", "Hình 3. Số cạnh theo loại quan hệ (toàn bộ đồ thị)", 13)
fig("core_edge_types.png", "Hình 3b. Số cạnh theo loại quan hệ trong đồ thị lõi", 13)
fig("degree_distribution.png", "Hình 4. Phân bố bậc trên thang log–log", 12)
p("Phân bố bậc có đuôi dài: phần lớn nút có bậc nhỏ, một số ít nút (idol/nhóm/công ty lớn) có bậc rất cao, "
  "phù hợp với tính chất power-law thường gặp ở mạng xã hội. Đường đi ngắn nhất trung bình nhỏ so với kích "
  "thước mạng, thể hiện tính small-world.")
fig("edge_support.png", "Hình 5. Phân bố số bài báo dẫn chứng của mỗi cạnh", 12)
h("7.1. Các nút trung tâm", 2)
p("Bậc tính trên đồ thị vô hướng đơn, PageRank chuẩn hóa tổng = 1 (NetworkX), nên khác thang đo với bảng GDS ở "
  "mục 6.", italic=True)
table(["Top bậc", "Bậc", "Top PageRank", "PageRank"],
      [[a[0], a[1], b[0], b[1]] for a, b in zip(st["top_degree"][:12], st["top_pagerank"][:12])],
      widths=[5.5, 1.5, 6, 2], size=9.5)
table(["Nhãn hàng (bậc)", "Công ty (bậc)", "Nhóm nhạc (bậc)", "Nghệ sĩ (bậc)"],
      [[f"{x[0]} ({x[1]})" if x else "" for x in row] for row in zip(
          st["top_brand_by_degree"], st["top_company_by_degree"], st["top_group_by_degree"],
          st["top_artist_by_degree"])], widths=[4, 4, 4, 4], size=9.5)
fig("top60_subgraph.png", "Hình 6. Đồ thị lõi: 60 nút có bậc cao nhất (không gồm bài hát/album)", 16)

# ================================================================ 8. KẾT LUẬN
h("8. Đánh giá sơ bộ chất lượng", 1)
if qc:
    _all = qc["by_rel"]
    _n_all = sum(v["n"] for v in _all.values())
    _ok_all = sum(v["ok"] for v in _all.values())
    _excl = qc.get("excluded_from_graph", [])
    p(f"Lấy mẫu ngẫu nhiên phân tầng tối đa {max(v['n'] for v in _all.values())} cạnh cho mỗi loại quan hệ (loại có ít "
      f"cạnh hơn thì lấy toàn bộ), tổng {_n_all} cạnh (file data/graph/review_sample.csv). Mỗi cạnh được đánh giá "
      "đúng/sai bằng cách đọc câu dẫn chứng: cạnh đúng khi câu thể hiện đúng loại quan hệ, đúng hai thực thể và "
      "đúng chiều; cạnh sai được ghi lý do ở cột note (ví dụ: chủ thể là thành viên chứ không phải cả nhóm, tin đồn, "
      "ngữ cảnh phim ảnh, sai chiều). Với 30–35 mẫu mỗi loại, một cạnh chỉ ảnh hưởng khoảng 3% tới tỷ lệ của loại đó.")
    table(["Loại quan hệ", "Số mẫu", "Đúng", "Tỷ lệ", "Ghi chú"],
          [[k, v["n"], v["ok"], f"{v['ok'] / v['n']:.0%}", "Đã loại khỏi đồ thị" if k in _excl else ""]
           for k, v in sorted(_all.items(), key=lambda x: -x[1]["ok"] / x[1]["n"])], widths=[5.6, 1.7, 1.7, 1.7, 5.3], size=10)
    p(f"Trên toàn bộ {_n_all} mẫu (16 loại) tỷ lệ đúng là {_ok_all / _n_all:.1%}. LEGAL_ACTION chỉ đạt "
      f"{_all['LEGAL_ACTION']['ok']}/{_all['LEGAL_ACTION']['n']} "
      f"({_all['LEGAL_ACTION']['ok'] / _all['LEGAL_ACTION']['n']:.0%}): lỗi chủ yếu do từ 'kiện', 'tố cáo' xuất hiện "
      "trong câu kể nhiều bên (fan kiện, kiện người bôi nhọ nghệ sĩ, cựu CEO thay vì công ty), không đủ tin cậy để "
      "phục vụ mục tiêu theo dõi tranh chấp. Vì vậy nhóm loại LEGAL_ACTION khỏi đồ thị và điều chỉnh phát biểu ý "
      "nghĩa kinh doanh ở mục 2.1. "
      f"Trên {len(_all) - len(_excl)} loại còn lại: tỷ lệ đúng trên mẫu {qc['precision']:.1%}; quy đổi theo tỷ trọng "
      f"số cạnh thực tế của từng loại: {qc['weighted_precision']:.1%}.")
    p("Các loại còn yếu là COLLABORATED_WITH, ACQUIRED_STAKE và DEBUTED_UNDER (khoảng 40–51%). Chúng vẫn được giữ "
      "vì gắn trực tiếp với mô tả đề tài (Ra mắt, Hợp tác toàn cầu) và cấu trúc sở hữu tập đoàn, nhưng cần được "
      "ưu tiên cải thiện. Đây là kiểm tra sơ bộ; theo đề bài, chỉ tiêu chất lượng ≥ 90% sẽ được đánh giá ở bài tập "
      "cuối kỳ.")
else:
    p("Chưa thực hiện đánh giá độ chính xác có gán nhãn ở đợt nộp này (theo đề bài, chỉ tiêu ≥ 90% đánh giá ở "
      "bài tập cuối kỳ).")

h("9. Kết luận", 1)
h("9.1. Đã đạt được", 2)
ok_nodes = st["nodes"] >= 2000
ok_edges = st["edges"] >= 5000
ok_rel = st["relation_types"] >= 10
for s in [
    f"Mạng gồm {fmt(st['nodes'])} nút ({'đạt' if ok_nodes else 'CHƯA đạt'} chỉ tiêu 2.000), "
    f"{fmt(st['edges'])} cạnh ({'đạt' if ok_edges else 'CHƯA đạt'} chỉ tiêu 5.000) và "
    f"{st['relation_types']} loại quan hệ ({'đạt' if ok_rel else 'CHƯA đạt'} chỉ tiêu 10).",
    "Toàn bộ cạnh có dẫn chứng là câu văn và URL bài báo, truy vết được nguồn gốc.",
    "Dữ liệu song ngữ Việt – Anh từ 5 trang báo, pipeline tự động hoàn toàn và chạy lại được.",
    "Đồ thị lưu trên Neo4j, đã chạy thử thuật toán PageRank, Louvain, Degree bằng GDS.",
    f"Đánh giá chất lượng trên mẫu {sum(v['n'] for v in qc['by_rel'].values())} cạnh; loại bỏ quan hệ không đủ tin cậy "
    "(LEGAL_ACTION) thay vì giữ để tăng số lượng." if qc else "",
]:
    if s:
        bullet(s)
h("9.2. Chưa đạt / hạn chế", 2)
for s in [
    f"Độ chính xác ước lượng {qc['precision']:.1%} trên mẫu ({qc['weighted_precision']:.1%} theo tỷ trọng cạnh), chưa đạt "
    "mức ≥ 90%; COLLABORATED_WITH, ACQUIRED_STAKE, DEBUTED_UNDER còn yếu. Chưa đo recall." if qc else "",
    f"Lớp lõi nghệ sĩ – công ty – nhãn hàng mới có {fmt(st['core_nodes'])} nút và {fmt(st['core_edges'])} cạnh; chỉ "
    "tiêu 2.000 nút/5.000 cạnh đạt được nhờ lớp phụ bài hát/album. Số nhãn hàng và công ty còn ít so với thực tế.",
    "Chưa theo dõi được tranh chấp pháp lý (LEGAL_ACTION bị loại do độ chính xác thấp).",
    "Trích xuất quan hệ bằng luật nên bỏ sót các câu diễn đạt gián tiếp và có thể gán sai chiều ở câu phức nhiều thực thể.",
    "NER phụ thuộc từ điển: nghệ sĩ mới/ít nổi tiếng chưa có trong Wikidata sẽ không được nhận dạng; tên ngắn dễ nhập nhằng (V, Jin, Joy…).",
    "Đồng tham chiếu mới ở mức luật đơn giản (đại từ đầu câu → nhân vật trong tiêu đề); các trường hợp phức tạp hơn "
    "(nhóm, nam ca sĩ ở giữa câu, nhiều nhân vật) chưa được khai thác.",
    "Quan hệ có tính thời điểm (ký/rời hợp đồng) mới chỉ lưu ngày bài báo, chưa chuẩn hóa thời gian hiệu lực.",
]:
    if s:
        bullet(s)
h("9.3. Hướng phát triển cho bài cuối kỳ", 2)
for s in [
    "Mở rộng lớp lõi: thêm nhãn hàng/công ty vào từ điển, tăng độ phủ cho quan hệ đại sứ và hợp đồng.",
    "Viết lại luật LEGAL_ACTION (xác định đúng bên kiện/bị kiện, loại câu kể gián tiếp) rồi đánh giá lại trước khi đưa vào đồ thị.",
    "Dùng các cạnh đã gán nhãn (data/graph/review_sample.csv) làm dữ liệu huấn luyện mô hình phân loại quan hệ (PhoBERT/XLM-R).",
    "Dùng LLM miễn phí (ví dụ Gemini free tier) để kiểm chứng lại các cạnh support = 1.",
    "Bổ sung đồng tham chiếu và chuẩn hóa thực thể mới (entity linking).",
    "Phân tích cộng đồng, dự đoán liên kết (idol – nhãn hàng), xếp hạng người ảnh hưởng.",
]:
    if s:
        bullet(s)

h("10. Mã nguồn", 1)
p(f"Link GitHub: {GITHUB_URL}")
p("Kho mã gồm toàn bộ script pipeline (src/), danh sách thực thể thủ công (config/), từ điển thực thể, danh "
  "sách URL, bộ ba quan hệ kèm dẫn chứng, nodes.csv/edges.csv, thống kê và mã sinh báo cáo. Nội dung đầy đủ "
  "của bài báo không được đưa lên kho để tôn trọng bản quyền của các tòa soạn.")

json.dump(HEADINGS, open(ROOT / "report" / "headings.json", "w", encoding="utf-8"), ensure_ascii=False)
out = ROOT / "report" / "BaoCao_DeTai24_Nhom22.docx"
doc.save(out)
print("Đã lưu", out)
