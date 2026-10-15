+++
title = "Codex 项目开发工作流与代码审查"
date = 2026-10-10
weight = 3
tags = ["Codex", "AI", "工作流", "代码审查"]
summary = "把 Codex 放进真实研发流程：需求梳理、按风格实现、重构与性能优化、测试补充、构建验证、Git 提交，以及用 codex review 做可重复的代码审查。"
+++

## 一、从需求到实现的完整流程

真实项目里，一次改动通常要经过：**理解需求 → 摸清现状 → 定方案 → 实现 → 自测 → 审查 → 提交**。Codex 在每一步都能帮上忙，但前提是分阶段推进，而不是一句"帮我做完"。

一条可复用的完整链路：

```text
1. 需求：把需求整理成可判定的验收标准（写进任务描述）。
2. 摸底：只读分析，找到相关代码和调用链。
3. 方案：给出文件级改动计划，人工确认。
4. 实现：按计划改，只动计划内文件。
5. 验证：跑测试 / 构建 / 静态检查，贴出证据。
6. 审查：codex review 审自己的改动。
7. 提交：小步提交，写清 commit message。
```

每一阶段对应的命令和提示词，下面逐节展开。

![](assets/01-workflow-overview.webp)

## 二、让 Codex 先梳理项目架构与调用链

### 2.1 摸清仓库全貌

```bash
codex -C ~/projects/my-service "只读，不要改任何文件。
1. 说明项目用途与技术栈；
2. 列出模块划分和依赖方向；
3. 找到程序入口和配置加载顺序；
4. 输出到 docs/architecture-map.md。"
```

### 2.2 追踪一条调用链

```text
从 HTTP 接口 POST /api/orders 出发，追出完整调用链：
Controller → Service → Mapper → 数据库，
标出每一层的方法名和文件路径，以及涉及的事务边界。
只读分析，不要改代码。
```

### 2.3 排查"改动会波及谁"

```text
如果我把 OrderService#createOrder 的返回值从 void 改成 Order，
请列出所有受影响的调用方（文件 + 行号 + 影响说明）。
只读分析。
```

这一步做扎实，后面的实现和审查都会轻松很多。

## 三、根据现有代码风格实现功能

### 3.1 先让 Codex 归纳风格

```text
只读，阅读 user 包下的 3 个 Service，
总结本项目的代码风格：注入方式、异常处理、日志、返回值包装、命名习惯。
用不超过 10 条列出。
```

### 3.2 再按风格实现

```text
参照刚才总结的风格，在 refund 包下实现 RefundService：
- 提供 createRefund(orderId, amount) 方法；
- 遵循构造器注入、返回 Result<T>、异常抛 BizException；
- 只新增 RefundService.java，不要改其它文件。
完成后贴出 git diff --stat。
```

### 3.3 用 `@` 直接投喂参考文件

```text
参照 @src/main/java/com/example/user/UserService.java 的写法，
实现 @src/main/java/com/example/refund/RefundService.java 里 TODO 标注的三个方法。
```

> 让 Codex"模仿"比让它"发挥"更稳。给定参照物，风格漂移会明显减少。

![](assets/02-implement-by-style.webp)

## 四、重构

### 4.1 重构的黄金前提：先有测试

```text
在重构之前，先为 OrderService 补一批能覆盖现有行为的测试。
不要改任何生产代码，只加测试，跑通后再继续。
```

没有测试保护的重构，Codex 和你都无法判断行为是否被改变。

### 4.2 小步重构

```text
把 OrderService 拆成 OrderService（编排）和 OrderCalculator（计算）。
约束：
- 外部行为完全不变，公共方法签名不变；
- 一次只做这一件事，不要顺手改别的；
- 每改一步跑一次 ./mvnw -q test；
- 先给计划，我确认后再动手。
```

### 4.3 重构后对比行为

```bash
git diff --stat
./mvnw -q test
git diff -w -- src/main/java/com/example/order/
```

