"""合同审查窗口的分页、重试与截断恢复执行器。"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import time
from typing import Callable, Literal, Protocol

from app.core.config import settings
from app.llm.base import ChatOptions, LLMAdapter, LLMError, LLMResponse
from app.services.audit.protocol import (
    AUDIT_JSON_FORMAT,
    AgentReviewResult,
    ReviewIssue,
    ReviewedRiskCandidate,
    RiskEnrichment,
    RiskEnrichmentItem,
    RiskEnvelope,
    RiskFinding,
    RiskFindingEnvelope,
    parse_risk_enrichment,
    parse_risk_finding_envelope,
    parse_risk_envelope,
)
from app.services.rag.contract_structure import ContractWindow, split_contract_window


@dataclass(frozen=True)
class ReviewWindow:
    window: ContractWindow
    parent_window_id: str | None = None
    depth: int = 0


def enrichment_candidate_id(window_id: str, finding: RiskFinding) -> str:
    payload = f"{window_id}\0{finding.category}\0{finding.quote}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


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
    deadline: float | None = None
    discovery_system_prompt: str | None = None
    build_discovery_prompt: Callable[
        [ReviewWindow, int, tuple[str, ...], tuple[RiskFinding, ...], int], str
    ] | None = None
    enrichment_system_prompt: str | None = None
    build_enrichment_prompt: Callable[[ReviewWindow, RiskFinding, bool], str] | None = None
    build_enrichment_batch_prompt: Callable[
        [ReviewWindow, tuple[RiskFinding, ...], bool], str
    ] | None = None


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
class WindowCallObservation:
    request: WindowReviewRequest
    page: int
    attempt: int
    response: LLMResponse | None
    validation_status: str
    error_code: str | None


@dataclass(frozen=True)
class BufferedWindowExecution:
    result: AgentReviewResult
    observations: tuple[WindowCallObservation, ...]
    saved_results: tuple[tuple[WindowReviewRequest, AgentReviewResult], ...]


class BufferedWindowCheckpoint:
    """工作线程内只记录内存观测，不打开数据库会话。"""

    def __init__(self) -> None:
        self._observations: list[WindowCallObservation] = []
        self._saved_results: list[tuple[WindowReviewRequest, AgentReviewResult]] = []

    def load_valid(self, request: WindowReviewRequest) -> AgentReviewResult | None:
        return None

    def save_valid(
        self,
        request: WindowReviewRequest,
        result: AgentReviewResult,
    ) -> None:
        self._saved_results.append((request, result))

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
        self._observations.append(WindowCallObservation(
            request=request,
            page=page,
            attempt=attempt,
            response=response,
            validation_status=validation_status,
            error_code=error_code,
        ))

    def execution(self, result: AgentReviewResult) -> BufferedWindowExecution:
        return BufferedWindowExecution(
            result=result,
            observations=tuple(self._observations),
            saved_results=tuple(self._saved_results),
        )


@dataclass(frozen=True)
class _PageOutcome:
    kind: Literal["valid", "truncated", "issue"]
    envelope: RiskEnvelope | None = None
    issue: ReviewIssue | None = None


@dataclass(frozen=True)
class _DiscoveryOutcome:
    kind: Literal["valid", "truncated", "issue"]
    envelope: RiskFindingEnvelope | None = None
    issue: ReviewIssue | None = None


@dataclass(frozen=True)
class _EnrichmentOutcome:
    kind: Literal["valid", "truncated", "issue"]
    enrichment: RiskEnrichment | None = None
    issue: ReviewIssue | None = None


@dataclass(frozen=True)
class _BatchEnrichmentOutcome:
    enrichments: dict[str, RiskEnrichment]
    failed: tuple[RiskFinding, ...]


class WindowReviewer:
    def __init__(
        self,
        adapter: LLMAdapter,
        checkpoint: WindowCheckpoint | None = None,
        max_split_depth: int = 2,
        max_pages: int = 8,
        max_call_attempts: int = 3,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
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
        self._clock = clock

    def review(self, request: WindowReviewRequest) -> AgentReviewResult:
        cached = self._checkpoint.load_valid(request)
        if cached is not None:
            return cached

        result = self._review_uncached(request)
        if result.complete:
            self._checkpoint.save_valid(request, result)
        return result

    def _review_uncached(self, request: WindowReviewRequest) -> AgentReviewResult:
        two_stage_fields = (
            request.discovery_system_prompt,
            request.build_discovery_prompt,
            request.enrichment_system_prompt,
            request.build_enrichment_prompt,
        )
        if any(value is not None for value in two_stage_fields):
            if not all(value is not None for value in two_stage_fields):
                raise ValueError("两阶段审查配置必须完整")
            return self._review_two_stage_uncached(request)

        candidates: list[ReviewedRiskCandidate] = []
        for page in range(1, self._max_pages + 1):
            if self._deadline_expired(request):
                return self._deadline_result(request, candidates)
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

    def _review_two_stage_uncached(
        self,
        request: WindowReviewRequest,
    ) -> AgentReviewResult:
        candidates: list[ReviewedRiskCandidate] = []
        accepted: list[RiskFinding] = []
        for page in range(1, self._max_pages + 1):
            if self._deadline_expired(request):
                return self._deadline_result(request, candidates)

            outcome = self._review_discovery_page(
                request, page, tuple(accepted), page_size=5,
            )
            if outcome.kind == "truncated":
                outcome = self._review_discovery_page(
                    request, page, tuple(accepted), page_size=1,
                )
            if outcome.kind == "truncated":
                recovered = self._recover_truncated(request)
                return recovered.model_copy(update={
                    "candidates": self._deduplicate(
                        request.agent, [*candidates, *recovered.candidates]
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
            page_findings: list[RiskFinding] = []
            for finding in outcome.envelope.risks:
                if self._finding_seen(finding, accepted) or self._finding_seen(
                    finding, page_findings
                ):
                    continue
                page_findings.append(finding)

            if (
                settings.AUDIT_BATCH_ENRICHMENT_ENABLED
                and request.build_enrichment_batch_prompt is not None
            ):
                for offset in range(0, len(page_findings), 5):
                    batch = tuple(page_findings[offset:offset + 5])
                    batch_outcome = self._review_enrichment_batch(
                        request, page, batch
                    )
                    resolved = dict(batch_outcome.enrichments)
                    for finding in batch_outcome.failed:
                        candidate_id = enrichment_candidate_id(
                            request.review_window.window.window_id, finding
                        )
                        if self._deadline_expired(request):
                            self._append_resolved_enrichments(
                                request, batch, resolved, candidates, accepted
                            )
                            return self._deadline_result(request, candidates)
                        detail = self._review_enrichment(request, page, finding)
                        if detail.kind != "valid":
                            self._append_resolved_enrichments(
                                request, batch, resolved, candidates, accepted
                            )
                            issue = detail.issue or self._issue(
                                request, "OUTPUT_TRUNCATED"
                            )
                            return AgentReviewResult(
                                candidates=self._deduplicate(
                                    request.agent, candidates
                                ),
                                issues=[issue],
                                complete=False,
                                planned_windows=1,
                                completed_windows=0,
                            )
                        assert detail.enrichment is not None
                        resolved[candidate_id] = detail.enrichment
                    self._append_resolved_enrichments(
                        request, batch, resolved, candidates, accepted
                    )
            else:
                for finding in page_findings:
                    detail = self._review_enrichment(request, page, finding)
                    if detail.kind != "valid":
                        issue = detail.issue or self._issue(
                            request, "OUTPUT_TRUNCATED"
                        )
                        return AgentReviewResult(
                            candidates=self._deduplicate(request.agent, candidates),
                            issues=[issue],
                            complete=False,
                            planned_windows=1,
                            completed_windows=0,
                        )
                    assert detail.enrichment is not None
                    candidates.append(self._reviewed_candidate(
                        request, finding, detail.enrichment
                    ))
                    accepted.append(finding)

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

    def _review_discovery_page(
        self,
        request: WindowReviewRequest,
        page: int,
        accepted: tuple[RiskFinding, ...],
        *,
        page_size: int,
    ) -> _DiscoveryOutcome:
        assert request.build_discovery_prompt is not None
        assert request.discovery_system_prompt is not None
        user_prompt = request.build_discovery_prompt(
            request.review_window, page, request.dimensions, accepted, page_size
        )
        invalid_outputs = 0
        retryable_failures = 0
        for attempt in range(1, self._max_call_attempts + 1):
            if self._deadline_expired(request):
                return _DiscoveryOutcome(
                    kind="issue",
                    issue=self._issue(request, "AUDIT_DEADLINE_EXCEEDED"),
                )
            options = ChatOptions(
                response_format=AUDIT_JSON_FORMAT,
                request_id=self._request_id(
                    request, page, attempt, stage=f"discovery-{page_size}"
                ),
                thinking="disabled",
            )
            try:
                response = self._adapter.chat(
                    request.discovery_system_prompt, user_prompt, options=options
                )
            except LLMError as error:
                error_code = self._map_error_code(error.code)
                self._checkpoint.record_call(
                    request, page=page, attempt=attempt, response=None,
                    validation_status="error", error_code=error_code,
                )
                if not error.retryable or attempt >= self._max_call_attempts:
                    return _DiscoveryOutcome(
                        kind="issue", issue=self._issue(request, error_code)
                    )
                if not self._can_wait(request, retryable_failures):
                    return _DiscoveryOutcome(
                        kind="issue",
                        issue=self._issue(request, "AUDIT_DEADLINE_EXCEEDED"),
                    )
                self._sleep(retryable_failures)
                retryable_failures += 1
                continue

            if response.finish_reason == "length":
                self._checkpoint.record_call(
                    request, page=page, attempt=attempt, response=response,
                    validation_status="truncated", error_code="OUTPUT_TRUNCATED",
                )
                return _DiscoveryOutcome(kind="truncated")
            try:
                if not isinstance(response.text, str):
                    raise ValueError("模型响应正文必须是字符串")
                try:
                    envelope = parse_risk_finding_envelope(response.text)
                except ValueError:
                    legacy = parse_risk_envelope(response.text)
                    envelope = RiskFindingEnvelope(
                        risks=[
                            RiskFinding(
                                level=item.level,
                                category=item.category,
                                quote=item.quote,
                            )
                            for item in legacy.risks
                        ],
                        has_more=legacy.has_more,
                    )
                if len(envelope.risks) > page_size:
                    raise ValueError("候选数量超过当前页容量")
            except ValueError:
                invalid_outputs += 1
                self._checkpoint.record_call(
                    request, page=page, attempt=attempt, response=response,
                    validation_status="invalid", error_code="INVALID_MODEL_OUTPUT",
                )
                if invalid_outputs >= 2 or attempt >= self._max_call_attempts:
                    return _DiscoveryOutcome(
                        kind="issue",
                        issue=self._issue(request, "INVALID_MODEL_OUTPUT"),
                    )
                continue
            self._checkpoint.record_call(
                request, page=page, attempt=attempt, response=response,
                validation_status="valid", error_code=None,
            )
            return _DiscoveryOutcome(kind="valid", envelope=envelope)
        return _DiscoveryOutcome(
            kind="issue", issue=self._issue(request, "INVALID_MODEL_OUTPUT")
        )

    def _review_enrichment(
        self,
        request: WindowReviewRequest,
        page: int,
        finding: RiskFinding,
    ) -> _EnrichmentOutcome:
        assert request.build_enrichment_prompt is not None
        assert request.enrichment_system_prompt is not None
        max_attempts = min(2, self._max_call_attempts)
        for attempt in range(1, max_attempts + 1):
            if self._deadline_expired(request):
                return _EnrichmentOutcome(
                    kind="issue",
                    issue=self._issue(request, "AUDIT_DEADLINE_EXCEEDED"),
                )
            concise = attempt > 1
            user_prompt = request.build_enrichment_prompt(
                request.review_window, finding, concise
            )
            digest = hashlib.sha256(
                f"{finding.category}\0{finding.quote}".encode("utf-8")
            ).hexdigest()[:12]
            options = ChatOptions(
                response_format=AUDIT_JSON_FORMAT,
                request_id=self._request_id(
                    request, page, attempt, stage=f"enrichment-{digest}"
                ),
                thinking="disabled",
            )
            try:
                response = self._adapter.chat(
                    request.enrichment_system_prompt, user_prompt, options=options
                )
            except LLMError as error:
                error_code = self._map_error_code(error.code)
                self._checkpoint.record_call(
                    request, page=page, attempt=attempt, response=None,
                    validation_status="error", error_code=error_code,
                )
                if not error.retryable or attempt >= max_attempts:
                    return _EnrichmentOutcome(
                        kind="issue", issue=self._issue(request, error_code)
                    )
                continue
            if response.finish_reason == "length":
                self._checkpoint.record_call(
                    request, page=page, attempt=attempt, response=response,
                    validation_status="truncated", error_code="OUTPUT_TRUNCATED",
                )
                if attempt >= max_attempts:
                    return _EnrichmentOutcome(kind="truncated")
                continue
            try:
                if not isinstance(response.text, str):
                    raise ValueError("模型响应正文必须是字符串")
                try:
                    enrichment = parse_risk_enrichment(response.text)
                except ValueError:
                    legacy = parse_risk_envelope(response.text)
                    if len(legacy.risks) != 1:
                        raise ValueError("旧协议补全结果必须只有一条风险")
                    legacy_item = legacy.risks[0]
                    if (
                        legacy_item.category != finding.category
                        or legacy_item.quote != finding.quote
                    ):
                        raise ValueError("旧协议补全结果与候选不一致")
                    enrichment = RiskEnrichment(
                        reason=legacy_item.reason,
                        suggestion=legacy_item.suggestion,
                    )
            except ValueError:
                self._checkpoint.record_call(
                    request, page=page, attempt=attempt, response=response,
                    validation_status="invalid", error_code="INVALID_MODEL_OUTPUT",
                )
                if attempt >= max_attempts:
                    return _EnrichmentOutcome(
                        kind="issue",
                        issue=self._issue(request, "INVALID_MODEL_OUTPUT"),
                    )
                continue
            self._checkpoint.record_call(
                request, page=page, attempt=attempt, response=response,
                validation_status="valid", error_code=None,
            )
            return _EnrichmentOutcome(kind="valid", enrichment=enrichment)
        return _EnrichmentOutcome(
            kind="issue", issue=self._issue(request, "INVALID_MODEL_OUTPUT")
        )

    def _review_enrichment_batch(
        self,
        request: WindowReviewRequest,
        page: int,
        findings: tuple[RiskFinding, ...],
    ) -> _BatchEnrichmentOutcome:
        assert request.build_enrichment_batch_prompt is not None
        assert request.enrichment_system_prompt is not None
        if not findings or self._deadline_expired(request):
            return _BatchEnrichmentOutcome({}, findings)

        prompt = request.build_enrichment_batch_prompt(
            request.review_window, findings, False
        )
        ids = {
            enrichment_candidate_id(
                request.review_window.window.window_id, finding
            ): finding
            for finding in findings
        }
        options = ChatOptions(
            response_format=AUDIT_JSON_FORMAT,
            request_id=self._request_id(
                request, page, 1, stage=f"enrichment-batch-{len(findings)}"
            ),
            thinking="disabled",
        )
        response: LLMResponse | None = None
        try:
            response = self._adapter.chat(
                request.enrichment_system_prompt, prompt, options=options
            )
        except LLMError as error:
            self._checkpoint.record_call(
                request, page=page, attempt=1, response=None,
                validation_status="error",
                error_code=self._map_error_code(error.code),
            )
            return _BatchEnrichmentOutcome({}, findings)

        if response.finish_reason == "length":
            self._checkpoint.record_call(
                request, page=page, attempt=1, response=response,
                validation_status="truncated", error_code="OUTPUT_TRUNCATED",
            )
            return _BatchEnrichmentOutcome({}, findings)

        try:
            raw_items = self._batch_enrichment_items(response.text)
        except (TypeError, ValueError):
            self._checkpoint.record_call(
                request, page=page, attempt=1, response=response,
                validation_status="invalid", error_code="INVALID_MODEL_OUTPUT",
            )
            return _BatchEnrichmentOutcome({}, findings)

        by_id: dict[str, list[RiskEnrichmentItem]] = {}
        for raw in raw_items:
            try:
                item = RiskEnrichmentItem.model_validate(raw)
            except (TypeError, ValueError):
                continue
            if item.candidate_id in ids:
                by_id.setdefault(item.candidate_id, []).append(item)

        enrichments = {
            candidate_id: RiskEnrichment(
                reason=items[0].reason,
                suggestion=items[0].suggestion,
            )
            for candidate_id, items in by_id.items()
            if len(items) == 1
        }
        failed = tuple(
            finding
            for candidate_id, finding in ids.items()
            if candidate_id not in enrichments
        )
        self._checkpoint.record_call(
            request, page=page, attempt=1, response=response,
            validation_status="valid" if not failed else "partial",
            error_code=None if not failed else "INVALID_MODEL_OUTPUT",
        )
        return _BatchEnrichmentOutcome(enrichments, failed)

    @staticmethod
    def _batch_enrichment_items(text: object) -> list[object]:
        if not isinstance(text, str):
            raise ValueError("批量补全输出正文类型无效")
        stripped = text.strip()
        if not stripped.startswith("{") or not stripped.endswith("}"):
            raise ValueError("批量补全输出必须是 JSON 对象")
        payload = json.loads(stripped)
        if not isinstance(payload, dict) or set(payload) != {"items"}:
            raise ValueError("批量补全顶层字段无效")
        items = payload["items"]
        if not isinstance(items, list) or not 1 <= len(items) <= 5:
            raise ValueError("批量补全 items 数量无效")
        return items

    @staticmethod
    def _reviewed_candidate(
        request: WindowReviewRequest,
        finding: RiskFinding,
        enrichment: RiskEnrichment,
    ) -> ReviewedRiskCandidate:
        return ReviewedRiskCandidate(
            level=finding.level,
            category=finding.category,
            quote=finding.quote,
            reason=enrichment.reason,
            suggestion=enrichment.suggestion,
            source_window_id=request.review_window.window.window_id,
            source_clause_ids=list(request.review_window.window.clause_ids),
        )

    def _append_resolved_enrichments(
        self,
        request: WindowReviewRequest,
        findings: tuple[RiskFinding, ...],
        enrichments: dict[str, RiskEnrichment],
        candidates: list[ReviewedRiskCandidate],
        accepted: list[RiskFinding],
    ) -> None:
        for finding in findings:
            candidate_id = enrichment_candidate_id(
                request.review_window.window.window_id, finding
            )
            enrichment = enrichments.get(candidate_id)
            if enrichment is None:
                continue
            candidates.append(self._reviewed_candidate(
                request, finding, enrichment
            ))
            accepted.append(finding)

    @staticmethod
    def _finding_seen(finding: RiskFinding, accepted: list[RiskFinding]) -> bool:
        return any(
            item.category == finding.category and item.quote == finding.quote
            for item in accepted
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
            if self._deadline_expired(request):
                return _PageOutcome(
                    kind="issue",
                    issue=self._issue(request, "AUDIT_DEADLINE_EXCEEDED"),
                )
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
                if not self._can_wait(request, retryable_failures):
                    return _PageOutcome(
                        kind="issue",
                        issue=self._issue(request, "AUDIT_DEADLINE_EXCEEDED"),
                    )
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
        if code in {"MODEL_TIMEOUT", "MODEL_UNAVAILABLE", "MODEL_REJECTED"}:
            return code
        return "INVALID_MODEL_OUTPUT"

    @staticmethod
    def _issue(request: WindowReviewRequest, code: str) -> ReviewIssue:
        details = {
            "OUTPUT_TRUNCATED": "模型输出被截断且窗口无法继续拆分",
            "INVALID_MODEL_OUTPUT": "模型未返回有效的审查 JSON",
            "MODEL_TIMEOUT": "模型调用超时且已达到重试上限",
            "MODEL_UNAVAILABLE": "模型暂时不可用且已达到重试上限",
            "MODEL_REJECTED": "模型供应商拒绝了审查请求",
            "PAGINATION_EXHAUSTED": "模型仍有后续结果但已达到分页上限",
            "AUDIT_DEADLINE_EXCEEDED": "审查达到整体时限，未启动新的模型调用",
        }
        return ReviewIssue(
            code=code,
            agent=request.agent,
            window_id=request.review_window.window.window_id,
            detail=details[code],
        )

    def _deadline_expired(self, request: WindowReviewRequest) -> bool:
        return request.deadline is not None and self._clock() >= request.deadline

    def _can_wait(self, request: WindowReviewRequest, seconds: float) -> bool:
        return (
            request.deadline is None
            or self._clock() + seconds < request.deadline
        )

    def _deadline_result(
        self,
        request: WindowReviewRequest,
        candidates: list[ReviewedRiskCandidate] | None = None,
    ) -> AgentReviewResult:
        return AgentReviewResult(
            candidates=self._deduplicate(request.agent, candidates or []),
            issues=[self._issue(request, "AUDIT_DEADLINE_EXCEEDED")],
            complete=False,
            planned_windows=1,
            completed_windows=0,
        )

    @staticmethod
    def _request_id(
        request: WindowReviewRequest,
        page: int,
        attempt: int,
        stage: str | None = None,
    ) -> str:
        base = (
            f"audit:{request.audit_job_id}:{request.audit_generation}:"
            f"{request.agent}:{request.review_window.window.window_id}:"
            f"{page}:{attempt}"
        )
        return f"{base}:{stage}" if stage else base

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
