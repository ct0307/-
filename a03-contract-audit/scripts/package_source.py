"""打包当前可审核源码，排除本地环境和业务数据，不覆盖已有压缩包。"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = frozenset({
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".planning", ".quality-gate", ".superpowers", ".codex", ".agents",
    "outputs", "storage", "logs", "dist", "build", "test-results", "playwright-report",
    "evaluation-runs", ".vite", "rendered", "model_cache", "models_cache", ".cache", "hf-cache",
})
EXCLUDED_SUFFIXES = frozenset({
    ".db", ".sqlite", ".sqlite3", ".log", ".pyc", ".pyo", ".zip", ".key", ".pem",
    ".p12", ".pfx", ".safetensors", ".tsbuildinfo", ".bin", ".pt", ".pth", ".onnx",
})


def allowed_path(path: Path) -> bool:
    """示例配置可以分发，真实环境配置和本地产物必须排除。"""
    lowered = Path(*(part.casefold() for part in path.parts))
    name = lowered.name
    return (not EXCLUDED_PARTS.intersection(lowered.parts)
            and lowered.suffix not in EXCLUDED_SUFFIXES
            and not name.startswith("~$")
            and (name == ".env.example" or not (name == ".env" or name.startswith(".env.") or name.endswith(".env"))))


def _git(*args: str) -> bytes:
    return subprocess.check_output(("git", "-C", str(PROJECT_ROOT), *args))


def package_source(output: Path) -> dict:
    output = output.resolve()
    if output.exists():
        raise FileExistsError("目标压缩包已存在，请使用新的文件名")
    repository = Path(_git("rev-parse", "--show-toplevel").decode("utf-8").strip()).resolve()
    relative_project = PROJECT_ROOT.relative_to(repository)
    paths = _git("ls-files", "--cached", "--others", "--exclude-standard", "--full-name", "-z", "--", f":(top){relative_project.as_posix()}")
    entries = []
    for item in sorted(set(paths.decode("utf-8").split("\0")) - {""}):
        relative = Path(item)
        if not allowed_path(relative):
            continue
        source = repository / relative
        if source.is_symlink() or not source.is_file() or not source.resolve().is_relative_to(PROJECT_ROOT):
            raise ValueError(f"源码路径不可打包：{relative.as_posix()}")
        data = source.read_bytes()
        entries.append((relative.as_posix(), data))
    if not entries:
        raise ValueError("没有找到可分发源码")
    manifest = {
        "schema_version": "source-package-v1",
        "base_commit": _git("rev-parse", "HEAD").decode().strip(),
        "branch": _git("branch", "--show-current").decode().strip(),
        "snapshot": "当前工作区文件内容，包含尚未提交的本轮改动",
        "files": [{"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()} for name, data in entries],
        "limits": "不含真实环境配置、合同原件、数据库、日志、依赖和模型缓存；回归测试不等于真实业务准确率",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "x", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in entries:
            archive.writestr(name, data)
        archive.writestr(f"{relative_project.as_posix()}/SOURCE_MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    with ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise ValueError("压缩包完整性校验失败")
        for item in manifest["files"]:
            if hashlib.sha256(archive.read(item["path"])).hexdigest() != item["sha256"]:
                raise ValueError("源码文件摘要校验失败")
    return {"path": str(output), "files": len(entries), "bytes": output.stat().st_size,
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="新的源码ZIP路径")
    args = parser.parse_args()
    print(json.dumps(package_source(args.output), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
