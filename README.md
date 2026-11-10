# INT3035 – Nhóm 22 – Đề tài 24

**Mạng lưới ngôi sao âm nhạc, thần tượng K-Pop/US-UK và tập đoàn giải trí quốc tế, xây dựng từ dữ liệu báo chí bằng NLP**

Học phần *Phân tích mạng phương tiện xã hội trong kinh doanh* (INT3035), Trường Đại học Công nghệ – ĐHQGHN.
Nhóm 22: Nguyễn Nhật Nam (23020557), Lưu Đạt Tuấn Nghĩa (23020559).

## Tổng quan

Pipeline lấy tin tức âm nhạc quốc tế/K-pop từ 5 trang báo, nhận dạng thực thể và trích xuất quan hệ bằng luật NLP song ngữ Việt–Anh, rồi lưu đồ thị vào Neo4j.

- **Nguồn báo:** Kênh14, Thanh Niên, Tuổi Trẻ, Znews (tiếng Việt) và Soompi (tiếng Anh). Chỉ thu thập các trang có robots.txt cho phép.
- **Nút (8 loại):** Artist, Group, Company, Brand, Award, Event, Song, Album.
- **Cạnh (16 loại):** MEMBER_OF, DEBUTED_UNDER, SIGNED_WITH, RENEWED_CONTRACT, LEFT_COMPANY, LEFT_GROUP, LEGAL_ACTION, COLLABORATED_WITH, BRAND_AMBASSADOR, RELEASED, WON_AWARD, NOMINATED_FOR, PERFORMED_AT, SUBSIDIARY_OF, ACQUIRED_STAKE, PRODUCED_FOR.
- Mỗi cạnh có `support` (số bài báo dẫn chứng) và tối đa 3 câu dẫn chứng kèm URL. Bài báo và câu văn **không** được tính là nút hay cạnh.
- Wikidata chỉ được dùng làm **từ điển tên thực thể** cho bước NER, không dùng để tạo cạnh.

### Kết quả (đợt nộp 11/2026)

| Chỉ số | Giá trị |
| --- | --- |
| Bài báo xử lý | 33.118 (22.484 tiếng Việt, 10.634 tiếng Anh) |
| Nút | 4.423 (976 nghệ sĩ, 293 nhóm, 85 công ty, 57 nhãn hàng, 25 giải thưởng, 39 sự kiện, 1.793 bài hát, 1.155 album) |
| Cạnh | 5.778 (2.323 cạnh có ≥ 2 bài báo dẫn chứng) |
| Loại quan hệ | 16 |
| Độ chính xác sơ bộ | 76,2% trên mẫu phân tầng 160 cạnh; 84,0% khi quy đổi theo tỷ trọng cạnh (`data/graph/quality_check.json`) |

Số liệu đầy đủ: `data/graph/summary.json`, `data/graph/stats.json`, `data/graph/neo4j_gds.json`.

## Cấu trúc thư mục

```
config/manual_entities.json   Nhãn hàng, giải thưởng, sự kiện, công ty bổ sung thủ công
src/common.py                 Đường dẫn, hàm tiện ích
src/build_gazetteer.py        B1  Dựng từ điển thực thể (Wikidata SPARQL + thủ công)
src/gazetteer_supplement.py   B1b Bổ sung ca sĩ Hàn, nghệ sĩ/nhóm khai báo thủ công
src/collect_urls.py           B2  Lấy URL bài báo từ sitemap, lọc theo slug
src/fetch_articles.py         B3  Tải và bóc tách bài báo
src/extract.py                B4–5 Tiền xử lý, NER, trích xuất quan hệ
src/build_graph.py            B6  Gộp cạnh, tính support → nodes.csv / edges.csv
src/load_neo4j.py             B7  Nạp Neo4j, chạy PageRank / Louvain / Degree (GDS)
src/stats.py                  B8  Thống kê mạng và biểu đồ
src/review_sample.py          B9  Lấy mẫu cạnh và tính độ chính xác sơ bộ
report/make_report.sh         Sinh báo cáo .docx + .pdf (cần LibreOffice, poppler)
data/gazetteer/               Từ điển thực thể
data/raw/urls.jsonl           Danh sách URL bài báo (không kèm toàn văn bài báo)
data/processed/               Thống kê tiền xử lý (relations.jsonl tạo lại bằng extract.py)
data/graph/                   nodes.csv, edges.csv, evidence, thống kê, hình
```

Toàn văn bài báo (`data/raw/articles.jsonl`) **không** được đưa lên repo, để tôn trọng bản quyền của các tòa soạn. Chạy lại bước 3 để tải lại.

## Cách chạy

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# Neo4j: brew install neo4j; bật plugin GDS + APOC; tạo file .env:
#   NEO4J_URI=bolt://localhost:7687
#   NEO4J_USER=neo4j
#   NEO4J_PASSWORD=...
cd src
../.venv/bin/python build_gazetteer.py
../.venv/bin/python gazetteer_supplement.py
../.venv/bin/python collect_urls.py --start 2023-07-01 --end 2026-11-10
../.venv/bin/python fetch_articles.py
../.venv/bin/python extract.py
../.venv/bin/python build_graph.py
../.venv/bin/python load_neo4j.py
../.venv/bin/python stats.py
../.venv/bin/python review_sample.py score
cd .. && sh report/make_report.sh
```

## Ví dụ truy vấn Cypher

```cypher
// Nhãn hàng có nhiều đại sứ nhất
MATCH (a)-[:BRAND_AMBASSADOR]->(b:Brand) RETURN b.name, count(a) AS n ORDER BY n DESC LIMIT 10;
// Tranh chấp pháp lý kèm câu dẫn chứng
MATCH (a)-[r:LEGAL_ACTION]->(b) RETURN a.name, b.name, r.support, r.evidence_sentences[0] ORDER BY r.support DESC;
```

## Hạn chế

Hệ thống trích xuất quan hệ bằng luật nên có thể bỏ sót hoặc gán sai chiều ở câu phức. Độ chính xác hiện chưa đạt mức ≥ 90%; các quan hệ yếu nhất là LEGAL_ACTION, COLLABORATED_WITH và ACQUIRED_STAKE. Nút tác phẩm (bài hát/album) chiếm khoảng 67% số nút.
