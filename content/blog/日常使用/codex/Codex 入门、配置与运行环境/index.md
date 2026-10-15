+++
title = "Codex 入门、配置与运行环境"
date = 2026-10-10
weight = 1
tags = ["Codex", "AI", "CLI", "环境配置"]
summary = "Codex CLI 上手第一课：安装、登录、会话操作，以及 config.toml、模型与推理强度、Provider、沙箱权限和常见环境问题的排查思路。"
+++

## 一、Codex 是什么

Codex 是 OpenAI 推出的**编程智能体（coding agent）**。它和普通聊天机器人的区别在于：它能直接读写你本地的代码仓库、执行命令、查看报错、修改文件，并在一个真实的工作目录里持续完成一项开发任务。

Codex 有几种使用形态：

- **Codex CLI**：终端里的交互式智能体，本系列的主角。
- **IDE 扩展**：在 VS Code 等编辑器里使用，能感知当前打开的文件和选中代码。
- **ChatGPT 桌面 / 网页 / 云端**：偏规划、审查和托管执行。

> 本系列只讲 CLI。掌握了 CLI，其他形态的配置（`config.toml`、`AGENTS.md`、MCP）是通用的。

### 1.1 适合交给 Codex 的任务

- 阅读陌生代码库，梳理目录结构、入口和调用链。
- 生成新代码、按现有风格补功能。
- 解释某段代码或某个报错的含义。
- 定位 Bug、加日志、写最小复现。
- 补充单元测试、集成测试和文档。
- 重构、性能优化、依赖升级。
- 对当前 Git 改动做代码审查。

### 1.2 不适合直接交给 Codex 的任务

- 需求本身还说不清、没有验收标准的任务。
- 涉及生产密钥、线上数据库、真实用户数据的**高危操作**。
- 需要长期业务判断、组织决策的事情。

一句话总结：**Codex 擅长"有明确验收标准的工程任务"**，任务越具体、边界越清楚，效果越好。

![](assets/01-codex-overview.webp)

## 二、安装 Codex CLI

### 2.1 前置条件

先确认 Node.js 环境（npm 安装方式需要）：

```bash
node -v
npm -v
```

建议 Node.js 20 以上。如果你的机器上没有 Node，可以用官方的独立安装脚本（下一小节），它会自带运行环境。

### 2.2 方式一：npm 全局安装

```bash
npm install --global @openai/codex
codex --version
```

安装成功后会输出类似 `codex-cli 0.162.1` 的版本号。

### 2.3 方式二：官方安装脚本

macOS / Linux：

```bash
curl -fsSL https://chatgpt.com/codex/install.sh | sh
```

Windows（PowerShell）：

```powershell
irm https://chatgpt.com/codex/install.ps1 | iex
```

脚本默认把可执行文件装到 `~/.local/bin`（macOS / Linux），Windows 默认在 `%LOCALAPPDATA%\Programs\OpenAI\Codex\bin`。可以用环境变量改安装目录：

```bash
curl -fsSL https://chatgpt.com/codex/install.sh | CODEX_INSTALL_DIR="$HOME/.local/bin" sh
```

无交互安装（适合脚本化，会跳过所有提示、全部用默认值）：

```bash
curl -fsSL https://chatgpt.com/codex/install.sh | CODEX_NON_INTERACTIVE=1 sh
```

### 2.4 验证安装

```bash
which codex
codex --version
codex doctor
```

`codex doctor` 会一次性体检安装、配置、认证和运行时状态，是排查环境问题的第一站。

![](assets/02-install-version.webp)

## 三、版本管理与升级降级

### 3.1 查看与升级

```bash
codex --version          # 当前版本
codex update             # 自更新（安装源支持时）
npm view @openai/codex version   # 看远端最新版本
```

### 3.2 指定版本安装（降级）

```bash
npm install --global @openai/codex@0.162.1
```

### 3.3 多版本并存排查

升级后如果 `codex --version` 还是旧版本，通常是 PATH 里有多个 `codex`：

