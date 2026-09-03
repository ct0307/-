"""参赛材料语言与重复度审计的行为测试。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

try:
    import audit_materials
except ModuleNotFoundError:
    audit_materials = None


class AuditMaterialsTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(audit_materials, "audit_materials.py 尚未实现")
        return audit_materials

    def test_rejects_level_four_heading(self):
        findings = self.module().find_level_four_headings(
            "# 第一章\n## 1.1 节\n### 1.1.1 小节\n#### 1.1.1.1 过深标题"
        )

        self.assertEqual(findings, ["#### 1.1.1.1 过深标题"])

    def test_rejects_common_chinese_and_english_placeholders(self):
        text = "\n".join(
            [
                "此处插入最终截图",
                "负责人：待填写",
                "结论：待补充",
                "TODO: replace figure",
                "TBD",
                "[PLACEHOLDER]",
            ]
        )

        findings = self.module().find_placeholders(text)

        self.assertEqual(len(findings), 6)

    def test_does_not_treat_verification_status_as_placeholder(self):
        findings = self.module().find_placeholders(
            "50+2 批量机制已实现，待真实环境验证；OCR 指标仍待实测。"
        )

        self.assertEqual(findings, [])

    def test_rejects_promotional_phrases(self):
        text = "全面赋能、颠覆性创新、革命性突破、行业绝对领先、完全替代人工"

        findings = self.module().find_promotional_phrases(text)

        self.assertEqual(
            findings,
            ["全面赋能", "颠覆性创新", "革命性突破", "行业绝对领先", "完全替代人工"],
        )

    def test_allows_domain_specific_closure_term(self):
        self.assertEqual(
            self.module().find_promotional_phrases("风险整改闭环保留处理记录"),
            [],
        )

    def test_rejects_repeated_long_paragraph(self):
        detail = "合同审查人员需要查看原文并核对依据。" * 12

        findings = self.module().audit_similarity(
            detail,
            detail,
            minimum_length=80,
            threshold=0.80,
        )

        self.assertTrue(findings)
        self.assertGreaterEqual(findings[0].ratio, 0.80)

    def test_ignores_repeated_short_paragraph(self):
        paragraph = "模型负责辅助阅读，人负责最终决定。"

        findings = self.module().audit_similarity(
            paragraph,
            paragraph,
            minimum_length=80,
            threshold=0.80,
        )

        self.assertEqual(findings, [])

    def test_command_accepts_explicit_material_paths(self):
        chapter_numbers = "一二三四五六七"
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            detail_dir = root / "detail"
            detail_dir.mkdir()
            for index, number in enumerate(chapter_numbers, start=1):
                (detail_dir / f"{index:02d}-chapter.md").write_text(
                    f"# 第{number}章 测试章节\n\n本章记录合同审查事实。",
                    encoding="utf-8",
                )
            overview = root / "overview.md"
            overview.write_text(
                "\n\n".join(f"# PAGE: 第 {index} 页\n\n页面说明。" for index in range(1, 10)),
                encoding="utf-8",
            )

            output = StringIO()
            with redirect_stdout(output):
                try:
                    exit_code = self.module().main(
                        [
                            "--detail-dir",
                            str(detail_dir),
                            "--overview",
                            str(overview),
                        ]
                    )
                except TypeError as exc:
                    self.fail(f"命令入口尚不支持显式参数：{exc}")

        self.assertEqual(exit_code, 0)
        self.assertIn("PASS detail_chapters=7 overview_pages=9", output.getvalue())


if __name__ == "__main__":
    unittest.main()
