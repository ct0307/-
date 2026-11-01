"""原型的运行身份、输入限制和可替换操作协议。"""
from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Protocol, TypedDict


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


class StaleRun(RuntimeError):
    """运行身份或执行权已经失效。"""


class AccessDenied(RuntimeError):
    """人工恢复不符合授权或幂等条件。"""


class FlowIssue(RuntimeError):
    """可以保存为人工待核原因的流程问题。"""


@dataclass(frozen=True)
class RunIdentity:
    contract_id: int
    job_id: int
    generation: int
    fingerprint: str
    contract_hash: str
    knowledge_revision: int
    role: str
    window_id: str

    @classmethod
    def create(cls, *, contract: str, **values):
        return cls(contract_hash=fingerprint(contract), **values)

    @property
    def thread_id(self):
        return fingerprint(asdict(self))


@dataclass(frozen=True)
class Limits:
    max_calls: int
    max_tokens: int
    deadline: float
    max_pages: int = 8

    def __post_init__(self):
        if self.max_calls < 0 or self.max_tokens < 0 or not 1 <= self.max_pages <= 8:
            raise ValueError('预算非负，分页上限必须在 1 到 8 之间')


@dataclass(frozen=True)
class OperationResult:
    payload: dict
    usage_tokens: int = 0


class Operations(Protocol):
    def discover(self, page: int, accepted: list[dict]) -> OperationResult: ...
    def enrich(self, finding: dict) -> OperationResult: ...
    def review(self, candidates: list[dict]) -> OperationResult: ...


class PilotState(TypedDict, total=False):
    page: int
    findings: list[dict]
    candidates: list[dict]
    has_more: bool
    issues: list[str]
    conflict_ids: list[str]
    status: str
    decision: str
    last_node: str
