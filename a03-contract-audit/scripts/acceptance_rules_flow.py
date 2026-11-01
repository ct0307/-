"""使用全新临时目录验收真实 API 规则流程；不加载项目 .env，不调用外部模型。"""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import time
from zipfile import ZipFile
from io import BytesIO


def main() -> None:
    backend = Path(__file__).resolve().parents[1] / "backend"
    # 必须先隔离工作目录，Settings 才不会加载项目中的真实 .env。
    isolated = Path(tempfile.mkdtemp(prefix="qijian-rules-acceptance-"))
    os.chdir(isolated)
    os.environ.update({
        "APP_ENV": "dev", "DEBUG": "false", "DB_BACKEND": "sqlite",
        "SQLITE_PATH": str(isolated / "acceptance.db"),
        "STORAGE_DIR": str(isolated / "storage"),
        "MODEL_PROCESSING_MODE": "rules_fallback", "AUDIT_ASYNC": "false",
        "LLM_API_KEY": "", "LLM_BASE_URL": "", "FILE_ENCRYPT_KEY": "",
        "MODEL_EXTERNAL_ALLOWED_BASE_URLS": "[]", "JWT_SECRET": secrets.token_hex(32),
    })
    sys.path.insert(0, str(backend))
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db.session import SessionLocal, engine
    from app.models.models import User
    from app.core.security import hash_password

    checks: list[str] = []
    password = secrets.token_urlsafe(24)

    with TestClient(app) as client:
        with SessionLocal() as db:
            db.add(User(username="acceptance", password_hash=hash_password(password),
                        role="admin", department="验收部"))
            db.commit()

        def request(method: str, path: str, expected: int = 200, **kwargs):
            response = client.request(method, "/api/v1" + path, **kwargs)
            assert response.status_code == expected, (path, response.status_code, response.text[:1000])
            return response

        request("GET", "/contracts", expected=401)
        token = request("POST", "/auth/login", data={"username": "acceptance", "password": password}).json()
        client.headers["Authorization"] = "Bearer " + token["access_token"]
        checks.append("未登录拒绝与真实密码登录")
        sample = ("合成验收样本，仅用于测试。\n软件开发外包合同\n甲方：样例科技有限公司\n"
                  "乙方：示例软件有限公司\n第一条 合同标的：开发采购管理系统，交付源代码和技术文档。\n"
                  "第二条 合同价款：总价人民币100000元，签约后支付全部价款。\n"
                  "第三条 验收：乙方提交成果后由甲方验收，但未约定验收期限与标准。\n"
                  "第四条 违约责任：乙方不承担任何违约责任，甲方不得解除合同。\n"
                  "第五条 争议解决：双方协商解决。\n第六条 知识产权由双方另行协商。\n")
        upload = dict(files=[("files", ("合成验收.txt", sample.encode("utf-8"), "text/plain"))],
                      data={"department": "验收部"}, headers={"Idempotency-Key": "acceptance-import-0001"})
        batch = request("POST", "/imports", expected=202, **upload).json()
        duplicate = request("POST", "/imports", expected=202, **upload).json()
        assert duplicate["id"] == batch["id"]
        deadline = time.monotonic() + 90
        while True:
            batch = request("GET", f"/imports/{batch['id']}").json()
            item = batch["items"][0]
            if item["status"] not in {"queued", "parsing"}:
                break
            assert time.monotonic() < deadline, "导入超时"
            time.sleep(0.2)
        assert item["status"] in {"ready", "awaiting_confirmation"}, item
        item = request("PATCH", f"/imports/{batch['id']}/items/{item['id']}",
                       json={"contract_type": "软件开发外包合同", "department": "验收部"}).json()
        assert item["status"] == "ready"
        contract_id = item["contract_id"]
        checks.append("真实上传、异步解析、重复上传幂等与人工类型确认")
        request("POST", f"/contracts/{contract_id}/audit", json={"contract_type": "软件开发外包合同"},
                headers={"Idempotency-Key": "acceptance-audit-0001"})
        deadline = time.monotonic() + 120
        while True:
            result = request("GET", f"/contracts/{contract_id}/audit-status").json()
            if result["status"] in {"done", "review_required", "audit_failed"}:
                break
            assert time.monotonic() < deadline, "审查超时"
            time.sleep(0.2)
        # 当前规则模式只禁用模型出站，尚未实现独立规则审查闭环。
        # 本验收要求其明确失败，不能用空结果伪装审查成功。
        assert result["status"] == "audit_failed", result
        assert result["error_code"] == "INVALID_MODEL_OUTPUT", result
        assert result["coverage"]["completed"] < result["coverage"]["planned"], result
        checks.append("规则模式审查失败明确可见，未伪装完整模型覆盖")
        risk_data = request("GET", f"/contracts/{contract_id}/risks").json()
        risks = risk_data if isinstance(risk_data, list) else risk_data["risks"]
        view = request("GET", f"/workflows/{contract_id}").json()
        assert view["can_finalize"] is False

        def final_payload(current):
            return {"expected_generation": current.get("generation", 0), "expected_version": current.get("version", 0),
                    "review_fingerprint": current.get("review_fingerprint", "0" * 64),
                    "comment": "合成样本流程验收，不构成真实法律意见", "quality_comment": "已核对合成文本",
                    "conflict_resolutions": {c["id"]: "合成样本人工流程验收记录" for c in current["conflicts"]}}

        request("POST", f"/workflows/{contract_id}/finalize", expected=409, json=final_payload(view))
        checks.append("失败审查不能终审发布")
        snapshot = request("POST", "/reports/preview", json={"contract_ids": [contract_id]}).json()
        for extension in ("docx", "xlsx"):
            response = request("GET", "/reports/export", params={"contract_ids": contract_id,
                               "format": extension, "report_id": snapshot["report_id"]})
            with ZipFile(BytesIO(response.content)) as archive:
                assert archive.testzip() is None
                assert "[Content_Types].xml" in archive.namelist()
        checks.append("真实证据报告预览、DOCX/XLSX 导出及容器完整性")
    engine.dispose()
    print(json.dumps({"status": "passed", "mode": "rules_fallback", "checks": checks,
                      "risk_count": len(risks), "artifacts": str(isolated),
                      "limits": "仅验证失败保护路径；未验收成功审查闭环、真实模型、OCR、PostgreSQL、Redis/Celery 或浏览器交互"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