```bash
which -a codex     # Linux / macOS，列出所有命中
type -a codex      # zsh / bash 内置，效果类似
```

按顺序清理：保留想要的那一个，把旧的删掉或把它的目录从 PATH 里移除。

> 记住一条规则：**谁在 PATH 里靠前，谁的 `codex` 就生效**。

## 四、登录、认证与模型使用

### 4.1 用 ChatGPT 账号登录（默认方式）

```bash
codex login
```

执行后会打开浏览器完成 OAuth 授权，凭证回写到本机。

### 4.2 无头 / 远程机器登录

服务器上没有浏览器时，优先用设备码登录：

```bash
codex login --device-auth
```

终端会打印一个链接和一次性验证码，在任意能上网的设备上打开链接、输入验证码即可。

如果设备码登录不可用，可以在有浏览器的机器上先登录，再把凭证拷过去：

```bash
# 有浏览器的机器
codex login
ls ~/.codex/auth.json

# 拷到远程机器
ssh user@remote 'mkdir -p ~/.codex'
scp ~/.codex/auth.json user@remote:~/.codex/auth.json
```

> `~/.codex/auth.json` 里是访问令牌，**要像密码一样对待**：不要提交到 Git，不要贴到聊天或工单里。

### 4.3 用 API Key 登录

```bash
printenv OPENAI_API_KEY | codex login --with-api-key
```

API Key 走的是标准 API 计费，适合 CI/CD 这类程序化场景；部分依赖 ChatGPT 工作区的能力会受限。

### 4.4 查看与退出登录

```bash
codex login status    # 打印当前认证方式，已登录时退出码为 0
codex logout          # 清除本地凭证
```

### 4.5 切换模型

```bash
codex -m gpt-6.1-sol "帮我梳理这个模块的调用链"
```

也可以在会话里用斜杠命令临时切换：

```text
/model
```

默认模型建议写在 `config.toml` 里，避免每次手动指定（见第十节）。

![](assets/03-login-status.webp)

## 五、启动方式与项目目录选择

### 5.1 最常用的启动方式

```bash
cd ~/projects/my-service
codex
```

进入交互式界面后，**当前目录就是 Codex 的工作根目录**。

### 5.2 不切目录直接指定工作目录

```bash
codex -C ~/projects/my-service
codex --cd ~/projects/my-service
```

`-C` 和 `--cd` 等价。

### 5.3 直接带一个初始任务启动

```bash
codex "先不要改代码，梳理这个项目的目录结构和启动入口，输出 Markdown"
codex -C ~/projects/my-service "跑一遍测试，告诉我失败了哪些"
```

### 5.4 在独立 Git 工作树里启动

```bash
codex --worktree
```

这会在一个全新的 Git worktree 里开一个会话，不打扰你当前的检出，适合并行做多个任务（第四篇会详细展开）。

### 5.5 追加可写目录

```bash
codex --add-dir /path/to/another-repo
```

需要跨仓库改动时用它，比直接开 `danger-full-access` 安全得多。

![](assets/04-start-session.webp)

## 六、交互式会话与基本命令

### 6.1 输入框里的快捷操作

| 操作 | 作用 |
| --- | --- |
| `@` | 搜索工作区文件，把路径插入提示词 |
| `!` 前缀 | 直接执行一条本地 shell 命令 |
| `Tab` | Codex 正在工作时，把后续消息排进下一轮 |
| `Enter` | Codex 正在工作时，把新指令注入当前轮 |
| 连按两次 `Esc` | 编辑上一条消息，并从那里分叉会话 |
| `Ctrl + R` | 搜索历史提示词 |
| `Ctrl + O` | 复制最近一次输出 |
| `Ctrl + C` | 中断 / 退出 |

### 6.2 常用斜杠命令

在输入框输入 `/` 会弹出命令面板。常用的有：

