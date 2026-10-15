+++
title = "多 Agent 协作"
date = 2026-10-11T00:00:00+08:00
weight = 16
tags = ["Agent", "多Agent", "Supervisor", "Planner", "协作"]
summary = "Agent 系列（七）：讲清多 Agent 的适用条件与成本，Supervisor、Planner/Executor 等协作模式，以及消息传递、并行汇总与冲突处理。"

+++

前六篇讲的都是"一个 Agent"。但有些任务，单 Agent 确实吃力：要同时调研、写代码、做测试，一个大脑既要又要，上下文越来越乱，指令越写越长，最后哪个都做不好。

于是就有了多 Agent：**把任务拆开，交给几个各有专长的 Agent，通过协作完成。**

但多 Agent 不是"人多了力量大"那么简单。它带来的协调成本、成本翻倍、循环调用等问题，往往比它解决的问题还多。这一篇的重点，是**先说清什么时候该用，再说怎么用。**

## 一、多 Agent 的适用条件与成本

### 1、什么时候值得用

单 Agent 遇到下面这些情况，才考虑上多 Agent：

- **上下文会互相污染**：一个 Agent 既要做客服又要做数据分析，两套知识和指令混在一起，互相干扰。
- **需要不同专长**：编码、设计、测试、审查，需要的知识和工具完全不同。
- **可以并行**：几个子任务互不依赖，能同时做，节省时间。
- **单个 Agent 指令太长**：为了覆盖所有场景，System Prompt 写了上千字，模型反而抓不住重点。
- **需要互相检查**：一个生成、一个审查，能提高质量。

### 2、成本

多 Agent 的代价很直接：

| 成本 | 说明 |
| --- | --- |
| Token 翻倍 | 每个 Agent 都要调模型，任务分解、结果汇总还要额外调用 |
| 延迟增加 | 串行协作时，总时间 = 各 Agent 时间之和 |
| 协调复杂 | 谁调谁、消息怎么传、结果怎么合，都要设计 |
| 容易跑偏 | Agent 之间可能来回甩锅，陷入循环 |
| 难调试 | 出问题时，要跨多个 Agent 的日志才能定位 |

**一条务实的原则：能用单 Agent 做好的，就不要上多 Agent。** 先用单 Agent + 好的工具 + 好的上下文管理，多数场景就够了。真的遇到上面那些瓶颈，再拆。

### 3、拆分的维度

如果确定要拆，按什么拆？常见三种：

- **按能力拆**：调研 Agent、编码 Agent、测试 Agent。
- **按领域拆**：法务 Agent、财务 Agent、技术 Agent。
- **按阶段拆**：规划 Agent、执行 Agent、审查 Agent。

## 二、Supervisor 调度模式

最常用的多 Agent 模式，是 Supervisor（主管）。

### 1、结构

一个主管 Agent 负责调度，几个工人 Agent 负责干活。

```text
                ┌──────────────┐
                │  Supervisor  │
                │  （主管）     │
                └──────┬───────┘
             ┌─────────┼─────────┐
             ▼         ▼         ▼
        ┌────────┐ ┌────────┐ ┌────────┐
        │ 调研   │ │ 编码   │ │ 测试   │
        │ Agent  │ │ Agent  │ │ Agent  │
        └────────┘ └────────┘ └────────┘
```

主管的职责：

- **理解用户需求**。
- **决定把任务派给谁**。
- **收集各 Agent 的结果**。
- **决定是继续派活还是给出最终答案**。

### 2、主管怎么决策

主管本身也是一个 Agent，它手上的"工具"就是"调用某个子 Agent"。

```java
// 主管的工具：把任务派给子 Agent
@Tool(description = "把调研任务交给调研 Agent，输入是具体要调研的问题")
public String callResearcher(
        @ToolParam(description = "要调研的具体问题") String question) {
    return researcherAgent.run(question);
}

@Tool(description = "把编码任务交给编码 Agent，输入是明确的编码需求")
public String callCoder(
        @ToolParam(description = "编码需求描述") String requirement) {
    return coderAgent.run(requirement);
}
```