## 五、Bug 修复

### 5.1 标准三步

```text
【现象】调用 /api/orders/1 返回 500，日志见下方。
【第一步】只读分析根因，给出最小复现步骤；
【第二步】给出修复方案和影响范围，等我确认；
【第三步】实现修复，并补一个能复现该 Bug 的测试。

日志：
（粘贴完整堆栈）
```

### 5.2 让 Codex 写复现测试

```text
先写一个失败的测试来复现这个 NPE，不要修代码。
确认测试能稳定复现后，再修代码让测试变绿。
```

这是"测试驱动修复"，比直接让它改代码更可靠。

### 5.3 别让它猜

```text
如果你无法从现有信息确定根因，请列出还需要哪些信息（日志、配置、数据），
不要猜测性地改代码。
```

## 六、性能优化

### 6.1 先量化，再优化

```text
只读分析 OrderQueryService#listByUser 的性能问题：
1. 找出可能的 N+1 查询；
2. 给出 EXPLAIN 分析需要的数据；
3. 预估优化收益。
先不要改代码。
```

### 6.2 常见优化点清单

```text
检查这个接口是否存在以下问题：
- 循环内数据库查询（N+1）；
- 全表扫描 / 未命中索引；
- 一次性加载过多数据（缺分页）；
- 重复计算、重复远程调用；
- 大对象序列化开销。
逐条给出证据（文件 + 行号）。
```

### 6.3 优化必须有前后对比

```text
优化后请给出：1) 改动前后 SQL 的 EXPLAIN 对比；2) 本地基准测试结果；
3) 是否改变了返回结果或排序。没有数据支撑的"优化"请标注为待验证。
```

## 七、让 AI 编写与补充测试

### 7.1 补单测

```text
为 OrderCalculator 补单元测试，要求：
- 覆盖正常路径、边界值（0、负数、超大值）、异常路径；
- 使用项目现有的 JUnit 5 + AssertJ 风格；
- 方法名用 should_xxx_when_yyy；
- 不要用 Mockito mock 被测类本身。
```

### 7.2 补集成测试

```text
为 OrderController 的 POST /api/orders 补集成测试：
- 使用 @SpringBootTest + MockMvc；
- 覆盖 200、400（参数校验失败）、409（库存不足）三种情况；
- 数据库用 Testcontainers，参照现有 XxxIT 的写法。
```

### 7.3 检查测试质量

```text
审查你刚写的测试：
1. 有没有断言过弱（只断言 not null）的用例？
2. 有没有互相依赖、顺序敏感的用例？
3. 覆盖率缺口在哪？
逐条指出并修正。
```

> 测试不是"跑绿就行"。**弱断言的测试比没有测试更危险**，因为它制造了虚假的安全感。

## 八、使用 Git diff 检查修改

### 8.1 三个最常用的命令

```bash
git diff --stat            # 改了哪些文件、各多少行
git diff                   # 完整改动
git diff -w                # 忽略空白，专看逻辑变化
git diff --name-only       # 只要文件名
```

### 8.2 让 Codex 帮你读 diff

```text
运行 git diff，逐文件说明这次改动做了什么、是否有超出需求的改动、
是否有遗漏。只读分析，不要改代码。
```

### 8.3 检查越界

```bash
git diff --name-only | grep -v -E '^(src/main/java/com/example/order/|src/test/)'
```

有输出就说明改到了计划外的地方。

## 九、小步提交与变更回滚

### 9.1 小步提交

```bash
git add -p                                   # 逐块挑选，避免把无关改动一起提交
git commit -m "feat(order): 支持异步扣减库存"
```

### 9.2 提交前让 Codex 写 message

```text
根据当前 git diff，生成一条符合 Conventional Commits 的提交信息，
只输出一行标题 + 可选的三行正文，不要执行 git commit。
```

### 9.3 回滚

```bash
git restore --staged <file>      # 取消暂存
git restore <file>               # 撤销工作区改动
git reset --soft HEAD~1          # 撤销最近一次提交，保留改动
git stash                        # 临时收起来
```

