#!/usr/bin/env python3
"""为「带图片的文章」生成可下载的 zip 包（index.md + assets/）。

Hugo 本身不能输出二进制文件，所以这一步在 hugo 构建之后跑，扫描 public/
里已经生成好的文章目录，就地打包成 index.zip。zip 内部结构：

    index.md
    assets/xxx.webp
    assets/yyy.webp

解压后直接用 Markdown 编辑器打开 index.md，图片就能正常显示。

用法（一般由 deploy.sh / 手动构建后调用）：
    python3 scripts/make-zips.py [public目录] [--clean]
"""
import argparse
import os
import sys
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def has_local_images(md_path):
    try:
        text = open(md_path, encoding="utf-8").read()
    except OSError:
        return False
    return "](assets/" in text


def make_zip(article_dir, clean=False):
    md = os.path.join(article_dir, "index.md")
    assets = os.path.join(article_dir, "assets")
    if not os.path.isfile(md) or not os.path.isdir(assets):
        return None

    # 收集实际被引用的图片，避免把废弃文件也打进去
    text = open(md, encoding="utf-8").read()
    used = []
    for name in sorted(os.listdir(assets)):
        if f"](assets/{name})" in text:
            used.append(name)
    if not used:
        return None

    zip_path = os.path.join(article_dir, "index.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(md, "index.md")
        for name in used:
            zf.write(os.path.join(assets, name), f"assets/{name}")
    return zip_path, len(used)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("public", nargs="?", default="public")
    ap.add_argument("--clean", action="store_true",
                    help="清理没有图片的文章里可能残留的 zip")
    args = ap.parse_args()

    root = args.public
    if not os.path.isabs(root):
        root = os.path.join(REPO, root)
    if not os.path.isdir(root):
        print(f"找不到目录：{root}", file=sys.stderr)
        return 1

    made = skipped = 0
    for dirpath, _dirs, files in os.walk(root):
        if "index.md" not in files:
            continue
        assets = os.path.join(dirpath, "assets")
        zip_path = os.path.join(dirpath, "index.zip")

        if not os.path.isdir(assets) or not has_local_images(os.path.join(dirpath, "index.md")):
            if args.clean and os.path.isfile(zip_path):
                os.remove(zip_path)
            skipped += 1
            continue

        result = make_zip(dirpath)
        if result:
            path, n = result
            made += 1
            print(f"  {os.path.relpath(dirpath, root)}  ({n} 张图, "
                  f"{os.path.getsize(path)/1024:.0f} KB)")
        else:
            skipped += 1

    print(f"\n生成 {made} 个 zip，跳过 {skipped} 篇（无图片）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