| 命令 | 用途 |
| --- | --- |
| `/model` | 切换模型 |
| `/permissions` | 调整权限（只读 / 自动等） |
| `/plan` | 进入计划模式，先出方案不动手 |
| `/status` | 查看当前会话状态 |
| `/clear` | 清屏并开一个新会话 |
| `/rename` | 给当前会话起名 |
| `/copy` | 复制最近一次输出 |
| `/agent` | 切换子智能体线程 |
| `/skills` | 选用某个技能 |
| `/approve` | 重试一次被自动审查拒绝的操作 |
| `/exit` | 退出会话 |

### 6.3 一次性非交互执行

```bash
codex exec "总结最近 10 次提交，生成发布说明"
```

`codex exec` 把进度打到 stderr、最终结果打到 stdout，天然适合接管道：

```bash
codex exec "生成最近 10 次提交的发布说明" > release-notes.md
```

第四篇会专门讲自动化用法。

## 七、代码生成、修改、解释与调试

### 7.1 生成新代码

```text
在 src/main/java/com/example/user 下新增一个 UserQueryService，
参照现有 UserCommandService 的风格：构造器注入、返回 Optional、不加 @Transactional。
只写这一个类，不要动其它文件。
```

### 7.2 修改已有代码

```text
把 OrderService#createOrder 里的库存扣减从同步调用改为发 MQ 消息，
保持方法签名不变，失败时回滚本地事务。
先给我改动方案，我确认后再动手。
```

### 7.3 解释代码

```text
解释 src/main/java/.../KafkaConsumer.java 的消费位点提交逻辑，
说明哪些情况下会重复消费，用一句话结论开头。
```

### 7.4 调试报错

```text
这是运行 mvn test 的完整输出（贴日志）。
先分析根因，给出最小复现步骤，再提出修复方案，暂时不要改代码。
```

> 调试类任务里，**贴完整的报错栈**比贴一句"报错了"有效得多。Codex 能看到的信息越多，越不容易瞎猜。

## 八、让 Codex 阅读已有项目

接手一个新仓库时，第一步不要急着改代码，而是先让它"读项目"：

```text
只读，不要修改任何文件。
1. 说明这个项目是做什么的；
2. 画出模块划分和依赖关系；
3. 找到程序入口和核心调用链；
4. 列出你判断最脆弱的三个地方。
输出 Markdown，文件路径用相对路径。
```

也可以直接让它读某个具体文件：

```text
读 src/main/java/.../OrderController.java，告诉我它暴露了哪些接口、每个接口的参数和返回值。
```

这一步做完，再让它动手改代码，准确率会明显提升。

![](assets/05-read-project.webp)

## 九、退出、恢复会话与常见操作

### 9.1 退出

- `Ctrl + C`
- 输入 `/exit`
- 输入 `/archive`：归档并退出
- 输入 `/delete`：删除并退出（不可恢复）

### 9.2 恢复上一次会话

```bash
codex resume            # 弹出选择器
codex resume --last     # 直接继续最近一次
codex resume <session-id>
```

### 9.3 分叉会话

```bash
codex fork --last
```

想保留原会话、又想从某个节点试另一条路时用 `fork`。

### 9.4 归档与恢复

```bash
codex archive <id>
codex unarchive <id>
codex delete <id>
```

会话记录默认放在 `$CODEX_HOME/sessions`，归档的在 `$CODEX_HOME/archived_sessions`。

### 9.5 会话被"卡住"时

1. 先看是不是在等审批。
2. 开一个终端跑 `git status` 确认仓库状态正常。
3. 用更小、更聚焦的提示词开一个新会话。

![](assets/06-resume-session.webp)

## 十、config.toml 配置文件

### 10.1 两个位置

| 位置 | 作用域 | 说明 |
| --- | --- | --- |
| `~/.codex/config.toml` | 用户级 | 个人默认配置，所有项目共用 |
| `<项目>/.codex/config.toml` | 项目级 | 只对这个仓库生效，**项目被标记为 trusted 才加载** |

打开用户配置：

