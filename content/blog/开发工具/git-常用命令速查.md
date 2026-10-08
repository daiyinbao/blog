+++
title = "Git 常用命令速查"
date = 2026-09-18
weight = 2
tags = ["Git", "速查"]
summary = "把日常开发中最常用的 Git 命令整理成一张速查表，随用随查。"
+++

## 基础操作

```bash
git init                      # 初始化仓库
git clone <url>               # 克隆远程仓库
git status                    # 查看当前状态
git add .                     # 暂存所有改动
git commit -m "提交说明"       # 提交
git log --oneline --graph     # 图形化查看提交历史
```

## 分支管理

```bash
git branch                    # 查看本地分支
git switch -c feature/x       # 新建并切换分支
git switch main               # 切回主分支
git merge feature/x           # 合并分支
git branch -d feature/x       # 删除已合并的分支
```

## 撤销与回退

> 回退操作前请务必确认没有未提交的改动，必要时先 `git stash`。

| 场景 | 命令 |
| --- | --- |
| 撤销工作区改动 | `git checkout -- <file>` |
| 取消暂存 | `git restore --staged <file>` |
| 修改最近一次提交 | `git commit --amend` |
| 回退到某个提交（保留改动） | `git reset --soft <commit>` |

## 与远程协作

```bash
git remote -v                 # 查看远程地址
git fetch --all --prune       # 拉取远程信息
git pull --rebase             # 变基式拉取
git push -u origin main       # 推送并建立追踪
```
