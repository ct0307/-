"""使用独立短事务保存窗口检查点和不含正文的调用观测。"""
from __future__ import annotations

import hashlib
import json
from typing import Callable

from sqlalchemy import case, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.llm.base import LLMResponse
from app.models.models import AuditWindowRun, LLMCallLog
from app.services.audit.protocol import AUDIT_PROTOCOL_VERSION, AgentReviewResult
from app.services.audit.review_pipeline import WindowReviewRequest


log = get_logger("audit.window_repository")


def dimensions_hash(dimensions: tuple[str, ...]) -> str:
    normalized = json.dumps(sorted(set(dimensions)), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _dimension_label(dimensions: tuple[str, ...]) -> str:
    label = ",".join(sorted(set(dimensions))) or "all"
    return label if len(label) <= 64 else dimensions_hash(dimensions)


class SqlAlchemyWindowCheckpoint:
    """session_factory 必须每次创建新的 Session，不得传入调用方正在使用的事务。"""

    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
        *,
        protocol_version: str = AUDIT_PROTOCOL_VERSION,
        provider: str | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._protocol_version = protocol_version
        self._provider = settings.LLM_PROVIDER if provider is None else provider

    def _identity(self, request: WindowReviewRequest) -> dict:
        if request.contract_id is None or request.contract_id == "":
            raise ValueError("持久化窗口检查点必须提供 contract_id")
        return {
            "audit_job_id": request.audit_job_id,
            "audit_generation": request.audit_generation,
            "agent": request.agent,
            "dimensions_hash": dimensions_hash(request.dimensions),
            "window_id": request.review_window.window.window_id,
            "protocol_version": self._protocol_version,
        }

    def load_valid(self, request: WindowReviewRequest) -> AgentReviewResult | None:
        if request.audit_job_id is None:
            return None
        identity = self._identity(request)
        with self._session_factory() as db:
            row = db.execute(select(AuditWindowRun).filter_by(**identity, status="valid")).scalar_one_or_none()
            if row is None:
                return None
            self._check_contract(row, request)
            return AgentReviewResult.model_validate_json(row.result_json)

    def save_valid(self, request: WindowReviewRequest, result: AgentReviewResult) -> None:
        if request.audit_job_id is None:
            return
        identity = self._identity(request)
        if not result.complete:
            raise ValueError("未完成的审查结果不能保存为 valid 检查点")
        try:
            with self._session_factory() as db, db.begin():
                row = db.execute(select(AuditWindowRun).filter_by(**identity)).scalar_one_or_none()
                if row is None:
                    row = AuditWindowRun(contract_id=request.contract_id, **identity)
                    db.add(row)
                self._update(row, request, result)
        except IntegrityError:
            # 另一任务可能在首次查询后抢先插入；原事务已回滚，重新打开事务再读。
            with self._session_factory() as db, db.begin():
                row = db.execute(select(AuditWindowRun).filter_by(**identity)).scalar_one_or_none()
                if row is None:
                    raise
                self._update(row, request, result)

    @staticmethod
    def _check_contract(row: AuditWindowRun, request: WindowReviewRequest) -> None:
        if str(row.contract_id) != str(request.contract_id):
            raise ValueError("窗口检查点 contract_id 与任务不一致")

    def _update(
        self,
        row: AuditWindowRun,
        request: WindowReviewRequest,
        result: AgentReviewResult,
    ) -> None:
        self._check_contract(row, request)
        row.parent_window_id = request.review_window.parent_window_id
        row.depth = request.review_window.depth
        row.status = "valid"
        row.result_json = result.model_dump_json()
        row.issues_json = json.dumps(
            [issue.model_dump(mode="json") for issue in result.issues],
            ensure_ascii=False, separators=(",", ":"),
        )
        # 使用数据库当前值，避免保存时的旧快照覆盖另一事务刚累加的调用次数。
        row.attempts = (
            case((AuditWindowRun.attempts < 1, 1), else_=AuditWindowRun.attempts)
            if row.id is not None else 1
        )

    def _increment_attempt(self, db: Session, request: WindowReviewRequest) -> None:
        identity = self._identity(request)
        row = db.execute(select(AuditWindowRun).filter_by(**identity)).scalar_one_or_none()
        if row is None:
            db.add(AuditWindowRun(
                contract_id=request.contract_id,
                parent_window_id=request.review_window.parent_window_id,
                depth=request.review_window.depth,
                status="failed", result_json="{}", issues_json="[]", attempts=1,
                **identity,
            ))
            # 先完成窗口插入，唯一冲突回滚后重试整个事务，不留下重复日志。
            db.flush()
        else:
            self._check_contract(row, request)
            db.execute(
                update(AuditWindowRun).filter_by(**identity).values(
                    attempts=AuditWindowRun.attempts + 1,
                ),
                execution_options={"synchronize_session": False},
            )

    def record_call(
        self,
        request: WindowReviewRequest,
        *,
        page: int,
        attempt: int,
        response: LLMResponse | None,
        validation_status: str,
        error_code: str | None,
    ) -> None:
        try:
            for conflict_attempt in range(2):
                try:
                    with self._session_factory() as db, db.begin():
                        if request.audit_job_id is not None:
                            self._increment_attempt(db, request)
                        db.add(LLMCallLog(
                            contract_id=request.contract_id,
                            audit_job_id=request.audit_job_id,
                            agent=request.agent,
                            window_id=request.review_window.window.window_id,
                            dimension=_dimension_label(request.dimensions),
                            attempt=attempt,
                            provider=self._provider,
                            model=response.model if response is not None else "",
                            prompt_tokens=response.prompt_tokens if response is not None else 0,
                            completion_tokens=response.completion_tokens if response is not None else 0,
                            finish_reason=response.finish_reason if response is not None else None,
                            latency_ms=response.latency_ms if response is not None else 0,
                            mode="llm",
                            validation_status=validation_status,
                            error_code=error_code,
                        ))
                    return
                except IntegrityError:
                    if conflict_attempt == 1:
                        raise
        except Exception as error:
            # 不带异常文本或 traceback，避免驱动异常泄漏 SQL 参数和合同内容。
            log.warning("audit.window_call_log_failed", exception_type=type(error).__name__)
