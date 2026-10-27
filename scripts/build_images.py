#!/usr/bin/env python3
"""在仓库根目录执行：python scripts/build_images.py --config configs/example.json"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ecom_images.generator import run_config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="工业五金淘宝/天猫图片批量排版")
    parser.add_argument("--config", required=True, type=Path, help="JSON 配置路径")
    parser.add_argument("--base-dir", type=Path, default=ROOT,
                        help="source/output 相对路径的基准目录（默认仓库根目录）")
    parser.add_argument("--report", type=Path, default=None,
                        help="可选：输出 JSON 制作报告")
    args = parser.parse_args()
    try:
        results = run_config(args.config.resolve(), args.base_dir)
        for result in results:
            print(f"[OK] {result['mode']:12} {result['width']}x{result['height']} "
                  f"{result['bytes'] / 1024:.0f}KB  {result['file']}")
        if args.report:
            dest = args.report.resolve()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"成功制作 {len(results)} 张图片")
        return 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