```bash
${EDITOR:-vim} ~/.codex/config.toml
```

### 10.2 配置优先级（从高到低）

1. 命令行参数与 `-c/--config` 覆盖
2. 项目配置 `.codex/config.toml`（从项目根到当前目录，越近越优先；仅限可信项目）
3. `--profile` 指定的 profile 文件 `~/.codex/<name>.config.toml`
4. 用户配置 `~/.codex/config.toml`
5. 云托管配置（登录工作区时下发）
6. 系统配置 `/etc/codex/config.toml`（Unix）
7. 内置默认值

> 想临时覆盖某个值又不想改文件，用 `-c`：
>
> ```bash
> codex -c model="gpt-6.1-sol" -c sandbox_mode="read-only"
> ```

### 10.3 一份可用的最小配置

```toml
# ~/.codex/config.toml
model = "gpt-6.1-sol"
model_reasoning_effort = "medium"
approval_policy = "on-request"
sandbox_mode = "workspace-write"
web_search = "cached"
```

### 10.4 可信项目

Codex 只在信任某个项目时才加载它的 `.codex/` 配置、hooks 和规则：

```toml
[projects."/home/me/projects/my-service"]
trust_level = "trusted"
```

## 十一、模型、推理强度与输出设置

### 11.1 选择模型

```toml
model = "gpt-6.1-sol"
```

临时切换：

```bash
codex -m gpt-6.1-sol
```

### 11.2 推理强度

支持 `minimal`、`low`、`medium`、`high` 等档位（取决于模型）：

```toml
model_reasoning_effort = "high"
```

经验做法：**分析、审查、重构用高一些；改文案、改格式用低一些**，省时也省钱。

### 11.3 沟通风格

```toml
personality = "pragmatic"   # 可选 friendly / pragmatic / none
```

会话里也能用 `/personality` 临时切换。

### 11.4 联网搜索

```toml
web_search = "cached"    # 默认，走搜索缓存，降低提示注入风险
# web_search = "live"    # 实时抓取，等价于 --search
# web_search = "disabled"
```

### 11.5 输出语言与格式

Codex 没有专门的"输出语言"开关，直接在提示词里约束最可靠：

```text
用中文回答；代码块外的说明不超过 5 行；结论放最前面。
```

## 十二、Provider 与自定义 API 配置

除了默认的 OpenAI 通道，还可以接自定义网关或兼容 API。

### 12.1 自定义 Provider

```toml
model_provider = "custom"
model = "your-model-name"

[model_providers.custom]
name = "custom"
base_url = "https://api.example.com/v1"
wire_api = "responses"          # 或 "chat"
env_key = "MY_PROVIDER_API_KEY" # 从环境变量读密钥，不要写死
requires_openai_auth = false
```

> **不要把 API Key 明文写进 `config.toml`**。用 `env_key` 指向环境变量，密钥只存在于 shell 环境里。

### 12.2 用 Profile 管理多套配置

`~/.codex/company.config.toml`：

```toml
model_provider = "custom"
model = "your-model-name"
```

使用：

```bash
codex --profile company
```

这样默认走一套、需要时切到另一套，互不影响。

### 12.3 本地开源模型

```bash
codex --oss --local-provider ollama
codex --oss --local-provider lmstudio
```

## 十三、环境变量与认证信息管理

Codex 读取的常用环境变量：

| 变量 | 作用 |
| --- | --- |
| `CODEX_HOME` | Codex 状态根目录，默认 `~/.codex`（目录必须已存在） |
| `CODEX_SQLITE_HOME` | SQLite 状态存放位置，默认等于 `CODEX_HOME` |
| `CODEX_API_KEY` | 非交互进程使用的 API Key |
| `CODEX_ACCESS_TOKEN` | ChatGPT / Codex 访问令牌，用于可信自动化 |
| `CODEX_CA_CERTIFICATE` | 企业自签 CA 的 PEM 证书路径 |

推荐做法：

