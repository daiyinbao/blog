#!/usr/bin/env python3
"""把过宽的图片等比缩小到指定宽度（默认 2500），原地替换。

只处理超过 --max-width 的图片，未超宽的原样保留，避免无谓的重新编码。
截图/示意图类图片在阅读区内 2000~2500 宽已足够清晰。

用法：
    python3 scripts/shrink-oversized.py --dry-run
    python3 scripts/shrink-oversized.py --max-width 2500
"""
import argparse
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTENT = os.path.join(REPO, "content")
EXTS = {".webp", ".png", ".jpg", ".jpeg"}


def dimension(path):
    out = subprocess.run(["identify", "-format", "%w %h", path],
                         capture_output=True, text=True)
    if out.returncode != 0:
        return None
    w, h = out.stdout.split()
    return int(w), int(h)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-width", type=int, default=2500)
    ap.add_argument("--quality", type=int, default=85)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    done = skipped = 0
    before_total = after_total = 0

    for root, _dirs, files in os.walk(CONTENT):
        if os.path.basename(root) != "assets":
            continue
        for name in sorted(files):
            ext = os.path.splitext(name)[1].lower()
            if ext not in EXTS:
                continue
            path = os.path.join(root, name)
            dim = dimension(path)
            if not dim:
                continue
            w, _h = dim
            before = os.path.getsize(path)
            if w <= args.max_width:
                skipped += 1
                continue
            if args.dry_run:
                print(f"  [dry] {w}px -> {args.max_width}px  {name}")
                done += 1
                continue
            tmp = path + ".tmp" + ext
            cmd = ["magick", path, "-resize", f"{args.max_width}x>",
                   "-quality", str(args.quality), tmp]
            subprocess.run(cmd, check=True, capture_output=True)
            after = os.path.getsize(tmp)
            if after < before:
                shutil.move(tmp, path)
                before_total += before
                after_total += after
                done += 1
                print(f"  {w}px -> {args.max_width}px  {name}  "
                      f"{before/1024:.0f} KB -> {after/1024:.0f} KB")
            else:
                os.remove(tmp)
                skipped += 1

    print()
    print(f"缩小 {done} 张，跳过 {skipped} 张")
    if before_total:
        print(f"体积 {before_total/1048576:.1f} MB -> {after_total/1048576:.1f} MB "
              f"(省 {(1-after_total/before_total)*100:.0f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