这样主管就是一个普通的 Agent，只不过它的工具是"别的 Agent"。**这个视角很重要：多 Agent 协作，本质上是"Agent 即工具"。**

### 3、Supervisor 的循环

```text
用户：做一个用户登录功能的竞品分析，并给出实现建议

Supervisor 思考：先让调研 Agent 收集信息
  → callResearcher("主流产品的登录方式有哪些")
调研 Agent 返回：密码、验证码、第三方、生物识别...

Supervisor 思考：还需要看技术实现
  → callCoder("调研主流登录方案的实现要点")
编码 Agent 返回：JWT、Session、OAuth2 的对比...

Supervisor 思考：信息够了
  → 汇总输出最终答案
```

### 4、Supervisor 的护栏

主管最容易犯的错是**反复派活、绕圈**。要加护栏：

- **最大轮数**：比如最多 10 轮调度。
- **重复检测**：同一任务派了两次就提示。
- **完成判断**：明确"什么情况下算完成"。

## 三、Planner 与 Executor 模式

Supervisor 是"边做边想"，Planner/Executor 是"先想清楚再做"。

### 1、结构

```text
        ┌──────────┐
用户 ──►│ Planner  │──► 计划：[步骤1, 步骤2, 步骤3]
        └──────────┘              │
                                  ▼
                          ┌──────────────┐
                          │  Executor    │──► 逐步执行
                          └──────────────┘
                                  │
                                  ▼
                             汇总结果
```

- **Planner**：把大目标拆成有序的子任务清单。
- **Executor**：按清单逐个执行，可以是一个 Agent，也可以是一组 Agent。

### 2、Planner 的输出

Planner 的输出是一份**结构化计划**：

```java
public record Plan(List<Step> steps) {}

public record Step(
        int order,
        String description,     // 做什么
        String assignee,        // 谁来做
        List<String> dependsOn  // 依赖哪几步
) {}
```

```json
{
  "steps": [
    { "order": 1, "description": "调研竞品登录方式", "assignee": "researcher", "dependsOn": [] },
    { "order": 2, "description": "整理技术方案对比", "assignee": "analyst", "dependsOn": [1] },
    { "order": 3, "description": "给出实现建议", "assignee": "coder", "dependsOn": [2] }
  ]
}
```

### 3、为什么先规划

"先规划"的好处：

- **全局视角**：先想清楚整体路线，避免走一步看一步。
- **可并行**：`dependsOn` 为空且互不依赖的步骤，可以同时执行。
- **可审查**：计划可以给人看，人可以在执行前就纠正方向。
- **可恢复**：计划是显式的，某一步失败可以重试那一步，不影响其他。

### 4、动态重规划

计划不一定一次就对。执行中发现新情况，可以让 Planner 重新规划：

```text
执行步骤 2 时发现：竞品资料缺失
  → 触发重规划
  → 新计划：先补充资料收集，再整理方案
```

**重规划要有上限**，否则可能一直在改计划。

## 四、专家 Agent 分工

每个专家 Agent 有自己的专长，靠三样东西区分：

### 1、不同的 System Prompt

```java
String researcherPrompt = """
        你是资深市场调研专家。擅长收集、交叉验证信息，
        输出结构化的调研结论，标注信息来源。
        """;

String coderPrompt = """
        你是资深后端工程师。擅长 Java、Spring 生态，
        给出可落地的技术方案，注意性能和可维护性。
        """;
```

### 2、不同的工具

调研 Agent 给搜索工具、抓取工具；编码 Agent 给代码执行、文件读写工具。

