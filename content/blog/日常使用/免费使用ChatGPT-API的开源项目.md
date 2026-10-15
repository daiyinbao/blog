+++
title = "五个免费使用 ChatGPT API 的开源项目（整理）"
date = 2026-10-14
weight = 10
tags = ["ChatGPT", "API", "开源", "AI"]
summary = "整理自 51CTO 的一篇旧文：五个可免费获取或转发 ChatGPT API 的开源项目，附项目地址、支持模型、部署与调用方式，并补充 2026 年的时效性与安全提示。"
+++

## 写在前面

本文整理自 51CTO 上的一篇旧文（2024-04-23，作者：小小IT仔，来源：IT仔的笔记本），原标题是《五个免费使用 ChatGPT API 的开源项目》。

原文介绍的是 GitHub 上几个可以**免费获取或转发 GPT API** 的项目。这里做了三件事：把零散信息整理成可查阅的格式、补上原文里含糊的部署与调用细节、并核对这些项目在当前的可用状态。

> **先说结论**：这类"免费 Key / 转发接口"本质上是**第三方中转服务**，不是 OpenAI 官方。省下的是钱，付出的是稳定性、隐私和合规风险。有条件的话，直接买官方 API Key 更省心。

### 使用前必须知道的风险

- **数据会经过第三方**。你的每一次提问都要先发到对方的服务器，再转发给模型。
- **多数中转不符合 OpenAI 服务条款**，账号或 Key 随时可能被回收。
- **免费额度有硬限制**，且随时可能失效，不适合放进正式项目。
- **不要用它处理敏感数据**：内部代码、客户信息、个人隐私、账号口令一律不要粘。
- **自部署类项目要警惕**。拉取来历不明的 Docker 镜像，等于在本机执行陌生代码。

## 一、五个项目总览

先看一张表，按需往下翻：

| # | 项目 | 类型 | 是否需要 Key | 自部署 | 仓库状态（2026-10 核对） |
| --- | --- | --- | --- | --- | --- |
| 1 | GPT-API-free | 免费 Key 分发 | 是 | 否 | 可访问 |
| 2 | FREE-CHATGPT-API | 免费 Key 分发 | 是 | 否 | ⚠️ 仓库已 404 |
| 3 | gpt4free | 免 Key 转发服务 | 否 | 是 | 可访问 |
| 4 | gpt4free-ts | 自部署 + 定期发 Key | 部分 | 是 | 可访问 |
| 5 | FreeGPT35 | 转发接口（需自部署） | 否 | 是 | 可访问 |

> 开源项目变动极快，**使用前先看仓库的最近提交时间**。如果一个项目半年没更新，基本可以认为已经失效。

## 二、GPT-API-free

国内比较早、也比较知名的一个免费 Key 分发项目，门槛低，适合先跑通流程试个水。

### 2.1 基本信息

- **项目地址**：<https://github.com/chatanywhere/GPT_API_free>
- **免费 Key 支持模型**：`gpt-3.5-turbo`、`embedding`，以及 `gpt-4`（每天 3 次）

### 2.2 获取免费 Key

打开绑定页面，用 GitHub 账号授权：

```text
https://api.chatanywhere.org/v1/oauth/free/github/render
```

绑定成功后会直接显示一个专属 API Key。

> 注意：**GitHub 账号注册未满 7 天无法领取**。

### 2.3 接口地址（Base_url）

这个项目**必须配合它指定的接口地址使用**，直接填 OpenAI 官方地址是不通的。按你的服务器所在区域选择：

| 环境 | 接口（Base_url） |
| --- | --- |
| 国外服务器 | `https://api.chatanywhere.cn` |
| 国内服务器 | `api.chatanywhere.com.cn` |
| 国内服务器 | `api.chatanywhere.tech` |

### 2.4 验证 Key 是否可用

```bash
export OPENAI_API_KEY="你领到的 key"

curl -sS https://api.chatanywhere.tech/v1/chat/completions \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-3.5-turbo",
    "messages": [{"role": "user", "content": "你好，请回复一句问候"}]
  }'
```

能返回 JSON 且 `choices[0].message.content` 有内容，就说明通了。

### 2.5 免费额度限制

