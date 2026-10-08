#!/usr/bin/env python3
"""生成 assets/css/syntax.css（亮色 github + 暗色 monokai）。

亮色规则统一加 `:root:not([data-theme="dark"])` 前缀：这样在暗色模式下
亮色规则整体失效，Chroma 没在 monokai 里定义的 token（如包名 .nn）会继承
`.chroma` 的前景色，而不会沿用 github 的深灰色导致看不清。

用法：在仓库根目录执行  python3 scripts/gen-syntax.py
"""
import os
import pathlib
import re
import subprocess

HUGO = os.environ.get("HUGO", os.path.expanduser("~/.local/bin/hugo"))


def gen(style):
    return subprocess.run(
        [HUGO, "gen", "chromastyles", f"--style={style}"],
        capture_output=True, text=True, check=True,
    ).stdout


def scope(css, prefix):
    out = []
    for line in css.splitlines():
        s = line.rstrip()
        if not s or s.strip().startswith("/* Generated using"):
            continue
        m = re.match(r"(/\*[^*]*\*/\s*)?(.*?)\s*\{", s)
        if not m:
            out.append(s)
            continue
        comment, sel = m.group(1) or "", m.group(2)
        rest = s[m.end() - 1:]  # 从 '{' 开始
        out.append(f"{comment}{prefix} {sel} {rest}".strip())
    return "\n".join(out)


def main():
    light = scope(gen("github"), ':root:not([data-theme="dark"])')
    dark = scope(gen("monokai"), '[data-theme="dark"]')

    header = (
        "/* 语法高亮：亮色 github / 暗色 monokai\n"
        "   由 scripts/gen-syntax.py 生成，勿手改。\n"
        "   亮色规则仅非暗色时生效，避免未覆盖的 token 沿用亮色深色字看不见。 */\n\n"
        "/* ── 亮色 GitHub ───────────────────────────────────────── */\n"
    )
    mid = "\n\n/* ── 暗色 Monokai ──────────────────────────────────────── */\n"

    out = pathlib.Path(__file__).resolve().parents[1] / "assets/css/syntax.css"
    out.write_text(header + light + mid + dark + "\n", encoding="utf-8")
    print(f"written {out}")


if __name__ == "__main__":
    main()