```java
ChatClient researcher = ChatClient.builder(model)
        .defaultSystem(researcherPrompt)
        .defaultTools(new SearchTools(), new FetchTools())
        .build();

ChatClient coder = ChatClient.builder(model)
        .defaultSystem(coderPrompt)
        .defaultTools(new FileTools(), new CodeExecTools())
        .build();
```

### 3、不同的上下文

每个 Agent 只看自己需要的上下文，**这是多 Agent 最大的好处之一**：上下文干净了，模型判断更准。

```text
调研 Agent 的上下文：调研问题 + 搜索工具
编码 Agent 的上下文：需求描述 + 代码规范 + 代码工具
```

**注意：上下文隔离是双刃剑。** 隔离避免了干扰，但也意味着编码 Agent 看不到调研 Agent 收集的资料——所以**结果必须显式传递**。

## 五、Agent 之间的消息传递

Agent 之间怎么通信，是设计的关键。

### 1、传什么

不要传整个对话历史（太长、有噪声），而是传**结构化的结果**：

```java
public record AgentMessage(
        String from,
        String to,
        String taskId,
        String type,        // REQUEST / RESULT / ERROR
        String content,     // 内容
        Map<String, Object> artifacts   // 附件（文件、数据）
) {}
```

### 2、怎么传

- **直接调用**：主管同步调用子 Agent，拿返回值。简单，但阻塞。
- **消息队列**：通过 MQ 异步传递。解耦，适合长任务和并行。
- **共享状态**：都读写同一个状态对象。简单，但要注意并发。

```text
同步调用（主管模式）：
  Supervisor ──call──► Researcher ──return──► Supervisor

异步消息（长任务）：
  Supervisor ──MQ──► [队列] ──► Researcher ──MQ──► [队列] ──► Supervisor
```

### 3、消息要精简

Agent 之间传的消息**只带必要信息**：

```text
❌ 把调研 Agent 的完整对话历史传给编码 Agent
✅ 只传调研结论：{ "登录方式": ["密码", "验证码", "第三方"], "推荐": "密码+验证码" }
```

**传结论，不传过程。** 过程留在各自的上下文里，结论才需要在 Agent 之间流转。

## 六、共享状态与独立上下文

多 Agent 在状态管理上，有两种模式。

### 1、共享状态

所有 Agent 读写同一份状态。

```text
        ┌──────────────────────────┐
        │      共享状态             │
        │  goal / findings / plan  │
        └────┬────────┬────────┬───┘
             │        │        │
             ▼        ▼        ▼
         Agent A  Agent B  Agent C
```

优点是信息透明，谁都能看到全局。缺点是**容易互相覆盖、互相干扰**。

### 2、独立上下文 + 消息传递

每个 Agent 有自己的上下文，通过消息交换信息。

```text
  Agent A（上下文A）──消息──► Agent B（上下文B）
```

优点是上下文干净，缺点是**信息要显式传递，可能丢**。

### 3、怎么选

一个实用的组合：

```text
共享状态：只放"任务级"的信息（目标、计划、最终结论）
独立上下文：各 Agent 自己的推理过程、中间细节
```

**共享状态保持精简，细节留在各自的上下文里。** 这和第 5 篇讲的"中间结果管理"是同一个思路：上下文里放结论，细节放外部。

## 七、任务分解与子任务依赖

任务分解做得好不好，直接决定多 Agent 的成败。

### 1、分解的原则

- **子任务边界清晰**：每个子任务有明确的输入和输出。
- **尽量低耦合**：子任务之间依赖越少越好。
- **可独立验证**：每个子任务的结果能单独判断对错。
- **粒度适中**：太粗（一个 Agent 干不完）、太细（调度开销大）都不好。

### 2、依赖的表达

用 DAG（有向无环图）表达依赖：

```text
         ┌─────────┐
         │ 任务1   │
         └────┬────┘
              ▼
         ┌─────────┐
         │ 任务2   │
         └────┬────┘
        ┌─────┴─────┐
        ▼           ▼
   ┌─────────┐ ┌─────────┐
   │ 任务3   │ │ 任务4   │   ← 3 和 4 可并行
   └────┬────┘ └────┬────┘
        └─────┬─────┘
              ▼
         ┌─────────┐
         │ 任务5   │
         └─────────┘
```

