#!/usr/bin/env python3
"""把简悦（SimpRead）保存的 HTML 教程转成 Hugo page bundle。

用法：
    python3 scripts/simpread-to-hugo.py <html目录> <目标栏目相对路径>

例：
    python3 scripts/simpread-to-hugo.py ~/download/linux_note/教程 "Agent开发/Agent基础"

处理内容：
- 正文取 <sr-rd-content>
- 图片取 sr-org-src 原图，下载到各文章的 assets/，正文改成本地相对路径
- 代码块按内容猜测语言（java/xml/yaml/sql/bash/json，猜不中就不标）
- 清理简悦的防拷贝水印（混在正文里的 base64 串）
- 生成 TOML front matter，标题去掉 "N - " 前缀
需要 Python 依赖：beautifulsoup4 markdownify
"""
import glob
import os
import re
import sys
import unicodedata
import urllib.request

from bs4 import BeautifulSoup
import markdownify

# ── 水印清理 ────────────────────────────────────────────────
WATERMARK = re.compile(r"[A-Za-z0-9+/]{20,}={0,2}")


def looks_like_watermark(s):
    if len(s) < 20 or not any(c.isdigit() for c in s):
        return False
    if not any(c in s for c in "+/="):
        return False
    return any(c.isupper() for c in s) and any(c.islower() for c in s)


def strip_watermarks(text):
    def repl(m):
        tok = m.group(0)
        return "" if looks_like_watermark(tok) else tok
    out = WATERMARK.sub(repl, text)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"[ \t]+([，。；：！？、）])", r"\1", out)
    return out


def clean_md_watermarks(md):
    """只在代码块之外、且不碰链接/行内代码的前提下清理水印。"""
    parts = re.split(r"(```[\s\S]*?```)", md)
    for i, part in enumerate(parts):
        if part.startswith("```"):
            continue
        placeholders = []

        def stash(m):
            placeholders.append(m.group(0))
            return f"\x00{len(placeholders) - 1}\x00"

        part = re.sub(r"\]\([^)]*\)", stash, part)      # markdown 链接 / 图片目标
        part = re.sub(r"`[^`]*`", stash, part)           # 行内代码
        part = strip_watermarks(part)
        for j, val in enumerate(placeholders):
            part = part.replace(f"\x00{j}\x00", val)
        parts[i] = part
    return "".join(parts)


# ── 语言猜测 ────────────────────────────────────────────────
def guess_lang(text):
    s = text.strip()
    if not s:
        return ""
    head = s[:400]
    if head.lstrip().startswith("<") and re.search(r"</?[A-Za-z][\w.:-]*", head):
        return "xml"
    if re.search(r"^\s*(spring|server|mybatis|springdoc|logging|knife4j)\s*:", s, re.M):
        return "yaml"
    if (re.search(r"\b(public|private|protected)\s+[\w<>\[\], ]+\s+\w+\s*\(", s)
            or re.search(r"\b(class|interface|enum|record)\s+\w+", s)
            or re.search(r"^\s*(import|package)\s+[\w.]+\s*;", s, re.M)
            or re.search(r"@(Override|RestController|Service|Component|Autowired|Bean|Test)\b", s)):
        return "java"
    if re.search(r"\b(SELECT|INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|CREATE\s+TABLE)\b", s, re.I):
        return "sql"
    if re.search(r"^\s*(npm|yarn|pnpm|mvn|gradle|docker|git|curl|wget|cd|ls|mkdir|sudo|apt|brew|systemctl)\b", s, re.M):
        return "bash"
    if re.match(r"^\s*[\[{]", s) and re.search(r'["\w]+\s*:', s):
        return "json"
    return ""


def clean_invisible(s):
    return "".join(ch for ch in s if ch not in "\u200b\u200c\u200d\u200e\u200f\u2060\ufeff")


