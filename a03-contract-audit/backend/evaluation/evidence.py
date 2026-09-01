"""版本化评测运行清单与追加式原始证据。"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
from typing import Any, Mapping


SCHEMA_VERSION = "1.0"
RUN_STATUSES = frozenset({"passed", "failed", "blocked", "error"})
_SAFE_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
_SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "api_key",
        "token",
        "password",
        "contract_text",
        "content",
        "raw_response",
    }
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_sensitive_key(key: Any) -> bool:
    normalized = str(key).lower().replace("-", "_")
    return normalized in _SENSITIVE_KEYS or normalized.endswith(
        ("_token", "_password", "_api_key")
    )


def redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if _is_sensitive_key(key) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _git_state() -> tuple[str, bool]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
        return commit, dirty
    except (OSError, subprocess.CalledProcessError):
        return "unknown", True


@dataclass(frozen=True)
class RunManifest:
    schema_version: str
    run_id: str
    command: str
    status: str
    created_at: str
    updated_at: str
    git_commit: str
    git_dirty: bool
    inputs: dict[str, Any]
    environment: dict[str, Any]
    modules: dict[str, str]


class EvidenceWriter:
    def __init__(self, run_dir: Path, manifest: RunManifest) -> None:
        self.run_dir = run_dir
        self.run_id = manifest.run_id
        self.command = manifest.command
        self._manifest = manifest

    @classmethod
    def create(
        cls,
        root: Path,
        *,
        run_id: str,
        command: str,
        git_commit: str | None = None,
        git_dirty: bool | None = None,
        inputs: Mapping[str, Any] | None = None,
        environment: Mapping[str, Any] | None = None,
    ) -> "EvidenceWriter":
        if not _SAFE_NAME.fullmatch(run_id):
            raise ValueError("run_id 只能包含字母、数字、点、下划线和连字符")
        if not _SAFE_NAME.fullmatch(command):
            raise ValueError("command 不是安全名称")
        if git_commit is None or git_dirty is None:
            detected_commit, detected_dirty = _git_state()
        else:
            detected_commit, detected_dirty = git_commit, git_dirty
        now = _utc_now()
        manifest = RunManifest(
            schema_version=SCHEMA_VERSION,
            run_id=run_id,
            command=command,
            status="error",
            created_at=now,
            updated_at=now,
            git_commit=git_commit if git_commit is not None else detected_commit,
            git_dirty=git_dirty if git_dirty is not None else detected_dirty,
            inputs=dict(inputs or {}),
            environment={
                "python": platform.python_version(),
                "platform": platform.platform(),
                **dict(environment or {}),
            },
            modules={},
        )
        run_dir = root / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        writer = cls(run_dir, manifest)
        writer._write_manifest_file()
        return writer

    def append(self, stream: str, payload: Mapping[str, Any]) -> None:
        if not _SAFE_NAME.fullmatch(stream):
            raise ValueError("事件流名称不是安全名称")
        event = {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "timestamp": _utc_now(),
            "payload": redact(dict(payload)),
        }
        with (self.run_dir / f"{stream}.jsonl").open("a", encoding="utf-8") as target:
            target.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
            target.flush()
            os.fsync(target.fileno())

    def write_manifest(
        self,
        *,
        status: str,
        modules: Mapping[str, str],
        inputs: Mapping[str, Any] | None = None,
        environment: Mapping[str, Any] | None = None,
    ) -> None:
        if status not in RUN_STATUSES:
            raise ValueError(f"未知运行状态: {status}")
        unknown_module_statuses = set(modules.values()) - RUN_STATUSES
        if unknown_module_statuses:
            raise ValueError(f"未知模块状态: {sorted(unknown_module_statuses)}")
        self._manifest = replace(
            self._manifest,
            status=status,
            updated_at=_utc_now(),
            modules=dict(modules),
            inputs=dict(inputs) if inputs is not None else self._manifest.inputs,
            environment=(
                {**self._manifest.environment, **dict(environment)}
                if environment is not None
                else self._manifest.environment
            ),
        )
        self._write_manifest_file()

    def _write_manifest_file(self) -> None:
        manifest_path = self.run_dir / "manifest.json"
        temporary_path = self.run_dir / "manifest.json.tmp"
        temporary_path.write_text(
            json.dumps(redact(asdict(self._manifest)), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary_path.replace(manifest_path)