```java
public record Step(int order, String description, List<Integer> dependsOn) {}

// 找出当前可以执行的步骤（依赖都已完成）
List<Step> ready = steps.stream()
        .filter(s -> !completed.contains(s.order()))
        .filter(s -> completed.containsAll(s.dependsOn()))
        .toList();
```

### 3、环的检测

DAG 不能有环。如果依赖关系里有环（A 等 B、B 等 A），任务永远执行不了。**分解后要检测有没有环。**

## 八、并行执行与结果汇总

### 1、并行执行

互不依赖的步骤，可以并行跑，节省时间。

```java
List<CompletableFuture<StepResult>> futures = readySteps.stream()
        .map(step -> CompletableFuture.supplyAsync(
                () -> executeStep(step), executor))
        .toList();

CompletableFuture.allOf(futures.toArray(new CompletableFuture[0])).join();
```

### 2、并行的收益与代价

```text
串行：任务3(30s) → 任务4(30s)         总耗时 60s
并行：任务3(30s) ┐
                ├─ 同时跑              总耗时 30s
      任务4(30s) ┘
```

收益是时间，代价是：

- **并发压力**：同时调多个模型，可能触发限流。
- **结果汇总变复杂**：要等所有分支完成，还要处理某个分支失败。
- **顺序不确定**：结果回来的顺序不确定，汇总逻辑要考虑。

### 3、结果汇总

汇总不是简单拼接，而是**综合判断**：

```text
调研结论：主流方案是密码 + 验证码
技术结论：JWT 适合无状态，Session 适合可控
        │
        ▼
   汇总 Agent 综合判断：
   建议采用 JWT + 密码/验证码，兼顾无状态和安全性
```

汇总可以：
- 用规则拼接（简单场景）。
- 用一个汇总 Agent 综合（需要判断时）。

**汇总时要处理冲突**：如果两个 Agent 的结论矛盾，要么让汇总 Agent 判断，要么把冲突暴露出来让人决策。

## 九、多 Agent 冲突与循环调用

这是多 Agent 最容易出问题的地方。

### 1、冲突

```text
编码 Agent：建议用 JWT
安全 Agent：JWT 容易被窃取，建议用 Session
```

冲突本身不一定是坏事，**它说明不同视角看到了不同问题**。关键是处理方式：

- **让仲裁者判断**：加一个仲裁 Agent，或者让 Supervisor 决策。
- **暴露给人**：重要决策不要自动拍板，把冲突给人看。
- **定规则**：事先约定"安全优先于性能"这类原则。

### 2、循环调用

最危险的情况：Agent 之间互相调用，停不下来。

```text
A 让 B 做事 → B 觉得该 A 先做 → B 让 A 做 → A 又让 B...   ← 死循环
```

对策：

- **限制调用深度**：A 调 B，B 最多再调一层，不能无限嵌套。
- **限制总轮数**：整个协作过程最多 N 轮。
- **检测重复**：同一个任务被派了两次，就打断。
- **超时**：整体超时，强制结束。

```java
public class CollaborationGuard {
    private static final int MAX_ROUNDS = 15;
    private static final int MAX_DEPTH = 3;

    private int rounds = 0;
    private final Set<String> seenTasks = new HashSet<>();

    public void checkRound() {
        if (++rounds > MAX_ROUNDS) {
            throw new CollaborationLimitException("协作轮数超过上限");
        }
    }

    public void checkDuplicate(String taskKey) {
        if (!seenTasks.add(taskKey)) {
            throw new CollaborationLimitException("任务重复派发：" + taskKey);
        }
    }
}
```

### 3、成本失控

多 Agent 最容易"不知不觉烧掉很多钱"。要做好**成本预算**：

