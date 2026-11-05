"""Audit a captured supplier catalog directly from source checkpoints.

The report is independent of earlier generated audit JSON and is safe to run
without network access, credentials or Playwright.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ecom_images.supplier_capture_validation import inspect_supplier_capture  # noqa: E402

DEFAULT_CAPTURE = ROOT / "data" / "supplier_captures" / "dgdeler"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse source location, coverage requirements, expected outcome and report output."""
    parser = argparse.ArgumentParser(description="独立校验原始分页和详情文件，不信任旧的完整性报告。")
    parser.add_argument("--capture-dir", type=Path, default=DEFAULT_CAPTURE)
    parser.add_argument("--require-details", action="store_true")
    parser.add_argument("--expect-status", choices=("complete", "partial"), default="complete")
    parser.add_argument("--report", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Print validation result and exit nonzero on unexpected/incomplete coverage."""
    args = parse_args(argv)
    try:
        report = inspect_supplier_capture(args.capture_dir, require_details=args.require_details)
        if args.report:
            target = args.report.expanduser().absolute()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["status"] == args.expect_status else 2
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(f"独立采集完整性检查失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
