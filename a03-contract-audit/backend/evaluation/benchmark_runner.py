"""OpenClaw 与 GPU 的同口径 3+5 完整数据集基准执行器。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any, Literal, Mapping, Protocol, Sequence

import httpx

from evaluation.benchmark import (
    BenchmarkConfig,
    PowerSample,
    assert_comparable,
    summarize_benchmark,
)
from evaluation.evidence import EvidenceWriter


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class TargetUnavailable(RuntimeError):
    """基准目标端点不可达。"""


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    prompt: str
    system: str = ""


@dataclass(frozen=True)
class InvocationResult:
    latency_ms: float | None
    prompt_tokens: int
    completion_tokens: int
    error: str | None


@dataclass(frozen=True)
class BenchmarkDataset:
    schema_version: str
    model: str
    cases: tuple[BenchmarkCase, ...]
    model_sha256: str
    prompt_version: str
    dataset_sha256: str
    context_length: int
    concurrency: int
    output_schema_sha256: str
    warmup_runs: int
    measured_runs: int

    def config_for(self, target: str) -> BenchmarkConfig:
        return BenchmarkConfig(
            target=target,
            model_sha256=self.model_sha256,
            prompt_version=self.prompt_version,
            dataset_sha256=self.dataset_sha256,
            context_length=self.context_length,
            concurrency=self.concurrency,
            output_schema_sha256=self.output_schema_sha256,
            warmup_runs=self.warmup_runs,
            measured_runs=self.measured_runs,
        )


@dataclass(frozen=True)
class TargetRunResult:
    config: BenchmarkConfig
    warmup_rounds: int
    measured_rounds: int
    summary: dict[str, object]


@dataclass(frozen=True)
class BenchmarkComparison:
    status: Literal["passed", "failed"]
    openclaw_success_rate: float
    gpu_success_rate: float
    openclaw_p95: float | None
    gpu_p95: float | None
    openclaw_throughput: float
    gpu_throughput: float


class BenchmarkTarget(Protocol):
    def invoke(self, phase: str, case: BenchmarkCase) -> InvocationResult:
        raise NotImplementedError


class OpenAICompatibleTarget:
    def __init__(
        self,
        base_url: str,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = 120,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._headers = {"Content-Type": "application/json"}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def invoke(self, phase: str, case: BenchmarkCase) -> InvocationResult:
        messages = []
        if case.system:
            messages.append({"role": "system", "content": case.system})
        messages.append({"role": "user", "content": case.prompt})
        started = time.perf_counter()
        try:
            response = self._client.post(
                f"{self._base_url}/chat/completions",
                headers=self._headers,
                json={
                    "model": self._model,
                    "messages": messages,
                    "temperature": 0,
                    "stream": False,
                },
            )
        except httpx.RequestError as exc:
            raise TargetUnavailable(f"目标端点不可达: {type(exc).__name__}") from exc
        latency_ms = (time.perf_counter() - started) * 1000
        if response.status_code >= 400:
            return InvocationResult(None, 0, 0, f"http_{response.status_code}")
        try:
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("content 不是字符串")
            usage = payload.get("usage", {})
            return InvocationResult(
                latency_ms=latency_ms,
                prompt_tokens=int(usage.get("prompt_tokens", 0)),
                completion_tokens=int(usage.get("completion_tokens", 0)),
                error=None,
            )
        except (KeyError, IndexError, TypeError, ValueError):
            return InvocationResult(None, 0, 0, "invalid_response")


def dataset_sha256(cases: Sequence[BenchmarkCase]) -> str:
    canonical = json.dumps(
        [
            {"case_id": case.case_id, "prompt": case.prompt, "system": case.system}
            for case in cases
        ],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def load_benchmark_manifest(path: Path) -> BenchmarkDataset:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"基准清单不是有效 JSON: {path}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
        raise ValueError("基准清单 schema_version 必须为 1.0")
    rows = payload.get("cases")
    if not isinstance(rows, list) or not rows:
        raise ValueError("基准清单 cases 必须是非空数组")
    cases: list[BenchmarkCase] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"cases[{index}] 必须是对象")
        case_id = str(row.get("case_id", "")).strip()
        prompt = row.get("prompt")
        system = row.get("system", "")
        if not case_id or case_id in seen:
            raise ValueError(f"cases[{index}].case_id 为空或重复")
        if not isinstance(prompt, str) or not prompt:
            raise ValueError(f"cases[{index}].prompt 必须是非空字符串")
        if not isinstance(system, str):
            raise ValueError(f"cases[{index}].system 必须是字符串")
        seen.add(case_id)
        cases.append(BenchmarkCase(case_id=case_id, prompt=prompt, system=system))

    expected_hash = str(payload.get("dataset_sha256", ""))
    actual_hash = dataset_sha256(cases)
    if expected_hash != actual_hash:
        raise ValueError(
            f"dataset_sha256 不匹配: expected={expected_hash}, actual={actual_hash}"
        )
    warmup_runs = payload.get("warmup_runs")
    measured_runs = payload.get("measured_runs")
    if warmup_runs != 3 or measured_runs != 5:
        raise ValueError("基准清单必须配置 3 次预热和 5 次正式运行")

    model = str(payload.get("model", "")).strip()
    model_hash = str(payload.get("model_sha256", "")).strip()
    prompt_version = str(payload.get("prompt_version", "")).strip()
    output_hash = str(payload.get("output_schema_sha256", "")).strip()
    context_length = payload.get("context_length")
    concurrency = payload.get("concurrency")
    if not all((model, model_hash, prompt_version, output_hash)):
        raise ValueError("基准清单缺少模型、提示词或输出 Schema 标识")
    if not _SHA256.fullmatch(model_hash):
        raise ValueError("model_sha256 必须是 64 位小写十六进制")
    if not _SHA256.fullmatch(output_hash):
        raise ValueError("output_schema_sha256 必须是 64 位小写十六进制")
    if not isinstance(context_length, int) or context_length <= 0:
        raise ValueError("context_length 必须是正整数")
    if not isinstance(concurrency, int) or concurrency <= 0:
        raise ValueError("concurrency 必须是正整数")
    return BenchmarkDataset(
        schema_version="1.0",
        model=model,
        cases=tuple(cases),
        model_sha256=model_hash,
        prompt_version=prompt_version,
        dataset_sha256=actual_hash,
        context_length=context_length,
        concurrency=concurrency,
        output_schema_sha256=output_hash,
        warmup_runs=warmup_runs,
        measured_runs=measured_runs,
    )


def _record_invocation(
    writer: EvidenceWriter | None,
    *,
    config: BenchmarkConfig,
    phase: str,
    round_index: int,
    case: BenchmarkCase,
    result: InvocationResult,
) -> None:
    if writer is None:
        return
    writer.append(
        "benchmark",
        {
            "event": "invocation",
            "target": config.target,
            "phase": phase,
            "round_index": round_index,
            "case_id": case.case_id,
            "success": result.error is None,
            "latency_ms": result.latency_ms,
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "error": result.error,
        },
    )


def _run_round(
    phase: str,
    round_index: int,
    cases: Sequence[BenchmarkCase],
    *,
    config: BenchmarkConfig,
    target: BenchmarkTarget,
    writer: EvidenceWriter | None,
) -> list[float | None]:
    def invoke(case: BenchmarkCase) -> InvocationResult:
        try:
            return target.invoke(phase, case)
        except TargetUnavailable:
            raise
        except Exception as exc:
            return InvocationResult(None, 0, 0, type(exc).__name__)

    if config.concurrency == 1 or len(cases) == 1:
        results = [invoke(case) for case in cases]
    else:
        with ThreadPoolExecutor(max_workers=min(config.concurrency, len(cases))) as executor:
            results = list(executor.map(invoke, cases))

    latencies: list[float | None] = []
    for case, result in zip(cases, results):
        _record_invocation(
            writer,
            config=config,
            phase=phase,
            round_index=round_index,
            case=case,
            result=result,
        )
        latencies.append(result.latency_ms if result.error is None else None)
    return latencies


def run_target(
    config: BenchmarkConfig,
    cases: Sequence[BenchmarkCase],
    *,
    target: BenchmarkTarget,
    writer: EvidenceWriter | None,
    power_samples: Sequence[PowerSample] | None = None,
) -> TargetRunResult:
    if not cases:
        raise ValueError("基准数据集不能为空")
    if config.warmup_runs != 3 or config.measured_runs != 5:
        raise ValueError("基准必须执行 3 次预热和 5 次正式运行")
    actual_hash = dataset_sha256(cases)
    if actual_hash != config.dataset_sha256:
        raise ValueError(
            f"dataset_sha256 不匹配: expected={config.dataset_sha256}, actual={actual_hash}"
        )

    for round_index in range(config.warmup_runs):
        _run_round(
            "warmup",
            round_index,
            cases,
            config=config,
            target=target,
            writer=writer,
        )

    measured: list[float | None] = []
    started = time.perf_counter()
    for round_index in range(config.measured_runs):
        measured.extend(
            _run_round(
                "measured",
                round_index,
                cases,
                config=config,
                target=target,
                writer=writer,
            )
        )
    wall_seconds = time.perf_counter() - started
    summary = summarize_benchmark(
        latencies_ms=measured,
        wall_seconds=wall_seconds,
        expected_runs=config.measured_runs * len(cases),
        power_samples=power_samples,
    )
    return TargetRunResult(
        config=config,
        warmup_rounds=config.warmup_runs,
        measured_rounds=config.measured_runs,
        summary=summary,
    )


def compare_target_results(
    openclaw: TargetRunResult,
    gpu: TargetRunResult,
) -> BenchmarkComparison:
    assert_comparable(openclaw.config, gpu.config)
    openclaw_success = float(openclaw.summary["success_rate"])
    gpu_success = float(gpu.summary["success_rate"])
    openclaw_latency = openclaw.summary["latency_ms"]
    gpu_latency = gpu.summary["latency_ms"]
    if not isinstance(openclaw_latency, Mapping) or not isinstance(gpu_latency, Mapping):
        raise ValueError("基准延迟统计结构无效")
    openclaw_p95_value = openclaw_latency.get("p95")
    gpu_p95_value = gpu_latency.get("p95")
    openclaw_p95 = float(openclaw_p95_value) if openclaw_p95_value is not None else None
    gpu_p95 = float(gpu_p95_value) if gpu_p95_value is not None else None
    openclaw_throughput = float(openclaw.summary["throughput_per_second"])
    gpu_throughput = float(gpu.summary["throughput_per_second"])
    faster_latency = (
        openclaw_p95 is not None and gpu_p95 is not None and openclaw_p95 < gpu_p95
    )
    higher_throughput = openclaw_throughput > gpu_throughput
    status: Literal["passed", "failed"] = (
        "passed"
        if openclaw_success >= gpu_success and (faster_latency or higher_throughput)
        else "failed"
    )
    return BenchmarkComparison(
        status=status,
        openclaw_success_rate=openclaw_success,
        gpu_success_rate=gpu_success,
        openclaw_p95=openclaw_p95,
        gpu_p95=gpu_p95,
        openclaw_throughput=openclaw_throughput,
        gpu_throughput=gpu_throughput,
    )