### 9.4 让 Codex 回滚越界改动

```text
你在计划外修改了以下文件：A.java、B.java。
请只回滚这两个文件到 HEAD，保留其它改动，不要影响我已有的未提交内容。
```

> 回滚前先 `git stash` 或确认没有未提交的重要改动，避免误伤。

## 十、Maven、Gradle、npm 等项目验证

### 10.1 让 Codex 先跑最小验证

```text
先只编译，不跑全量测试：./mvnw -q -DskipTests compile
通过后再跑与本次改动相关的测试类。
```

### 10.2 常用命令速查

| 生态 | 编译 / 类型检查 | 测试 | 打包 |
| --- | --- | --- | --- |
| Maven | `./mvnw -q -DskipTests compile` | `./mvnw -q test` | `./mvnw -q -DskipTests package` |
| Gradle | `./gradlew compileJava` | `./gradlew test` | `./gradlew build` |
| npm | `npm run build` | `npm test` | `npm run build` |
| pnpm | `pnpm build` | `pnpm test` | `pnpm build` |

### 10.3 让 Codex 自己判断用哪个命令

```text
先只读检查仓库里有哪些构建文件（pom.xml / build.gradle / package.json），
告诉我正确的构建和测试命令，然后运行一次编译验证环境可用。
```

## 十一、处理多模块项目与复杂依赖

### 11.1 只构建相关模块

```bash
# Maven
./mvnw -q -pl services/order -am test

# Gradle
./gradlew :services:order:test

# pnpm workspace
pnpm --filter @app/order test
```

### 11.2 提示词里明确模块边界

```text
这是一个 Maven 多模块项目。
本次只修改 services/order 模块；如果必须改 common 模块，先告诉我原因。
验证命令：./mvnw -pl services/order -am -q test
```

### 11.3 依赖冲突排查

```bash
./mvnw -q dependency:tree -Dincludes=org.slf4j
./gradlew :services:order:dependencies --configuration runtimeClasspath
pnpm why lodash
```

让 Codex 分析输出：

```text
这是 dependency:tree 的输出（粘贴）。
找出被多个版本同时引入的依赖，说明冲突来源和收敛方案，先不要改 pom.xml。
```

---

下面是本文的后半部分：用 `codex review` 建立可重复的代码审查流程。

## 十二、让 Codex 审查当前 Git 改动

Codex 内置了专门的审查命令 `codex review`，它会以"审查者"的视角读改动，而不是直接动手改。

### 12.1 三种审查范围

```bash
# 审查未提交的改动（已暂存 + 未暂存 + 未跟踪）
codex review --uncommitted

# 审查当前分支相对某个基线的全部改动
codex review --base main

# 审查某一个提交引入的改动
codex review --commit 3f9a1c2
```

### 12.2 自定义审查要求

```bash
codex review --base main "重点检查事务边界、并发安全和 SQL 性能，
每条问题给出文件:行号、风险等级、复现条件和修复建议。"
```

也可以用 stdin 传入审查规则：

```bash
cat docs/review-checklist.md | codex review --uncommitted -
```

### 12.3 在 CI 里做审查

```bash
codex exec review --base origin/main "只报告阻断级问题，输出 JSON"
```

非交互模式下，审查结论可以接进流水线做门禁（第四篇会展开 CI 集成）。

![](assets/03-codex-review.webp)

## 十三、代码审查与自动修改的区别

这是最容易混淆的一点：

| | 审查（review） | 自动修改（实现） |
| --- | --- | --- |
| 目标 | 发现问题、给出证据 | 达成需求、产出代码 |
| 是否改文件 | 默认不改 | 会改 |
| 输出 | 问题清单 + 风险等级 | diff + 验证结果 |
| 适合时机 | 提交前、合并前 | 开发过程中 |