```text
整个协作任务预算：最多 20 次模型调用，最多 10 万 token
超出预算 → 中断，返回已有结果 + 提示
```

## 十、如何评估多 Agent 是否优于单 Agent

上多 Agent 之前，先问一个问题：**它真的比单 Agent 好吗？** 不要凭感觉，要测。

### 1、怎么对比

用同一批任务，分别跑单 Agent 和多 Agent，对比：

| 指标 | 说明 |
| --- | --- |
| 任务成功率 | 多 Agent 是不是真的做对了更多 |
| 质量 | 结果是不是更好（人工评或自动评） |
| 成本 | Token 消耗、模型调用次数 |
| 延迟 | 总耗时 |
| 稳定性 | 结果波动大不大 |

### 2、常见的结论

实践中经常出现的情况：

- **简单任务**：单 Agent 又快又便宜，多 Agent 纯属浪费。
- **需要多种专长的复杂任务**：多 Agent 质量明显更好。
- **可并行的任务**：多 Agent 在时间上有优势。
- **需要互相校验的任务**：多 Agent（生成 + 审查）能减少错误。

### 3、判断框架

```text
任务复杂吗？
  ├── 不复杂 → 单 Agent
  └── 复杂
        ├── 需要多种专长/工具吗？
        │     ├── 需要 → 考虑多 Agent
        │     └── 不需要 → 单 Agent（可能只是 Prompt 没写好）
        └── 能并行吗？
              ├── 能 → 多 Agent 有延迟优势
              └── 不能 → 权衡质量和成本
```

**一句话：多 Agent 是为"复杂、需要专长分工、可并行"的任务准备的。简单任务上多 Agent，只会更贵更慢更不稳。**

## 十一、实践验证：搭一个多 Agent 协作的旅游规划团队

前面讲了 Supervisor、Planner/Executor 和各种协作模式，这一节用 Spring AI Alibaba 1.1 的 `ReactAgent` + 工作流 Agent 搭一个旅游规划团队，把"专家分工""主管调度""并行执行"都跑一遍。

### 1、先建几个专家 Agent

每个专家有自己的名字、描述和工具，也就是有自己的**职责边界**：

```java
// 费用统筹 Agent
ReactAgent budgetAgent = ReactAgent.builder()
        .name("budgetAgent")
        .description("你是负责统筹旅游费用")
        .build();

// 路线制定 Agent：把"费用统筹"作为工具挂进来
ReactAgent routeMakingAgent = ReactAgent.builder()
        .name("routeMakingAgent")
        .description("你是负责制定旅游出行路线")
        .tools(AgentTool.getFunctionToolCallback(budgetAgent))   // Agent 即工具
        .build();

// 行程规划 Agent：同样挂上费用统筹
ReactAgent tripPlannerAgent = ReactAgent.builder()
        .name("tripPlannerAgent")
        .description("你是负责规划旅游行程")
        .tools(AgentTool.getFunctionToolCallback(budgetAgent))
        .build();
```

这里有个关键点：**`AgentTool.getFunctionToolCallback(budgetAgent)` 把一个 Agent 包装成了另一个 Agent 的工具**。这正是前面讲的"Agent 即工具"——多 Agent 协作本质上就是一个 Agent 调用另一个 Agent。

### 2、用工作流 Agent 组织协作

`ReactAgent` 是"自主决策"的 Agent，而 `SequentialAgent` / `ParallelAgent` / `LlmRoutingAgent` 是**工作流 Agent**，负责按流程把多个 Agent 组织起来：