```bash
# 只对当前命令生效，不污染全局环境
CODEX_API_KEY="$MY_KEY" codex exec "生成发布说明"

# 持久化登录用 stdin 管道，而不是写进脚本
printenv CODEX_ACCESS_TOKEN | codex login --with-access-token
```

> 密钥只放环境变量或凭证存储，**不要提交进仓库、不要贴进日志**。

## 十四、项目级配置与用户级配置

### 14.1 怎么选

- **个人偏好**（模型、风格、keymap）→ 用户级 `~/.codex/config.toml`
- **团队约定**（沙箱、MCP、构建命令）→ 项目级 `<repo>/.codex/config.toml`
- **一次性的任务约束** → 直接写在提示词里，或 `-c` 临时覆盖

### 14.2 项目配置示例

```toml
# <repo>/.codex/config.toml
sandbox_mode = "workspace-write"
approval_policy = "on-request"

[sandbox_workspace_write]
network_access = false
```

### 14.3 验证项目配置是否生效

```bash
codex -C ~/projects/my-service "列出你实际加载了哪些指令文件"
```

Codex 会在每次启动时重新构建配置与指令链，改完配置重开会话即可，没有缓存要清。

## 十五、沙箱、文件访问与网络权限

这是 Codex 安全模型的核心，务必理解。

### 15.1 三种沙箱模式

| 模式 | 能读 | 能写 | 典型场景 |
| --- | --- | --- | --- |
| `read-only` | ✅ | ❌ | 只分析、只审查 |
| `workspace-write` | ✅ | 仅工作区（及 `--add-dir`） | 日常开发（推荐） |
| `danger-full-access` | ✅ | 任意路径 | 隔离容器里才用 |

### 15.2 审批策略

| 策略 | 含义 |
| --- | --- |
| `on-request` | 模型自己判断何时需要你确认（默认、推荐） |
| `never` | 从不询问，失败直接返回给模型 |

### 15.3 常用组合

| 目标 | 命令 / 配置 |
| --- | --- |
| 日常自动模式 | `--sandbox workspace-write --ask-for-approval on-request` |
| 只读浏览 | `--sandbox read-only --ask-for-approval on-request` |
| CI 只读 | `--sandbox read-only --ask-for-approval never` |
| 完全放开 | `--dangerously-bypass-approvals-and-sandbox`（别名 `--yolo`，不建议） |

### 15.4 允许工作区联网

```toml
[sandbox_workspace_write]
network_access = true
```

### 15.5 本地测试沙箱行为

```bash
# Linux
codex sandbox linux --log-denials ls /etc
# macOS
codex sandbox macos --log-denials ls /etc
# Windows
codex sandbox windows ls C:\
```

被拦下来的操作会打印拒绝原因，是排查"为什么这条命令跑不了"的最快方式。

![](assets/07-sandbox-test.webp)

## 十六、Shell 环境与 PATH 排查

### 16.1 Codex 用哪个 shell

Codex 执行命令时继承你的 shell 环境。它默认会过滤掉名字里带 `KEY`、`SECRET`、`TOKEN` 的变量，避免误传密钥。

需要精细控制时：

```toml
[shell_environment_policy]
ignore_default_excludes = false

[shell_environment_policy.filters]
"PATH" = "include"
"HOME" = "include"
```

### 16.2 PATH 排查三步

```bash
echo $PATH | tr ':' '\n'      # 看顺序
which -a codex                # 看有几个 codex
type -a node npm              # 看工具链是否来自同一套
```

常见坑：用 nvm / asdf / fnm 管理 Node 时，Codex 里的 `node` 和交互 shell 里的不是同一个。解决办法是在启动 Codex 前先激活对应版本，或把绝对路径写进配置。

### 16.3 命令在 Codex 里找不到

```bash
# 在 Codex 会话里直接跑，看它眼里的 PATH
!echo $PATH
!which node
```

如果这里缺目录，说明 Codex 没有加载你的登录 shell 配置。可以在 `~/.codex/config.toml` 里显式补上：