**先审查、再修改**，比让 Codex 一边审一边改要安全得多。因为它一旦动手，就可能把"看起来像问题"的地方顺手改掉，反而引入新问题。

推荐节奏：

```text
第一轮：codex review --uncommitted "只报告问题，不要改代码"
第二轮：人工筛选哪些问题确实要修
第三轮：codex "只修复第 2、5 条问题，其它不要动"
第四轮：再跑一次 codex review 确认没有回归
```

## 十四、Bug、异常处理与边界条件检查

把这几条固化进审查清单：

```text
请检查本次改动是否存在：
1. 空指针 / 数组越界 / 除零等基础风险；
2. 未处理的异常（吞异常、只打印不回滚）；
3. 边界条件：空集合、单元素、极大值、负数、null 字段；
4. 资源未关闭（流、连接、锁）；
5. 时间与时区处理错误；
6. 金额用浮点数计算；
7. 循环终止条件错误。
每条给出 文件:行号 + 触发条件 + 修复建议。
```

### 14.1 关注"异常被吞掉"

```text
检查是否出现 try-catch 后既不记录也不抛出的情况，
以及 catch 了过宽的异常类型（如 catch (Exception e)）却只打日志。
```

### 14.2 关注事务与异常的关系

```text
检查是否存在：事务方法内部捕获异常后没有重新抛出，
导致本该回滚的操作被提交。
```

## 十五、并发安全、SQL 与事务风险检查

这三类是线上事故的高发区，值得单独审。

### 15.1 并发安全

```text
检查本次改动是否引入并发问题：
1. 共享可变状态是否缺少同步或使用了非线程安全集合；
2. 是否有 check-then-act 竞态（先查再改）；
3. 缓存、单例、静态字段的可见性问题；
4. 定时任务是否可能重复执行。
```

### 15.2 SQL 与索引

```text
检查新增/修改的 SQL：
1. 是否有 N+1 查询；
2. 是否可能全表扫描（WHERE 条件未走索引）；
3. 是否有 `SELECT *`、缺 LIMIT 的大结果集；
4. 拼接 SQL 是否使用了字符串拼接而非参数绑定（SQL 注入）；
5. 批量操作是否分批。
```

### 15.3 事务

```text
检查事务相关问题：
1. @Transactional 是否加在 public 方法上、是否被同类内部调用绕过；
2. 事务范围是否过大（把远程调用、消息发送包进事务）；
3. 是否有长事务、锁等待风险；
4. 隔离级别是否合适，是否存在不可重复读 / 幻读风险。
```

## 十六、安全漏洞与敏感信息检查

### 16.1 常见漏洞

```text
以安全视角审查本次改动，重点看：
1. SQL 注入、命令注入、路径穿越；
2. 越权（水平/垂直权限校验缺失）；
3. 反序列化、SSRF、XXE；
4. 敏感信息写入日志或返回给前端；
5. 硬编码密钥、口令、Token；
6. 依赖是否存在已知高危 CVE。
每条给出 文件:行号 + 攻击场景 + 修复建议。
```

### 16.2 敏感信息扫描

```bash
# 看看有没有明显的密钥被带进来
git diff | grep -n -E "(password|secret|token|api[_-]?key|BEGIN [A-Z ]*PRIVATE KEY)" -i
```

```text
检查本次 diff 是否包含任何密钥、Token、连接串、真实用户数据。
如果有，明确指出位置，并给出改用环境变量或配置中心的方案。
```

> 一旦敏感信息被提交进 Git 历史，**改代码是没用的**，必须轮换密钥并清理历史。所以这一步要在提交前做。

## 十七、测试覆盖与回归验证

### 17.1 让审查关注测试

```text
审查本次改动：
1. 新增/修改的逻辑是否有对应测试；
2. 测试是否只覆盖了 happy path；
3. 断言是否足够强（不是只断言非空）；
4. 是否有被修改的测试断言（可能是在"迁就"实现）；
5. 列出仍然没有覆盖的分支。
```

