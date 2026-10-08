#!/usr/bin/env python3
"""把文章资源目录里的图片统一压缩为 WebP，并同步更新 Markdown 里的引用。

特点：
- 保持原始分辨率（截图类图片缩小后会糊）
- 只做有损 WebP 转换（quality 可调，默认 85），体积通常能降到 40%~60%
- 转换后自动改写同目录文章 index.md 里的图片引用
- 默认保留原图（--delete-originals 才会删），可随时回滚

用法：
    python3 scripts/optimize-images.py                    # 处理全部文章
    python3 scripts/optimize-images.py --quality 80
    python3 scripts/optimize-images.py --delete-originals
    python3 scripts/optimize-images.py --dry-run
"""
import argparse
import os
import re
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTENT = os.path.join(REPO, "content")
SUPPORTED = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".gif"}


def find_asset_dirs():
    for root, dirs, _files in os.walk(CONTENT):
        if os.path.basename(root) == "assets":
            yield root


def convert(src, dst, quality, max_width=0):
    cmd = ["magick", src]
    if max_width:
        cmd += ["-resize", f"{max_width}x>"]
    cmd += ["-quality", str(quality), dst]
    subprocess.run(cmd, check=True, capture_output=True)


def relink_only():
    """把 Markdown 里 assets/xxx.png 改成 assets/xxx.webp（仅当 webp 已存在）。"""
    changed = 0
    for root, _dirs, files in os.walk(CONTENT):
        assets = os.path.join(root, "assets")
        for fn in files:
            if not fn.endswith(".md"):
                continue
            path = os.path.join(root, fn)
            text = open(path, encoding="utf-8").read()
            orig = text

            def repl(m):
                name = m.group(1)
                base, ext = os.path.splitext(name)
                if ext.lower() in SUPPORTED:
                    candidate = base + ".webp"
                    if os.path.isfile(os.path.join(assets, candidate)):
                        return f"](assets/{candidate})"
                return m.group(0)

            text = re.sub(r"\]\(assets/([^)]+)\)", repl, text)
            if text != orig:
                open(path, "w", encoding="utf-8").write(text)
                changed += 1
                print(f"  更新 {path}")
    print(f"共更新 {changed} 个 Markdown 文件")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quality", type=int, default=85)
    ap.add_argument("--max-width", type=int, default=0,
                    help="超过该宽度的图片等比缩小（0=不缩放）。阅读区宽度有限，"
                         "对截图类图片 2000~2500 足够清晰，且能显著省流量")
    ap.add_argument("--delete-originals", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--relink-only", action="store_true",
                    help="跳过转换，只把 Markdown 里指向 .png/.jpg 的引用改成同名 .webp")
    args = ap.parse_args()

    if args.relink_only:
        return relink_only()

    total_before = total_after = 0
    converted = 0
    renames = {}   # 绝对路径原图 -> 新 webp 文件名

    for assets in sorted(find_asset_dirs()):
        for name in sorted(os.listdir(assets)):
            src = os.path.join(assets, name)
            if not os.path.isfile(src):
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext == ".webp":
                continue  # 已优化过的 webp 不重复处理，避免反复降质
            if ext not in SUPPORTED:
                continue
            dst_name = os.path.splitext(name)[0] + ".webp"
            dst = os.path.join(assets, dst_name)
            before = os.path.getsize(src)
            if args.dry_run:
                print(f"  [dry] {name} -> {dst_name}  ({before/1024:.0f} KB)")
                continue
            convert(src, dst, args.quality, args.max_width)
            after = os.path.getsize(dst)
            # 文件名变了（扩展名/基名变化）就必须更新 Markdown 引用
            if name != dst_name:
                renames[src] = dst_name
            total_before += before
            total_after += after
            converted += 1
            if args.delete_originals:
                os.remove(src)
            print(f"  {name} -> {dst_name}  {before/1024:.0f} KB -> {after/1024:.0f} KB")

    if args.dry_run:
        return 0

    # 更新文章 markdown 里的引用
    changed = 0
    for root, _dirs, files in os.walk(CONTENT):
        for fn in files:
            if not fn.endswith(".md"):
                continue
            path = os.path.join(root, fn)
            text = open(path, encoding="utf-8").read()
            orig = text
            for src, new_name in renames.items():
                if os.path.dirname(src) != os.path.join(root, "assets"):
                    continue
                old_name = os.path.basename(src)
                if old_name == new_name:
                    continue
                text = text.replace(f"](assets/{old_name})", f"](assets/{new_name})")
            if text != orig:
                open(path, "w", encoding="utf-8").write(text)
                changed += 1

    print()
    print(f"转换 {converted} 张：{total_before/1048576:.1f} MB -> {total_after/1048576:.1f} MB "
          f"(省 {(1-total_after/total_before)*100:.0f}%)")
    print(f"更新 {changed} 个 Markdown 文件")
    if not args.delete_originals:
        print("原图已保留；确认无误后可加 --delete-originals 重新执行来清理")
    return 0


if __name__ == "__main__":
    sys.exit(main())