# ── 单篇转换 ────────────────────────────────────────────────
def convert(path):
    soup = BeautifulSoup(open(path, encoding="utf-8").read(), "html.parser")
    content = soup.find("sr-rd-content")
    title_el = soup.find("sr-rd-title")
    desc_el = soup.find("sr-rd-desc")
    if content is None:
        raise RuntimeError(f"找不到 <sr-rd-content>: {path}")

    for el in content.find_all(attrs={"data-id": True}):
        del el["data-id"]
    for el in content.find_all(id=True):
        del el["id"]

    codes = []
    for idx, pre in enumerate(content.find_all("pre")):
        text = clean_invisible(pre.get_text()).replace("\xa0", " ").rstrip("\n") + "\n"
        lang = guess_lang(text)
        token = f"@@CODEBLOCK{idx}@@"
        codes.append((token, lang, text))
        ph = soup.new_tag("p")
        ph.string = token
        pre.replace_with(ph)

    images = []
    for idx, img in enumerate(content.find_all("img")):
        src = img.get("sr-org-src") or img.get("src", "")
        token = f"@@IMAGESLOT{idx}@@"
        images.append((token, src))
        ph = soup.new_tag("p")
        ph.string = token
        holder = img.find_parent("div", class_="sr-rd-content-center") or img
        holder.replace_with(ph)

    md = markdownify.markdownify(str(content), heading_style="ATX", bullets="-", strip=["span", "a"])
    md = clean_invisible(md)

    for token, lang, text in codes:
        body = "```" + lang + "\n" + text + "```"
        md = re.sub(r"^.*" + re.escape(token) + r".*$", lambda m: body, md, count=1, flags=re.M)
    for token, src in images:
        md = re.sub(r"^.*" + re.escape(token) + r".*$", lambda m: f"@@ORGSRC{src.replace(chr(47),chr(124))}@@", md,
                    count=1, flags=re.M)

    md = clean_md_watermarks(md)
    md = re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"
    return {
        "title": title_el.get_text(strip=True) if title_el else "",
        "desc": desc_el.get_text(" ", strip=True) if desc_el else "",
        "md": md,
        "images": [src for _, src in images],
    }


# ── 批量转换 ────────────────────────────────────────────────
def fetch(url, dest):
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        f.write(r.read())


def toml_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    src_dir, target = sys.argv[1], sys.argv[2]
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    module = os.path.join(repo, "content/blog", target)
    os.makedirs(module, exist_ok=True)

    files = sorted(glob.glob(os.path.join(src_dir, "*.html")),
                   key=lambda p: int(re.search(r"simpread-(\d+)", os.path.basename(p)).group(1)))

    for path in files:
        r = convert(path)
        raw_title = re.sub(r"\s*-\s*AI 超级智能体项目教程.*$", "", r["title"]).strip()
        m = re.match(r"(\d+)\s*-\s*(.+)", raw_title)
        n = int(m.group(1)) if m else 0
        name = m.group(2).strip() if m else raw_title

        art_dir = os.path.join(module, name)
        assets = os.path.join(art_dir, "assets")
        os.makedirs(assets, exist_ok=True)

        md = r["md"]
        for src in r["images"]:
            fn = os.path.basename(src.split("?")[0])
            fetch(src, os.path.join(assets, fn))
            md = md.replace(f"@@ORGSRC{src.replace(chr(47),chr(124))}@@", f"![](assets/{fn})")
        if "@@ORGSRC" in md:
            raise RuntimeError("有图片占位符没替换：" + name)

        front = ("+++\n"
                 f"title = {toml_str(name)}\n"
                 f"date = {toml_str('2026-10-07T12:00:00+08:00')}\n"
                 f"weight = {n}\n"
                 f"summary = {toml_str(r['desc'])}\n"
                 "+++\n\n")
        open(os.path.join(art_dir, "index.md"), "w", encoding="utf-8").write(front + md)
        print(f"  [{n}] {name}: {len(md)} chars, {len(r['images'])} imgs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