```java
// 并行 Agent：路线制定和行程规划没有依赖，可以同时跑
ParallelAgent parallelAgent = ParallelAgent.builder()
        .name("parallelAgent")
        .description("路线制定和行程规划是并行执行")
        .subAgents(List.of(tripPlannerAgent, routeMakingAgent))
        .build();

// 路由 Agent：让大模型动态决定把任务分给谁（Supervisor 思路）
LlmRoutingAgent llmRoutingAgent = LlmRoutingAgent.builder()
        .name("llmRoutingAgent")
        .description("将旅游出行工具选择和景点、住宿规划分发给对应的智能体")
        .subAgents(List.of(tripPlannerAgent, routeMakingAgent))
        .build();

// 顺序 Agent：把路由和并行按顺序串起来
SequentialAgent sequentialAgent = SequentialAgent.builder()
        .name("sequentialAgent")
        .subAgents(List.of(llmRoutingAgent, parallelAgent))
        .build();
```

四种 Agent 的分工对照前面：

| 代码里的类型 | 对应前面的模式 | 职责 |
| --- | --- | --- |
| `ReactAgent` | 专家 Agent | 自主决策、调工具 |
| `LlmRoutingAgent` | Supervisor 调度 | 用大模型动态分发任务 |
| `ParallelAgent` | 并行执行 | 无依赖的子任务同时跑 |
| `SequentialAgent` | 流程编排 | 按顺序串联各阶段 |

### 3、运行

```java
Optional<OverAllState> res = sequentialAgent.invoke(
        "帮我规划深圳到惠州的3天旅游行程");
```

整体流程是：

```text
sequentialAgent
   ├── llmRoutingAgent    → 判断该谁来接（路由）
   └── parallelAgent      → 路线制定 ‖ 行程规划（并行）
            ├── routeMakingAgent ──► budgetAgent
            └── tripPlannerAgent ──► budgetAgent
```

![image-20261011107000001](assets/image-20261011107000001.png)

![image-20261011107000002](assets/image-20261011107000002.png)

### 4、这一步验证了什么

- **专家分工靠"名字 + 描述 + 工具"**：每个 `ReactAgent` 的 `description` 就是它的职责说明，`tools` 就是它的能力边界。
- **Agent 即工具**：`AgentTool.getFunctionToolCallback(budgetAgent)` 印证了"多 Agent 协作本质是 Agent 互相调用"。
- **Supervisor 模式落地**：`LlmRoutingAgent` 用大模型做动态路由，就是"主管 Agent"的思路。
- **并行真的能省时间**：`ParallelAgent` 让路线和行程两条链路同时跑——对应"并行执行与结果汇总"。
- **工作流 Agent 与 ReAct Agent 是两层**：前者管"流程怎么走"，后者管"这一步怎么自主完成"，正好是前面开头讲的"Workflow 搭骨架、Agent 填血肉"。

> 这里把预算 Agent 同时挂给了两个 Agent，真实场景要注意**循环调用**：A 调 B、B 又调 A 会死循环。前面"多 Agent 冲突与循环调用"讲的护栏（最大深度、重复检测、预算上限）在生产环境必须加上。

## 小结

这一篇把多 Agent 讲透了：

- **能用单 Agent 做好的，就别上多 Agent**，它的协调成本和 Token 成本都很高。
- **Supervisor 模式**最常用，本质是"Agent 即工具"。
- **Planner/Executor 模式**先规划再执行，全局视角、可并行、可审查。
- **专家 Agent** 靠不同的 Prompt、工具、上下文区分。
- Agent 之间**传结论，不传过程**；共享状态只放任务级信息。
- 任务分解要**边界清晰、低耦合、可独立验证**，用 DAG 表达依赖，注意检测环。
- **并行执行**省时间，但要处理并发压力、结果汇总和失败分支。
- **冲突要仲裁或暴露给人，循环调用要加护栏，成本要有预算。**
- 上多 Agent 前，**用数据对比它是否真的优于单 Agent**。

到这里，Agent 之间怎么协作讲完了。但这些 Agent 要接入外部工具，如果每个工具都自己写一套对接，成本太高。业界正在用一个标准协议来解决这个问题——MCP。下一篇：《MCP 与 Agent 工具生态》。