限制规则是 **100 请求 / 天 / IP & Key**，两边同时卡：

- 同一个 IP 下用多个 Key，所有 Key 当天请求数之和不能超过 100；
- 同一个 Key 用在多个 IP，这个 Key 当天请求数同样不能超过 100。

也就是说，想靠堆 Key 或换 IP 刷额度是行不通的。

### 2.6 付费版本

项目同时提供付费 Key，价格低于官方、稳定性好于免费版。介意稳定性的可以用付费版过渡。

## 三、FREE-CHATGPT-API

### 3.1 基本信息

- **项目地址**：`https://github.com/popjane/free_chatgpt_api`（⚠️ 截至 2026-10 已无法访问，此处仅作记录）
- **免费 Key 支持模型**：`gpt-3.5-turbo-0125`、`gpt-3.5-turbo-1106`、`gpt-3.5-turbo`、`gpt-3.5-turbo-16k`、`net-gpt-3.5-turbo`（可联网搜索，稳定性稍差）、`whisper-1`、`dall-e-2`，以及 `text-` 开头的系列模型（如 `text-davinci`）

### 3.2 获取免费 Key

同样是 GitHub 授权绑定，绑定后显示专属 Key：

```text
https://free.gpt.ge/github
```

同样要求 GitHub 账号注册满 7 天。

### 3.3 接口地址（Base_url）

| 环境 | 接口（Base_url） |
| --- | --- |
| 国内外服务器 | `https://free.gpt.ge` |

### 3.4 说明

这个项目同样提供付费 Key。由于仓库已下线，上面的地址和领取入口**很可能已经失效**，列在这里是为了保留线索——同类项目往往会在别处重新出现，思路是通用的。

## 四、gpt4free

这是几个项目里名气最大的一个，特点是**完全不需要 Key**：自己部署服务后，它会生成一个免 Key 的 API 地址。

### 4.1 基本信息

- **项目地址**：<https://github.com/xtekky/gpt4free>
- **支持的模型相当杂**，覆盖多个厂商的免费渠道，例如：
  - OpenAI 系：`gpt-3.5-turbo`、`gpt-4`、`gpt-4-turbo`
  - Meta 系：`Llama-2-7b/13b/70b-chat-hf`、`Meta-Llama-3-8b/70b`、`CodeLlama-34b/70b-Instruct-hf`
  - Mistral 系：`Mixtral-8x7B-Instruct-v0.1`、`Mistral-7B-Instruct-v0.1`
  - 其它：`gemini`、`gemini-pro`、`claude-v2`、`claude-3-opus`、`claude-3-sonnet` 等

### 4.2 部署服务

```bash
docker pull hlohaus789/g4f

docker run -p 8080:8080 -p 1337:1337 -p 7900:7900 \
  --shm-size="2g" \
  -v ${PWD}/hardir:/app/hardir \
  hlohaus789/g4f:latest
```

### 4.3 对外端口说明

| 地址 | 说明 |
| --- | --- |
| `http://ip:1337` | API 接口，供其它项目调用。使用时**无需配置 Key**；如果对方强制要求填 Key，随便写几个字符即可 |
| `http://ip:8080` | 项目自带的 Web UI，仿 ChatGPT 官网，可直接对话 |

### 4.4 说明

项目主页也会列出一些可直接访问的 AI 站点，不过可用性不稳定，**不保证能打开**。

> 这类项目依赖上游免费渠道，上游一改规则就会大面积失效。适合折腾、不适合依赖。

## 五、gpt4free-ts

用 TypeScript 重写的同类项目，部署更轻。它的定位是"自部署 + 定期在主页发放免费 Key"。

### 5.1 基本信息

- **项目地址**：<https://github.com/xiangsx/gpt4free-ts>
- **支持模型**：`gpt-4-all`、`gpt-3.5-turbo`、`gpt-3.5-turbo-16k`、`net-gpt-3.5-turbo`、`net-gpt-3.5-turbo-16k`、`claude-1-100k`、`google-palm`、`llama-2-70b/13b/7b`、`code-llama-34b/13b/7b`、`qwen-72b`、`stable-diffusion`、`mixtral-8x7b`、`mistral-medium`

### 5.2 公开的接口地址与 Key

