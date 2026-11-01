"""调用当前生产检索生成可追溯预测；不生成金标或改写失败案例。"""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path

from evaluation.retrieval_metrics import evaluate_retrieval_dataset


def evidence_key(source: dict) -> str:
    if source.get("source_id") and source.get("article_number"):
        return f"{source['source_id']}:{source['article_number']}"
    if source.get("chunk_id") is not None:
        return f"chunk:{source['chunk_id']}"
    return ""


def predict(records: list[dict], *, retriever, top_k: int) -> list[dict]:
    if not records or not 1 <= top_k <= 100:
        raise ValueError("案例不能为空，top_k 应为 1 到 100")
    seen = set()
    for record in records:
        case_id = record.get("case_id")
        if not isinstance(case_id, str) or not case_id.strip() or case_id in seen:
            raise ValueError("case_id 必须为非空且唯一的字符串")
        if not isinstance(record.get("query"), str) or not record["query"].strip():
            raise ValueError(f"{case_id}: 缺少 query")
        if record.get("as_of"):
            date.fromisoformat(record["as_of"])
        seen.add(case_id)
    predictions = []
    for record in records:
        row = {"case_id": record["case_id"], "ranked_ids": [], "retrieval_modes": [], "error_code": None}
        try:
            sources = retriever(record["query"], top_k=top_k,
                                contract_type=record.get("contract_type", ""),
                                dimensions=record.get("dimensions", []),
                                as_of=date.fromisoformat(record["as_of"]) if record.get("as_of") else None)
            row["ranked_ids"] = list(dict.fromkeys(key for source in sources if (key := evidence_key(source))))[:top_k]
            row["retrieval_modes"] = sorted({str(source.get("retrieval_mode", "unknown")) for source in sources})
        except Exception as exc:
            # 仅保存异常类型，不把查询、合同正文或地址写入评测产物。
            row["error_code"] = type(exc).__name__
        predictions.append(row)
    return predictions


def knowledge_identity() -> dict:
    from app.db.session import SessionLocal
    from app.services.rag.retriever import _load_docs_from_session
    from app.services.rag.revision import current_knowledge_revision

    with SessionLocal() as db:
        docs = _load_docs_from_session(db)
        payload = json.dumps([list(row) for row in sorted(docs, key=lambda row: row[0])], ensure_ascii=False, default=str)
        return {"revision": current_knowledge_revision(db), "content_sha256": hashlib.sha256(payload.encode()).hexdigest()}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="生成当前检索预测并评测，知识库仅只读")
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--min-recall", type=float, default=0.9)
    args = parser.parse_args(argv)
    if not 0 <= args.min_recall <= 1:
        raise ValueError("min-recall 应在 0 到 1 之间")
    raw = args.gold.read_bytes()
    records = [json.loads(line) for line in raw.decode("utf-8-sig").splitlines() if line.strip()]
    evaluate_retrieval_dataset(records, {}, k_values=(args.k,))
    from app.core.config import settings
    from app.services.rag.retriever import retrieve

    before = knowledge_identity()
    predictions = predict(records, retriever=retrieve, top_k=args.k)
    if knowledge_identity() != before:
        raise ValueError("评测期间知识库发生变化，请冻结知识库后重跑")
    report = evaluate_retrieval_dataset(records, {row["case_id"]: row["ranked_ids"] for row in predictions}, k_values=(args.k,))
    backend = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for path in sorted([*backend.joinpath("app").rglob("*.py"), *backend.joinpath("evaluation").glob("*.py")]):
        digest.update(path.relative_to(backend).as_posix().encode())
        digest.update(path.read_bytes())
    identity = {"code_sha256": digest.hexdigest(), "knowledge": before,
                "gold_sha256": hashlib.sha256(raw).hexdigest(), "top_k": args.k,
                "min_recall": args.min_recall,
                "configuration": {name: getattr(settings, name) for name in (
                    "EMBED_BACKEND", "EMBED_MODEL", "LOCAL_EMBED_MODEL", "EMBED_DIM", "EMBED_QUERY_PREFIX",
                    "RERANK_BACKEND", "RERANK_MODEL", "RERANK_CANDIDATE_K", "MODEL_PROCESSING_MODE")}}
    identity["run_fingerprint"] = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    failures = sum(row["error_code"] is not None for row in predictions)
    passed = failures == 0 and report["overall"][f"recall@{args.k}"] >= args.min_recall
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / "predictions.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in predictions), encoding="utf-8")
    (args.output_dir / "report.json").write_text(json.dumps({"identity": identity, "report": report,
        "failed_query_count": failures, "status": "passed" if passed else "failed"}, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if passed else 4


if __name__ == "__main__":
    raise SystemExit(main())