```toml
[shell_environment_policy.filters]
"PATH" = "include"
```

## 十七、Linux、macOS、Windows 环境差异

| 方面 | Linux | macOS | Windows |
| --- | --- | --- | --- |
| 沙箱实现 | Landlock | Seatbelt（`sandbox-exec`） | 优先 MXC，可回退 elevated |
| 安装目录 | `~/.local/bin` | `~/.local/bin` | `%LOCALAPPDATA%\Programs\OpenAI\Codex\bin` |
| 系统配置 | `/etc/codex/config.toml` | 同左 | 由策略 / 注册表管理 |
| 登录 shell | 常见 bash / zsh | zsh 为主 | PowerShell / WSL |

Windows 上如果沙箱能力受限，可显式选择实现：

```toml
[windows]
sandbox = "elevated"

[features]
prefer_mxc = true
```

WSL 里使用时，按 Linux 的方式排查即可；注意 WSL 与 Windows 两侧的 PATH 会互相拼接，容易出现"同名命令两份"。

## 十八、网络、代理与常见 HTTP 错误

### 18.1 代理

```bash
export HTTPS_PROXY="http://127.0.0.1:7890"
export HTTP_PROXY="http://127.0.0.1:7890"
export NO_PROXY="localhost,127.0.0.1"
codex login
```

企业自签 CA：

```bash
export CODEX_CA_CERTIFICATE=/path/to/corporate-root-ca.pem
```

未设置时，Codex 会回退读取 `SSL_CERT_FILE`。

### 18.2 常见状态码

| 状态码 | 常见原因 | 处理方向 |
| --- | --- | --- |
| `400` | 请求体 / 参数不被模型或网关接受 | 检查模型名、`wire_api`、Provider 是否兼容 |
| `401` | 未认证或密钥失效 | `codex login status`，重新登录或换 key |
| `403` | 无权限（工作区 / 模型 / 区域） | 确认账号权限、Provider 白名单 |
| `404` | `base_url` 或路径写错 | 核对自定义 Provider 的 `base_url` |
| `429` | 触发限流 | 降并发、退避重试、错峰执行 |
| 超时 | 网络抖动 / 代理不稳 | 重试、检查代理、缩小任务粒度 |

### 18.3 模型或 Provider 参数不兼容

典型症状：登录正常，但一发请求就报 `400`。常见原因是 `wire_api` 选错（该用 `chat` 却写了 `responses`，或反过来），或自定义网关不支持某个参数。先换成最小配置验证：

```bash
codex -c model_provider="custom" -c model="your-model" "说一句你好"
```

## 十九、日志收集、最小复现与问题定位

### 19.1 日志位置

| 内容 | 位置 |
| --- | --- |
| 会话记录 | `$CODEX_HOME/sessions`（默认 `~/.codex/sessions`） |
| 归档会话 | `$CODEX_HOME/archived_sessions` |
| TUI 明文日志 | 设置了 `log_dir` 后生成 `codex-tui.log` |
| 登录日志 | 直接执行 `codex login` 时生成 `codex-login.log` |

打开明文日志：

```bash
codex -c log_dir=./.codex-log
ls ./.codex-log
```

### 19.2 一条可复用的排查流程

1. `codex --version` 记录版本。
2. `codex doctor` 看体检结论。
3. `codex login status` 确认认证方式。
4. 用一个最小提示词复现，例如 `codex exec "说一句你好"`。
5. 加 `-c log_dir=./.codex-log` 拿日志。
6. 检查 PATH、代理、自定义 Provider 三处最常见的外部因素。

### 19.3 提 Issue 前先自查

```bash
codex --version
codex doctor
codex login status
```

把这三条的输出、你的操作系统、以及最小复现步骤一起贴出来，比"我这边用不了"高效得多。**分享日志前先确认里面没有敏感信息。**

---

到这里，环境和会话已经跑通。下一篇进入提示词与上下文工程，解决"怎么让 Codex 更准确地理解任务"的问题。