原文给出的信息如下（**Key 已打码**）：

| 项 | 值 |
| --- | --- |
| API 接口地址（Base_url） | `https://api.gptgod.online` |
| API Key | `sk-OsMMq65t...`（原文直接贴了完整 Key） |

> ⚠️ 提醒两点：一是**在公开文章里贴出来的 Key 基本都会立刻失效或被滥用**，实际多半已经不能用；二是**不要使用来路不明的公开 Key**，你无法知道背后是谁在收集流量。

### 5.3 自己部署

第一步，创建配置文件 `.env`：

```bash
vim .env
```

```ini
http_proxy=http://host:port     # 按需自定义
rapid_api_key=xxxxxxxxxx        # 上一步获取的 key
EMAIL_TYPE=temp-email44
DEBUG=0
POOL_SIZE=0
PHIND_POOL_SIZE=0
```

第二步，启动容器：

```bash
docker run -p 3000:3000 --env-file .env xiangsx/gpt4free-ts:latest
```

第三步，访问 `http://ip:3000` 使用自带的 Web UI。

## 六、FreeGPT35

思路和前两个不同：它**不提供 Key，只提供一个转发接口**。

### 6.1 基本信息

- **项目地址**：<https://github.com/missuo/FreeGPT35>
- **支持模型**：GPT-3.5
- **原理**：利用免登录的 ChatGPT Web 规则，对外提供 GPT-3.5-Turbo 的 API 服务

### 6.2 使用方式

1. 部署这个项目，得到一个 API 接口地址；
2. 把这个地址填到任意 AI Web UI 项目里作为 **Base URL**（例如 ChatGPT-Next-Web）；
3. **无需配置 Key**，直接就能用。

> 由于它本质是"转发网页端"，上游一改登录规则就会失效，属于典型的"能用一天是一天"。

## 七、把 Base_url 接到自己的 Web UI 上

上面几个项目，除了自带 UI 的，最常见的用法都是接到一个通用的 Web 前端上。以 ChatGPT-Next-Web 为例，核心就两个环境变量：

```bash
OPENAI_API_KEY=<你领到的或随便填的 key>
OPENAI_API_BASE_URL=<项目提供的 Base_url>
```

写成 `docker-compose.yml` 大致是这样：

```yaml
services:
  chatgpt-next-web:
    image: yidadaa/chatgpt-next-web
    ports:
      - "3000:3000"
    environment:
      OPENAI_API_KEY: "<你的 key>"
      OPENAI_API_BASE_URL: "https://api.chatanywhere.tech"
      CODE: "<访问密码>"
```

```bash
docker compose up -d
```

打开 `http://localhost:3000`，随便发一句话，能回就说明接好了。

## 八、怎么判断一个免费中转还值不值得用

按这个顺序自查，基本能筛掉大部分坑：

1. **仓库还活着吗**：最近一次提交是不是在半年内？有没有 `archived` 标记？
2. **接口还通吗**：用第二节那段 `curl` 跑一次，看返回的是内容还是报错。
3. **文档还准吗**：Base_url 是否和仓库 README 一致（这类项目换域名非常频繁）。
4. **有没有偷偷收费**：部分项目免费额度用完后会自动转付费，注意条款。
5. **安全边界**：绝不喂敏感数据；自部署镜像尽量用可信来源，并在隔离环境里跑。

## 九、写在最后

把这五个项目放在一起看，能发现一个共同规律：**免费的中转服务本质上是在"赌上游不封"**，所以生命周期都很短。

- 想**长期稳定**用：老老实实买官方 API Key，或者用官方渠道。
- 想**低成本试水**：可以拿免费 Key 跑通流程、熟悉 API 调用方式，然后把代码切到正式 Key 上。
- 想**研究原理**：gpt4free 这类项目的代码值得读一读，能看清"转发"到底做了什么。

**一句话总结**：可以白嫖，但别依赖；可以试玩，但别放敏感数据。

---

**原文信息**

- 标题：五个免费使用 ChatGPT API 的开源项目
- 作者：小小IT仔（来源：IT仔的笔记本）
- 发布：2024-04-23 08:16:21
- 链接：<https://www.51cto.com/article/786796.html>
