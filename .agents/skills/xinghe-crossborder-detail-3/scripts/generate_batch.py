#!/usr/bin/env python3
"""Batch wrapper for generate_image.py.

Reads prompt .txt files from a directory and generates one image per prompt
with a consistent size/resolution.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch generate ecommerce detail modules.")
    parser.add_argument("--prompt-dir", required=True, help="Directory containing module prompt .txt files.")
    parser.add_argument("--image", action="append", help="Product/reference image path; repeatable.")
    parser.add_argument("--output-dir", default="generated-images", help="Output directory.")
    parser.add_argument("--env-file", help="Optional .env path.")
    parser.add_argument("--size", default="16:9", help="Default 16:9 for cross-border detail pages.")
    parser.add_argument("--resolution", default="2k", choices=("1k", "2k", "4k"))
    parser.add_argument("--format", default="png", choices=("png", "jpeg", "webp"))
    parser.add_argument("--python", default=sys.executable or "python", help="Python executable.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    prompt_dir = Path(args.prompt_dir)
    if not prompt_dir.is_dir():
        print(f"ERROR: prompt-dir not found: {prompt_dir}", file=sys.stderr)
        return 2

    script = Path(__file__).with_name("generate_image.py")
    prompts = sorted(prompt_dir.glob("*.txt"))
    if not prompts:
        print(f"ERROR: no .txt prompt files in {prompt_dir}", file=sys.stderr)
        return 2

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    failures: list[tuple[Path, int]] = []
    for index, prompt_file in enumerate(prompts, start=1):
        module_dir = output_dir / f"module-{index:02d}"
        cmd = [
            args.python,
            str(script),
            "--prompt-file",
            str(prompt_file),
            "--output-dir",
            str(module_dir),
            "--size",
            args.size,
            "--resolution",
            args.resolution,
            "--format",
            args.format,
        ]
        if args.env_file:
            cmd.extend(["--env-file", args.env_file])
        if args.image:
            for image_path in args.image:
                cmd.extend(["--image", image_path])

        print(f"[{index:02d}/{len(prompts):02d}] {prompt_file.name}")
        result = subprocess.run(cmd)
        if result.returncode != 0:
            failures.append((prompt_file, result.returncode))

    if failures:
        print("\nFailed modules:", file=sys.stderr)
        for prompt_file, code in failures:
            print(f"- {prompt_file.name}: exit {code}", file=sys.stderr)
        return 1

    print(f"\nDone. Output directory: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
