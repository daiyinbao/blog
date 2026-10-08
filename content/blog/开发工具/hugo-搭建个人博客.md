+++
title = "用 Hugo 搭建一个知识库风格的个人博客"
date = 2026-10-06
weight = 1
tags = ["Hugo", "博客", "教程"]
summary = "从零开始，用 Hugo 复刻一个带文档树、全文搜索、大纲导航和明暗主题的知识库风格博客。"
+++

## 为什么选择 Hugo

Hugo 是用 Go 编写的静态站点生成器，最大的特点就是**快**。几千篇文章也能在几百毫秒内构建完成，
而且只需要一个二进制文件，不需要安装运行时依赖。

相比 Hexo、Jekyll，它更适合我这种「写一堆笔记，然后希望它们有条理地展示出来」的场景。

## 目录结构

一个典型的 Hugo 站点长这样：

```text
my_blog/
├── hugo.toml          # 站点配置
├── content/           # 所有 Markdown 文章
│   └── blog/
│       ├── Java基础/
│       └── 随笔/
├── layouts/           # 页面模板
├── assets/            # 需要被处理的 CSS / JS
└── static/            # 原样拷贝的资源（头像、图片）
```

> 约定优于配置：`content/` 下的每一级文件夹都会自动变成一个栏目。

## 写第一篇文章

在 `content/blog/Java基础/` 下新建一个 `.md` 文件，开头写上元信息：

```toml
+++
title = "文章标题"
date = 2026-10-06
tags = ["标签一", "标签二"]
+++

正文从这里开始……
```

## 本地预览

```bash
hugo server -D
```

打开 `http://localhost:1313` 就能看到效果，修改文件会自动刷新。

## 常用命令速查

| 命令 | 作用 |
| --- | --- |
| `hugo server -D` | 本地预览（含草稿） |
| `hugo` | 生成静态文件到 `public/` |
| `hugo new content/blog/xxx.md` | 新建文章 |
| `hugo --minify` | 生成并压缩输出 |

## 部署到 GitHub Pages

把生成的 `public/` 目录推到仓库的 `gh-pages` 分支，或者在仓库设置里选择
**GitHub Actions** 作为 Pages 的来源，然后提交 `.github/workflows/hugo.yml` 即可自动部署。

到此为止，一个属于自己的知识库博客就跑起来了。
