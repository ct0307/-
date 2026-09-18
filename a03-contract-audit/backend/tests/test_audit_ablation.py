import json

import pytest

from evaluation.audit_ablation import compare_ablation_runs
from evaluation.cli import main


def _run(version: str, *, model: str = "model-1") -> dict:
    return {
        "version": version,
        "frozen_context": {
            "model_version": model,
            "knowledge_base_version": "kb-1",
            "dataset_version": "gold-1",
            "temperature": 0,
            "environment": "local",
        },
        "component_versions": {
            "prompt_version": f"prompt-{version}",
            "rule_version": "rules-1",
            "reranker_version": "disabled",
            "support_validator_version": "support-v3",
        },
        "input_hashes": {"gold_sha256": "a" * 64},
        "overall": {"risk_f1": 0.8, "p95_latency_ms": None},
    }


def test_ablation_rejects_different_frozen_context():
    runs = [_run(f"V{i}") for i in range(5)]
    runs[3]["frozen_context"]["model_version"] = "different"
    with pytest.raises(ValueError, match="冻结上下文"):
        compare_ablation_runs(runs)


def test_ablation_requires_exact_v0_to_v4_set():
    with pytest.raises(ValueError, match="V0-V4"):
        compare_ablation_runs([_run(f"V{i}") for i in range(4)])


def test_ablation_preserves_unmeasured_as_null():
    result = compare_ablation_runs([_run(f"V{i}") for i in range(5)])
    assert result["runs"][0]["overall"]["p95_latency_ms"] is None
    assert result["runs"][1]["delta_previous"]["p95_latency_ms"] is None


def test_ablation_cli_writes_evidence(tmp_path):
    paths = []
    for index in range(5):
        path = tmp_path / f"v{index}.json"
        path.write_text(json.dumps(_run(f"V{index}")), encoding="utf-8")
        paths.append(path)
    args = ["audit-ablation"]
    for path in paths:
        args.extend(["--run", str(path)])
    args.extend(["--runs-root", str(tmp_path), "--run-id", "ablation-1"])
    assert main(args) == 0
    assert (tmp_path / "ablation-1" / "manifest.json").exists()
    assert (tmp_path / "ablation-1" / "audit-ablation.jsonl").exists()
    assert (tmp_path / "ablation-1" / "report.md").exists()
