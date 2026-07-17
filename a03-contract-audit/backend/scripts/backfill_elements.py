"""批量回填合同要素：对已上传但要素为空的合同重跑 LLM 精抽，写入 elements_json。

用法（在 backend/ 目录下）：
    ./.venv/Scripts/python.exe -m scripts.backfill_elements

幂等：有 party_a 或 subject 的合同跳过，不重复消耗 token。
"""
import json
import os
import sys
import time
from pathlib import Path

# 固定工作目录为 backend/，保证 storage/ 相对路径能解析
_BACKEND_DIR = Path(__file__).resolve().parent.parent
os.chdir(_BACKEND_DIR)
sys.path.insert(0, str(_BACKEND_DIR))

from app.db.session import SessionLocal
from app.models.models import Contract
from app.services.parser.extractor import extract_elements_with_llm, extract_text


def _needs_backfill(contract: Contract) -> bool:
    """判断合同是否需要回填：elements_json 里缺失三要素之一则回填。"""
    try:
        d = json.loads(contract.elements_json or "{}")
        return not any(d.get(k) for k in ("party_a", "subject", "payment_terms"))
    except (ValueError, AttributeError):
        return True


def main() -> None:
    db = SessionLocal()
    try:
        contracts = db.query(Contract).order_by(Contract.id).all()
        need = [c for c in contracts if _needs_backfill(c)]
        skip = len(contracts) - len(need)
        print(f"合同总数: {len(contracts)}  跳过(已有要素): {skip}  待回填: {len(need)}")

        ok = fail = 0
        for c in need:
            print(f"  [{c.id:3}] {c.filename[:40]:40} ", end="", flush=True)
            try:
                text = extract_text(c.storage_path)
                elements = extract_elements_with_llm(text)
                # 只持久化字符串字段（text_length/has_* 为非字符串，不写 db）
                c.elements_json = json.dumps(
                    {k: v for k, v in elements.items() if isinstance(v, (str, type(None)))},
                    ensure_ascii=False,
                )
                db.commit()
                filled = [k for k in ("party_a", "subject", "payment_terms") if elements.get(k)]
                print(f"[OK]  filled={filled}")
                ok += 1
            except Exception as exc:
                db.rollback()
                print(f"[FAIL] {exc}")
                fail += 1
            time.sleep(0.3)  # 避免 LLM 调用过快触发限流

        print(f"\n回填完成: 成功 {ok}  失败 {fail}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
