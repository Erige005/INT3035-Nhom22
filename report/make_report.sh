#!/bin/sh
# Sinh báo cáo .docx và .pdf (2 lượt để mục lục có số trang đúng)
set -e
cd "$(dirname "$0")/.."
SOFFICE=${SOFFICE:-/Applications/LibreOffice.app/Contents/MacOS/soffice}
rm -f report/toc_pages.json
.venv/bin/python report/build_report.py
"$SOFFICE" --headless --convert-to pdf --outdir report report/BaoCao_DeTai24_Nhom22.docx >/dev/null
.venv/bin/python report/toc_pages.py
.venv/bin/python report/build_report.py
"$SOFFICE" --headless --convert-to pdf --outdir report report/BaoCao_DeTai24_Nhom22.docx >/dev/null
.venv/bin/python report/toc_pages.py
