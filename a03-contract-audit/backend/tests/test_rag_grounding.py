import unittest
from unittest.mock import patch

from app.services.audit import auditor


def _risk(category: str, original_text: str, basis: str = "模型自报依据") -> dict:
    return {
        "agent": "legal",
        "level": "medium",
        "category": category,
        "original_text": original_text,
        "basis": basis,
        "suggestion": "修改建议",
        "confidence": 88,
    }


class RagGroundingTests(unittest.TestCase):
    def test_supported_low_risk_can_enter_green_tier(self):
        risk = _risk("一般提示", "合同原文")
        risk.update({
            "level": "low",
            "confidence": 10,
            "evidence_status": "supported",
            "original_text_verified": True,
        })

        self.assertEqual(auditor.classify_tier(risk), "green")

    def test_unsupported_low_risk_never_enters_green_tier(self):
        risk = _risk("一般提示", "合同原文")
        risk.update({
            "level": "low",
            "confidence": 99,
            "evidence_status": "unsupported",
            "original_text_verified": False,
        })

        self.assertEqual(auditor.classify_tier(risk), "yellow")

    def test_selected_dimension_skips_unrelated_agent(self):
        with patch.object(auditor, "_agent_audit", return_value=[]) as agent_audit:
            auditor.audit_contract({}, "合同正文", dimensions=["payment"])

        called_roles = [call.args[0] for call in agent_audit.call_args_list]
        self.assertEqual(called_roles, ["finance"])

    def test_each_risk_gets_its_own_sources(self):
        calls = []

        def fake_retrieve(query, **kwargs):
            calls.append((query, kwargs))
            return [{
                "chunk_id": len(calls),
                "content": query,
                "source": f"法规{len(calls)}",
                "article_number": f"第{len(calls)}条",
                "score": 0.8,
                "reliable": True,
            }]

        risks = [_risk("违约责任", "违约金为50%"), _risk("争议解决", "由甲方所在地法院管辖")]
        with patch.object(auditor, "retrieve", side_effect=fake_retrieve):
            grounded = auditor._ground_risks(
                risks, contract_type="采购合同", dimensions=["breach", "dispute"]
            )

        self.assertEqual(len(calls), 2)
        self.assertNotEqual(grounded[0]["rag_sources"], grounded[1]["rag_sources"])
        self.assertEqual(grounded[0]["basis"], "法规1 第1条")
        self.assertEqual(grounded[1]["basis"], "法规2 第2条")
        self.assertEqual(calls[0][1]["contract_type"], "采购合同")
        self.assertEqual(calls[0][1]["dimensions"], ["breach", "dispute"])

    def test_verified_original_with_retrieved_source_still_requires_support_review(self):
        risks = [_risk("违约责任", "违约金为50%")]

        with patch.object(auditor, "retrieve", return_value=[{
            "content": "约定违约金过高时可以适当减少。",
            "source": "民法典",
            "article_number": "第五百八十五条",
            "score": 0.9,
            "reliable": True,
        }]):
            grounded = auditor._ground_risks(
                risks,
                contract_text="合同约定：违约金为50%。",
            )

        self.assertTrue(grounded[0]["original_text_verified"])
        self.assertEqual(grounded[0]["support_relation_status"], "supported")
        self.assertEqual(grounded[0]["evidence_status"], "supported")
        self.assertFalse(grounded[0]["requires_manual_review"])

    def test_unverified_original_is_partial_and_requires_review(self):
        risks = [_risk("违约责任", "合同没有出现的原文")]

        with patch.object(auditor, "retrieve", return_value=[{
            "content": "企业规则要求明确违约责任。",
            "source": "合同模板规则",
            "score": 0.8,
            "reliable": True,
        }]):
            grounded = auditor._ground_risks(
                risks,
                contract_text="合同正文没有该条款。",
            )

        self.assertFalse(grounded[0]["original_text_verified"])
        self.assertEqual(grounded[0]["support_relation_status"], "unclear")
        self.assertEqual(grounded[0]["evidence_status"], "partially_supported")
        self.assertTrue(grounded[0]["requires_manual_review"])

    def test_unverified_basis_is_replaced_and_requires_review(self):
        risks = [_risk("违约责任", "未约定违约责任", basis="《民法典》第9999条")]

        with patch.object(auditor, "retrieve", return_value=[]):
            grounded = auditor._ground_risks(risks)

        self.assertEqual(grounded[0]["basis"], auditor.NO_RELIABLE_BASIS)
        self.assertEqual(grounded[0]["rag_sources"], [])
        self.assertEqual(grounded[0]["support_relation_status"], "unclear")
        self.assertLessEqual(grounded[0]["confidence"], 50)
        self.assertTrue(grounded[0]["requires_manual_review"])

    def test_source_without_reliable_flag_requires_manual_review(self):
        risks = [_risk("payment", "payment within 30 days")]
        source = {
            "chunk_id": 1,
            "content": "payment reference",
            "source": "legacy source",
            "score": 0.9,
        }

        with patch.object(auditor, "retrieve", return_value=[source]):
            grounded = auditor._ground_risks(risks)

        self.assertEqual(grounded[0]["basis"], auditor.NO_RELIABLE_BASIS)
        self.assertEqual(grounded[0]["rag_sources"], [])
        self.assertLessEqual(grounded[0]["confidence"], 50)
        self.assertTrue(grounded[0]["requires_manual_review"])


if __name__ == "__main__":
    unittest.main()
