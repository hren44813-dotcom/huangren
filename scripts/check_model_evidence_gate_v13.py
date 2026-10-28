#!/usr/bin/env python3
"""只读核对型号资料，并检查参数能否用于电商图片/详情文案。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ecom_images.database_v9 import DEFAULT_DB  # noqa: E402
from ecom_images.model_evidence_reconciliation_v13 import (  # noqa: E402
    evaluate_content_gate,
    reconcile_model_evidence,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="按型号检索来源页、SKU映射和参数冲突；可选执行商品内容证据门禁。"
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--model-code", required=True)
    parser.add_argument("--manufacturer", default="")
    parser.add_argument("--sku-id", default="", help="可选：指定SKU并要求已确认型号映射")
    parser.add_argument("--require-attribute", action="append", default=[],
                        help="要用于商品内容的参数名称，可重复指定；例如 --require-attribute 扭矩")
    parser.add_argument("--limit", type=int, default=100)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.require_attribute:
            result = evaluate_content_gate(
                args.database, model_code=args.model_code,
                manufacturer_name=args.manufacturer, sku_id=args.sku_id,
                required_attributes=args.require_attribute,
            )
            result["mode"] = "content_gate"
        else:
            result = reconcile_model_evidence(
                args.database, model_code=args.model_code,
                manufacturer_name=args.manufacturer, limit=args.limit,
            )
            result["mode"] = "reconciliation"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("allowed", True) else 2
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({
            "allowed": False, "status": "error", "model_code": args.model_code,
            "error": str(exc),
        }, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
