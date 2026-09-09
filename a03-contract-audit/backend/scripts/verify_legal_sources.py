"""只读校验权威法源清单及正文。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.rag.legal_sources import (
    load_manifest,
    parse_articles,
    validate_article_set,
    verify_source_file,
)


def verify_manifest(manifest_path: Path) -> dict:
    specs = load_manifest(manifest_path)
    source_reports = []
    for spec in specs:
        text = verify_source_file(spec, manifest_path.parent)
        articles = parse_articles(spec, text)
        validate_article_set(spec, articles)
        source_reports.append({
            "source_id": spec.source_id,
            "title": spec.title,
            "article_count": len(articles),
            "first_article": articles[0].article_number,
            "last_article": articles[-1].article_number,
            "file_sha256": spec.file_sha256,
        })
    return {
        "schema_version": 1,
        "source_count": len(source_reports),
        "article_count": sum(item["article_count"] for item in source_reports),
        "sources": source_reports,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="校验权威法源文件，不连接数据库")
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(verify_manifest(args.manifest), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
