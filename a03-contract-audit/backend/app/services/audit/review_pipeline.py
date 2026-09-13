"""合同审查窗口的分页、重试与截断恢复执行器。"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import time
from typing import Callable, Literal, Protocol

from app.llm.base import ChatOptions, LLMAdapter, LLMError, LLMResponse
from app.services.audit.protocol import (
    AUDIT_JSON_FORMAT,
    AgentReviewResult,
    ReviewIssue,
    ReviewedRiskCandidate,
    RiskEnvelope,
    parse_risk_envelope,
)
from app.services.rag.contract_structure import ContractWindow, split_contract_window


@dataclass(frozen=True)
class ReviewWindow:
    window: ContractWindow
    parent_window_id: str | None = None
    depth: int = 0


@dataclass(frozen=True)
class WindowReviewRequest:
    contract_id: int | str | None
    audit_job_id: int | str | None
    audit_generation: int
    agent: str
    dimensions: tuple[str, ...]
    review_window: ReviewWindow
    system_prompt: str
    build_user_prompt: Callable[[ReviewWindow, int, tuple[str, ...]], str]


class WindowCheckpoint(Protocol):
    """窗口检查点接口。

    ``load_valid`` 和 ``save_valid`` 的异常必须向上抛出，由任务级重试恢复；
    ``record_call`` 的具体持久化实现负责自行隔离记录失败，执行器不吞检查点异常。
    """

    def load_valid(self, request: WindowReviewRequest) -> AgentReviewResult | None: ...

    def save_valid(
        self,
        request: WindowReviewRequest,
        result: AgentReviewResult,
    ) -> None: ...

    def record_call(
        self,
        request: WindowReviewRequest,
        *,
        page: int,
        attempt: int,
        response: LLMResponse | None,
        validation_status: str,
        error_code: str | None,
    ) -> None: ...


class NullWindowCheckpoint:
    def load_valid(self, request: WindowReviewRequest) -> AgentReviewResult | None:
        return None

    def save_valid(
        self,
        request: WindowReviewRequest,
        result: AgentReviewResult,
    ) -> None:
        return None

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
        return None


@dataclass(frozen=True)
class _PageOutcome:
    kind: Literal["valid", "truncated", "issue"]
    envelope: RiskEnvelope | None = None
    issue: ReviewIssue | None = None


class WindowReviewer:
    def __init__(
        self,
        adapter: LLMAdapter,
        checkpoint: WindowCheckpoint | None = None,
        max_split_depth: int = 2,
        max_pages: int = 3,
        max_call_attempts: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_split_depth < 0:
            raise ValueError("max_split_depth 不能小于 0")
        if max_pages <= 0:
            raise ValueError("max_pages 必须为正数")
        if max_call_attempts <= 0:
            raise ValueError("max_call_attempts 必须为正数")
        self._adapter = adapter
        self._checkpoint = checkpoint or NullWindowCheckpoint()
        self._max_split_depth = max_split_depth
        self._max_pages = max_pages
        self._max_call_attempts = max_call_attempts
        self._sleep = sleep

    def review(self, request: WindowReviewRequest) -> AgentReviewResult:
        cached = self._checkpoint.load_valid(request)
        if cached is not None:
            return cached

        result = self._review_uncached(request)
        if result.complete:
            self._checkpoint.save_valid(request, result)
        return result

    def _review_uncached(self, request: WindowReviewRequest) -> AgentReviewResult:
        candidates: list[ReviewedRiskCandidate] = []
        for page in range(1, self._max_pages + 1):
            outcome = self._review_page(request, page)
            if outcome.kind == "truncated":
                recovered = self._recover_truncated(request)
                return recovered.model_copy(update={
                    "candidates": self._deduplicate(
                        request.agent,
                        [*candidates, *recovered.candidates],
                    ),
                })
            if outcome.kind == "issue":
                return AgentReviewResult(
                    candidates=self._deduplicate(request.agent, candidates),
                    issues=[outcome.issue] if outcome.issue is not None else [],
                    complete=False,
                    planned_windows=1,
                    completed_windows=0,
                )

            assert outcome.envelope is not None
            candidates.extend(
                ReviewedRiskCandidate(
                    **candidate.model_dump(),
                    source_window_id=request.review_window.window.window_id,
                    source_clause_ids=list(request.review_window.window.clause_ids),
                )
                for candidate in outcome.envelope.risks
            )
            if not outcome.envelope.has_more:
                return AgentReviewResult(
                    candidates=self._deduplicate(request.agent, candidates),
                    complete=True,
                    planned_windows=1,
                    completed_windows=1,
                )

        return AgentReviewResult(
            candidates=self._deduplicate(request.agent, candidates),
            issues=[self._issue(request, "PAGINATION_EXHAUSTED")],
            complete=False,
            planned_windows=1,
            completed_windows=0,
        )

    def _review_page(
        self,
        request: WindowReviewRequest,
        page: int,
    ) -> _PageOutcome:
        user_prompt = request.build_user_prompt(
            request.review_window,
            page,
            request.dimensions,
        )
        call_attempt = 0
        retryable_failures = 0
        invalid_outputs = 0
        while call_attempt < self._max_call_attempts:
            call_attempt += 1
            options = ChatOptions(
                response_format=AUDIT_JSON_FORMAT,
                request_id=self._request_id(request, page, call_attempt),
            )
            try:
                response = self._adapter.chat(
                    request.system_prompt,
                    user_prompt,
                    options=options,
                )
            except LLMError as error:
                error_code = self._map_error_code(error.code)
                self._checkpoint.record_call(
                    request,
                    page=page,
                    attempt=call_attempt,
                    response=None,
                    validation_status="error",
                    error_code=error_code,
                )
                if not error.retryable or call_attempt >= self._max_call_attempts:
                    return _PageOutcome(
                        kind="issue",
                        issue=self._issue(request, error_code),
                    )
                # 总预算最多允许两次等待，因此三次调用的退避固定为 0、1 秒。
                self._sleep(retryable_failures)
                retryable_failures += 1
                continue

            if response.finish_reason == "length":
                self._checkpoint.record_call(
                    request,
                    page=page,
                    attempt=call_attempt,
                    response=response,
                    validation_status="truncated",
                    error_code="OUTPUT_TRUNCATED",
                )
                return _PageOutcome(kind="truncated")

            try:
                if not isinstance(response.text, str):
                    raise ValueError("模型响应正文必须是字符串")
                envelope = parse_risk_envelope(response.text)
            except ValueError:
                invalid_outputs += 1
                self._checkpoint.record_call(
                    request,
                    page=page,
                    attempt=call_attempt,
                    response=response,
                    validation_status="invalid",
                    error_code="INVALID_MODEL_OUTPUT",
                )
                if invalid_outputs >= 2 or call_attempt >= self._max_call_attempts:
                    return _PageOutcome(
                        kind="issue",
                        issue=self._issue(request, "INVALID_MODEL_OUTPUT"),
                    )
                continue

            self._checkpoint.record_call(
                request,
                page=page,
                attempt=call_attempt,
                response=response,
                validation_status="valid",
                error_code=None,
            )
            return _PageOutcome(kind="valid", envelope=envelope)

        return _PageOutcome(
            kind="issue",
            issue=self._issue(request, "INVALID_MODEL_OUTPUT"),
        )

    def _recover_truncated(self, request: WindowReviewRequest) -> AgentReviewResult:
        review_window = request.review_window
        if review_window.depth >= self._max_split_depth:
            return self._truncated_result(request)

        children = split_contract_window(review_window.window)
        if len(children) < 2:
            return self._truncated_result(request)

        child_results: list[AgentReviewResult] = []
        for child in children:
            child_request = replace(
                request,
                review_window=ReviewWindow(
                    window=child,
                    parent_window_id=review_window.window.window_id,
                    depth=review_window.depth + 1,
                ),
            )
            child_results.append(self.review(child_request))

        planned_windows = sum(result.planned_windows for result in child_results)
        completed_windows = sum(result.completed_windows for result in child_results)
        candidates = [
            candidate
            for result in child_results
            for candidate in result.candidates
        ]
        issues = [issue for result in child_results for issue in result.issues]
        return AgentReviewResult(
            candidates=self._deduplicate(request.agent, candidates),
            issues=issues,
            complete=completed_windows == planned_windows,
            planned_windows=planned_windows,
            completed_windows=completed_windows,
        )

    def _truncated_result(self, request: WindowReviewRequest) -> AgentReviewResult:
        return AgentReviewResult(
            issues=[self._issue(request, "OUTPUT_TRUNCATED")],
            complete=False,
            planned_windows=1,
            completed_windows=0,
        )

    @staticmethod
    def _map_error_code(code: str) -> str:
        if code in {"MODEL_TIMEOUT", "MODEL_UNAVAILABLE"}:
            return code
        return "INVALID_MODEL_OUTPUT"

    @staticmethod
    def _issue(request: WindowReviewRequest, code: str) -> ReviewIssue:
        details = {
            "OUTPUT_TRUNCATED": "模型输出被截断且窗口无法继续拆分",
            "INVALID_MODEL_OUTPUT": "模型未返回有效的审查 JSON",
            "MODEL_TIMEOUT": "模型调用超时且已达到重试上限",
            "MODEL_UNAVAILABLE": "模型暂时不可用且已达到重试上限",
            "PAGINATION_EXHAUSTED": "模型仍有后续结果但已达到分页上限",
        }
        return ReviewIssue(
            code=code,
            agent=request.agent,
            window_id=request.review_window.window.window_id,
            detail=details[code],
        )

    @staticmethod
    def _request_id(
        request: WindowReviewRequest,
        page: int,
        attempt: int,
    ) -> str:
        return (
            f"audit:{request.audit_job_id}:{request.audit_generation}:"
            f"{request.agent}:{request.review_window.window.window_id}:"
            f"{page}:{attempt}"
        )

    @staticmethod
    def _deduplicate(
        agent: str,
        candidates: list[ReviewedRiskCandidate],
    ) -> list[ReviewedRiskCandidate]:
        unique: list[ReviewedRiskCandidate] = []
        seen: set[str] = set()
        for candidate in candidates:
            identity = f"{agent}\0{candidate.category}\0{candidate.quote}"
            digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            unique.append(candidate)
        return unique
