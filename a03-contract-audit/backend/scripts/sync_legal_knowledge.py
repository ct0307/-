"""检查、预演或同步权威法律知识库。"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from app.db.session import SessionLocal
from app.services.rag.legal_sync import apply_legal_sync, plan_legal_sync
from scripts.verify_legal_sources import verify_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="同步权威法律知识库")
    parser.add_argument("--manifest", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check-only", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--replace-legacy", action="store_true")
    args = parser.parse_args()

    if args.check_only:
        result = verify_manifest(args.manifest)
    else:
        db = SessionLocal()
        try:
            if args.apply:
                report = apply_legal_sync(
                    db, args.manifest, replace_legacy=args.replace_legacy
                )
            else:
                report = plan_legal_sync(
                    db, args.manifest, replace_legacy=args.replace_legacy
                )
            result = asdict(report)
        finally:
            db.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
