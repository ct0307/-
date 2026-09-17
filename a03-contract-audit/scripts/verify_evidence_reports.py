"""只读真实测试库，生成本地验收样例并核对 Excel／Word 与快照一致。"""
import argparse
import json
import sys
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from docx import Document
from openpyxl import load_workbook
from app.db.session import SessionLocal, engine
from app.services.report.exporter import build_report_snapshot, export_report_docx, export_report_xlsx


def main():
    engine.echo = False
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ids", type=int, nargs="+", required=True)
    args = parser.parse_args()
    target = ROOT / "outputs/evidence-report-acceptance"
    target.mkdir(parents=True, exist_ok=True)
    evidence = []
    with SessionLocal() as db:
        for label, ids in [("single", args.ids[:1]), ("selected", args.ids)]:
            snapshot = build_report_snapshot(db, ids)
            xlsx = export_report_xlsx(snapshot)
            docx = export_report_docx(snapshot)
            workbook = load_workbook(BytesIO(xlsx))
            document = Document(BytesIO(docx))
            assert [row[0].value for row in workbook["合同清单"].iter_rows(min_row=2)] == snapshot["contract_ids"]
            assert workbook["摘要"]["B4"].value == len(snapshot["contract_ids"])
            assert workbook["摘要"]["B10"].value == len(snapshot["risks"])
            text = "\n".join(p.text for p in document.paragraphs)
            assert snapshot["report_id"][:20] in text
            assert all(f"R{risk['id']} ·" in text for risk in snapshot["risks"])
            (target / f"{label}.xlsx").write_bytes(xlsx)
            (target / f"{label}.docx").write_bytes(docx)
            (target / f"{label}.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
            evidence.append({"sample": label, "ids": snapshot["contract_ids"], "summary": snapshot["summary"], "report_id": snapshot["report_id"], "sheets": workbook.sheetnames, "word_risks_verified": len(snapshot["risks"])})
    (target / "verification.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    browser_xlsx, browser_docx = target / "browser-selected.xlsx", target / "browser-selected.docx"
    if browser_xlsx.exists() and browser_docx.exists():
        workbook = load_workbook(browser_xlsx)
        document = Document(browser_docx)
        assert [row[0].value for row in workbook["合同清单"].iter_rows(min_row=2)] == snapshot["contract_ids"]
        assert workbook["摘要"]["B10"].value == len(snapshot["risks"])
        assert sum(p.text.startswith("R") and " · " in p.text for p in document.paragraphs) == len(snapshot["risks"])
        print("浏览器下载的Excel与Word回读一致")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
