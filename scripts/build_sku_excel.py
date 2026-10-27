"""命令行批量导出：python scripts/build_sku_excel.py --excel ... --images ... --out ..."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ecom_images.sku_batch import build_sku_batch, unpack_image_zip  # noqa: E402
from ecom_images.sku_layout_v4 import layout_from_json  # noqa: E402
from ecom_images.workflow import UploadedPicture  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="根据 Excel SKU 清单和图片 ZIP 批量生成 SKU 规格图")
    parser.add_argument("--excel", type=Path, required=True, help="SKU 清单 XLSX")
    parser.add_argument("--images", type=Path, required=True, help="产品照片 ZIP（文件名和表格一致）")
    parser.add_argument("--out", type=Path, default=Path("output/sku_excel_result.zip"), help="最终 ZIP 输出")
    parser.add_argument("--layout", type=Path, help="V4 布局 JSON 文件（在网页中导出）")
    parser.add_argument("--clean-background", type=Path,
                        help="已人工清除旧商品和文字的1440×1440净背景（需配合--layout）")
    args = parser.parse_args()
    try:
        pictures = unpack_image_zip(args.images.read_bytes())
        if args.clean_background and not args.layout:
            raise ValueError("--clean-background 必须与 --layout 一起使用")
        layout = layout_from_json(args.layout.read_bytes()) if args.layout else None
        clean = UploadedPicture(args.clean_background.name, args.clean_background.read_bytes()) if args.clean_background else None
        result = build_sku_batch(args.excel.read_bytes(), pictures,
                                 custom_layout=layout, clean_template=clean)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(result.zip_bytes())
        print(f"生成成功 {result.successes} 张，失败 {result.failures} 行。报告在 ZIP 的 sku_import_report.csv")
        return 0 if result.failures == 0 else 2
    except (ValueError, OSError) as exc:
        print(f"批量生成失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
