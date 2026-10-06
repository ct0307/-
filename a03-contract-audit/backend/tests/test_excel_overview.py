"""报表总览在未审查、空范围及有风险时不得产生误导。"""
from io import BytesIO
from openpyxl import load_workbook
import pytest
from app.services.report.renderers import export_report_xlsx


@pytest.mark.parametrize('total,unreviewed,risks,expected', [
    (0, 0, 0, '无合同可供评阅'),
    (1, 1, 0, '1份合同尚未审查'),
    (1, 0, 0, '当前范围暂无风险记录'),
    (1, 0, 6, '高6 / 中0 / 低0'),
])
def test_overview_explains_scope_and_preserves_snapshot(total, unreviewed, risks, expected):
    snapshot = {'report_id': 'a' * 64, 'generated_at': '2026-10-02T11:00:00+00:00',
        'summary': dict(total=total, completed=0, review_required=total-unreviewed,
                        failed=0, unreviewed=unreviewed, running=0,
                        risks=risks, high=risks, medium=0, low=0, supported=0),
        'contracts': [], 'risks': [], 'rectifications': [],
        'matrix': {'categories': [], 'rows': []}, 'notes': []}
    wb = load_workbook(BytesIO(export_report_xlsx(snapshot)))
    ws = wb['摘要']
    text = '\n'.join(str(c.value) for row in ws for c in row if c.value is not None)
    assert expected in text
    assert '2026-10-02 19:00' in text
    assert snapshot['report_id'] in text
    assert f'共{risks}条风险记录' in text
    assert ws['E40'].hyperlink.target == "#'风险详情'!A1"
    assert not ws._charts  # 无全零空图或“系列1”默认标签。
    assert len(wb.sheetnames) == 10