### 17.2 用覆盖率工具兜底

```bash
# JaCoCo（Maven）
./mvnw -q test jacoco:report
open target/site/jacoco/index.html

# Jest（前端）
pnpm test --run --coverage
```

### 17.3 回归验证

```text
改动完成后：
1. 跑一次全量测试；
2. 与改动前对比失败用例列表，确认没有新增失败；
3. 贴出命令与结果摘要。
```

## 十八、避免无关格式化和大范围重构

### 18.1 审查时专门查这个

```text
本次 diff 中是否存在与需求无关的改动？包括：
1. 整文件格式化、换行符变化；
2. 无关的 import 重排、方法重排；
3. 顺手的重命名或"顺便优化"；
4. 依赖版本升级。
逐条列出并建议回滚。
```

### 18.2 用 `-w` 排除噪音

```bash
git diff -w
git diff --stat -w
```

如果 `git diff` 很大但 `git diff -w` 很小，说明大量改动只是空白差异，应当回滚。

### 18.3 从源头预防

在 `AGENTS.md` 里写死（见第二篇）：

```md
## 改动范围
- 禁止格式化无关文件、禁止批量重命名、禁止调整 import 顺序。
- 不做需求之外的"顺手优化"。
```

## 十九、AI 审查结果的误报与漏报

AI 审查**不是**全知全能的，要带着"它会错"的预期使用。

### 19.1 误报（说有问题其实没有）

常见原因：缺少上下文、不了解项目约定、把"风格差异"当成"错误"。

对策：

```text
你指出的第 3 条不符合本项目约定，原因：……
请重新评估，只保留确实成立的结论。
```

### 19.2 漏报（有问题它没发现）

常见原因：问题跨多个文件、依赖运行时行为、需要业务知识。

对策：

- **分维度多次审**：一次只审一个维度（并发、SQL、安全），比一次"全都看"更容易发现问题。
- **给出攻击/触发场景**：让它按具体场景推演，而不是泛泛扫描。
- **补上业务约束**：把领域规则写进提示词或 `AGENTS.md`。

```text
换一个角度重新审：假设并发 1000 QPS、数据库有 500 万行数据，
重新评估这次改动会不会出问题。只报告新发现。
```

### 19.3 人工终审不可省

> AI 审查用来**提高发现问题的概率**，而不是替代人的判断。合入决定必须由人来做。

## 二十、建立可重复执行的审查清单

把上面的内容固化成一份 `docs/review-checklist.md`，每次审查直接喂进去。

```md
# 代码审查清单

## 通用
- [ ] 改动是否只覆盖需求范围，没有无关格式化 / 重命名
- [ ] 公共 API 签名是否被意外修改

## 正确性
- [ ] 空值、边界值、极端输入
- [ ] 异常处理与资源释放
- [ ] 事务边界与回滚

## 并发与数据
- [ ] 共享状态与竞态
- [ ] SQL 是否走索引、有无 N+1
- [ ] 锁与长事务风险

## 安全
- [ ] 注入类漏洞
- [ ] 越权校验
- [ ] 密钥 / 敏感信息泄露

## 测试
- [ ] 新逻辑有测试，断言足够强
- [ ] 没有为迁就实现而修改测试断言
```

使用：

```bash
codex review --uncommitted "$(cat docs/review-checklist.md)"
```

再把它接进提交前流程：

```bash
# .git/hooks/pre-push（示例）
codex exec review --base origin/main "按 docs/review-checklist.md 审查，只报告阻断级问题" \
  && git push "$@"
```

### 20.1 让审查结果可追踪

```text
把本次审查结论写入 docs/reviews/2026-10-10-order-refactor.md，
格式：问题清单表格（严重级别 / 文件:行号 / 描述 / 状态）。
```

留档之后，同一个问题反复出现时就能回溯。

---

到这里，日常研发的完整闭环就跑通了。下一篇把 Codex 接上外部工具（MCP），并把它推进到可重复的自动化流程。

