+++
title = "Agent 工作流与状态图"
date = 2026-10-11T00:00:00+08:00
weight = 15
tags = ["Agent", "工作流", "状态图", "Graph", "Human-in-the-Loop"]
summary = "Agent 系列（六）：从 Workflow 与 Agent Loop 的区别讲起，说清节点、边、状态与条件路由，以及检查点、中断恢复、人工审批和幂等控制。"

+++

前面几篇，Agent 的执行方式一直是"一个循环转到底"。这种方式灵活，但有个问题：**不好控。**

真实业务里，流程往往是有明确环节的——先审核、再执行、最后归档。这种时候，我们不想让模型自由发挥，而是希望**把流程固定下来，只在需要判断的地方交给模型**。

这就是工作流编排要解决的事。这一篇讲怎么用"状态图"把 Agent 的执行过程组织起来，让它可控、可恢复、可观察。

## 一、Workflow 与 Agent Loop 的区别

先回顾第一篇讲过的一个区分，这里把它讲透。

### 1、Agent Loop

Agent Loop 是"模型驱动"的：走哪一步、走几步，都是模型运行时决定的。

```text
while (未完成) {
    决策 = 模型(上下文)
    if (决策是工具调用) {
        结果 = 执行工具(决策)
        上下文 += 结果
    } else {
        return 决策.答案
    }
}
```

优点是灵活，能应对不确定的路径。缺点是**不可控**：可能绕圈、可能走偏、可能步数失控。

### 2、Workflow

Workflow 是"人驱动"的：步骤和流转条件都是预先定义好的。

```text
接收请求 → 校验参数 → 查询数据 → 判断是否需要人工 → 返回结果
```

优点是可控、可预测、好测试。缺点是**不灵活**：遇到没预设的情况就处理不了。

### 3、两者结合

成熟的做法是**用 Workflow 搭骨架，用 Agent Loop 填血肉**：

```text
┌─────────┐   ┌─────────┐   ┌──────────────┐   ┌─────────┐
│ 接收请求 │──►│ 预处理   │──►│ Agent 环节    │──►│ 后处理   │
└─────────┘   └─────────┘   │（模型自主决策）│   └─────────┘
                             └──────────────┘
```

固定的部分用工作流，不确定的部分交给 Agent。**哪一步需要"自主决策"，哪一步才上 Agent。**

## 二、节点、边、状态与条件路由

工作流用"图"来描述，核心概念有四个。

### 1、节点（Node）

节点是流程里的一个执行单元，可以是：

- 一个普通的 Java 方法（确定性逻辑）。
- 一次模型调用。
- 一个 Agent（带工具循环）。
- 一个工具调用。
- 一个人工审批环节。

```java
// 一个节点就是一个函数：输入 State，输出 State 的更新
public Map<String, Object> validateParams(AgentState state) {
    // 校验逻辑
    return Map.of("validated", true);
}
```

**注意节点的签名：输入是状态，输出是对状态的更新。** 这样节点之间就通过状态解耦了。

### 2、边（Edge）

边是节点之间的连线，表示"执行完 A 之后去 B"。

```text
A ──► B ──► C
```

### 3、状态（State）

状态在整个图的执行过程中流转，每个节点都能读它、改它。

```java
public class WorkflowState {
    private Map<String, Object> data = new HashMap<>();

    public <T> T get(String key) { ... }
    public void put(String key, Object value) { ... }
}
```

**状态是工作流的中枢。** 节点之间不直接传参，而是通过状态交互，这样加节点、改顺序都不影响其他节点。

### 4、条件路由（Conditional Edge）

边不一定是固定的，可以根据状态动态决定走哪条路。

```text
                    ┌── 金额 <= 500 ──► 自动审批
判断金额 ───────────┤
                    └── 金额 > 500  ──► 人工审批
```

在 Spring AI Alibaba 的 Graph 里，条件边就是一个返回"下一个节点名"的函数：

```java
// 条件路由：根据状态决定下一步
graph.addConditionalEdges(
        "checkAmount",
        state -> {
            BigDecimal amount = state.get("amount", BigDecimal.class);
            return amount.compareTo(new BigDecimal("500")) <= 0
                    ? "autoApprove"
                    : "manualApprove";
        },
        Map.of(
                "autoApprove", "autoApprove",
                "manualApprove", "manualApprove"
        )
);
```

**条件路由是工作流"有智能"的地方**：它不是写死的顺序，而是根据运行时的数据决定走向。

## 三、顺序执行、分支与循环

图能表达的三种基本结构。

### 1、顺序执行

最简单的结构，A 完了 B，B 完了 C。

```text
A ──► B ──► C
```

```java
graph.addNode("fetchData", this::fetchData);
graph.addNode("analyze", this::analyze);
graph.addNode("report", this::report);

graph.addEdge(START, "fetchData");
graph.addEdge("fetchData", "analyze");
graph.addEdge("analyze", "report");
graph.addEdge("report", END);
```

### 2、分支

根据条件走不同的路。

```text
        ┌──► 路径 A ──┐
判断 ───┤             ├──► 汇合
        └──► 路径 B ──┘
```

### 3、循环

回到之前的节点，重复执行。循环要**有明确的退出条件**，否则会死循环。

```text
        ┌───────────────┐
        │               │
        ▼               │
    处理一步 ──► 完成了吗？
                    │
                    ├── 否 ──┘
                    └── 是 ──► 结束
```

```java
graph.addConditionalEdges(
        "processStep",
        state -> state.get("done", Boolean.class) ? END : "processStep"
);
```

**循环必须有护栏**：最大轮数、超时、或者状态里的进度判断。**没有退出条件的循环，就是线上事故。**

## 四、节点输入输出与状态更新

节点怎么读写状态，是工作流设计的关键细节。

### 1、读

节点从状态里取自己需要的数据：

```java
public Map<String, Object> analyze(WorkflowState state) {
    String text = state.get("inputText", String.class);
    // ...
}
```

### 2、写

节点返回"要更新的字段"，而不是返回整个状态：

```java
public Map<String, Object> analyze(WorkflowState state) {
    String text = state.get("inputText", String.class);
    String result = doAnalyze(text);
    return Map.of("analysisResult", result);   // 只返回更新的字段
}
```

这样做的意义：

- **节点之间解耦**：节点不需要知道状态的全部内容。
- **更新可追溯**：能看出是哪个节点改了哪个字段。
- **便于合并**：多个并行节点各自返回更新，再统一合并。

### 3、字段的覆盖与累加

状态更新有两种语义，要分清楚：

- **覆盖**：新值直接替换旧值。适合"当前状态"这类字段。
- **追加**：新值加到列表里。适合"历史记录""已完成步骤"这类。

```java
// 覆盖：当前步骤
state.put("currentStep", "analyze");

// 追加：消息历史（用 reducer 合并）
// 多个节点/并行分支各自返回消息，最终合并成一个列表
```

**并行分支时，追加语义特别重要**：几个分支各自产生的结果，要能合并到一起，而不是互相覆盖。

## 五、Graph 编排与普通函数调用的区别

有人会问：这些用普通函数调用不也能写吗？为什么要用图？

对比一下同一段逻辑的两种写法。

**普通函数调用：**

```java
public Result handle(Request req) {
    var validated = validate(req);
    var data = fetch(validated);
    if (needApproval(data)) {
        var approved = manualApprove(data);
        return report(approved);
    }
    return report(data);
}
```

**状态图：**

```java
graph.addNode("validate", this::validate);
graph.addNode("fetch", this::fetch);
graph.addNode("approve", this::manualApprove);
graph.addNode("report", this::report);
graph.addEdge(START, "validate");
graph.addEdge("validate", "fetch");
graph.addConditionalEdges("fetch", this::route, ...);
```

看起来图更啰嗦，但它带来几个普通函数没有的能力：

| 能力 | 普通函数 | 状态图 |
| --- | --- | --- |
| 中断后恢复 | 难（调用栈丢了） | 支持（状态在图里） |
| 可视化 | 无 | 能画出流程图 |
| 人工介入 | 难（同步阻塞） | 支持（中断等待） |
| 并行执行 | 要手写线程 | 声明式支持 |
| 步骤级重试 | 要自己包 | 可按节点配置 |
| 执行记录 | 要自己埋点 | 天然有节点级记录 |

**核心差别在于"状态在谁手里"。** 普通函数的中间状态在调用栈里，函数一中断就没了；状态图的状态是显式的、可持久化的，所以能中断、能恢复、能观察。

**如果流程很短、不需要中断恢复和人工介入，用普通函数就够了，不必上图。** 图是为"长流程、要可控、要恢复"准备的。

## 六、检查点与中断恢复

这是状态图最有价值的能力。

### 1、检查点（Checkpoint）

检查点就是**在每一步执行后，把当前状态保存下来**。

```text
执行节点 A ──► 保存检查点 ──► 执行节点 B ──► 保存检查点 ──► ...
```

有了检查点，任何一步出问题，都能从上一个检查点恢复，不用从头再来。

```java
// Spring AI Alibaba Graph 里配置检查点保存
CompiledGraph graph = stateGraph.compile(
        CompileConfig.builder()
                .saverConfig(SaverConfig.builder()
                        .type(SaverType.REDIS)   // 存到 Redis
                        .build())
                .build()
);
```

### 2、中断（Interrupt）

中断是**主动暂停**流程，等外部条件满足再继续。最常见的场景是人工审批。

```java
// 在需要人工确认的地方，主动中断
graph.addNode("requestApproval", state -> {
    // 抛出中断，等待人工输入
    return Map.of("__interrupt__", "等待审批");
});
```

### 3、恢复

恢复时，从检查点加载状态，带上人工的输入，继续往下走。

```java
// 恢复执行，带上人工审批结果
RunnableConfig config = RunnableConfig.builder()
        .threadId(taskId)          // 用 threadId 找回检查点
        .build();

graph.invoke(Map.of("approved", true), config);
```

### 4、为什么这套机制重要

看一个具体的场景：一个退款审批流程，需要人工审核。

```text
提交退款 ──► 校验 ──► 中断（等审批）──► 人工审批 ──► 执行退款 ──► 完成
                          │
                    （可以等几分钟、几小时、几天）
```

- 中断期间，**服务可以重启，状态不会丢**。
- 审批人可能在几小时后才处理，**流程要能等**。
- 恢复时**从断点继续**，不用重新跑前面的步骤。

**这是"同步阻塞等审批"做不到的。** 如果用同步等待，一个审批挂几小时，线程早耗光了。

## 七、人工审批与 Human-in-the-Loop

Human-in-the-Loop（人在回路中）是让 Agent 可控的重要手段。

### 1、什么时候需要人工

- **不可逆操作**：退款、删除、发消息。
- **金额/风险超阈值**：超过一定金额。
- **模型不确定**：置信度低、多次失败。
- **合规要求**：某些业务必须人工确认。

### 2、审批的几种模式

```text
① 执行前审批：Agent 准备好参数，人确认后才执行
② 执行中审批：关键步骤暂停，人确认后继续
③ 执行后审批：先执行，人复核，不对就回滚
```

**不可逆操作用①，可控流程用②，可回滚的用③。**

### 3、审批的信息要给全

让人做审批，就要给人足够的信息：

```text
待审批事项：
  操作：退款
  订单：20261011001000000001
  金额：1280.00 元
  原因：用户反馈商品质量问题
  申请人：客服小张
  风险提示：该订单已退款过一次

[ 通过 ]  [ 驳回 ]
```

信息不全，审批就是走过场。

### 4、审批也要有超时和兜底

审批不能无限等。要有超时策略：

```text
超时未审批 → 自动驳回 / 转交上级 / 提醒催办
```

## 八、节点重试、超时与错误分支

工作流要处理"某一步失败"的情况。

### 1、节点级重试

不同节点的重试策略应该不一样：

```java
graph.addNode("fetchExternal", this::fetchExternal,
        NodeConfig.builder()
                .maxRetries(3)
                .retryInterval(Duration.ofSeconds(1))
                .build());

// 写操作不重试，或者只在确认幂等时重试
graph.addNode("submitRefund", this::submitRefund,
        NodeConfig.builder()
                .maxRetries(0)
                .build());
```

### 2、节点超时

```java
NodeConfig.builder()
        .timeout(Duration.ofSeconds(30))
        .build();
```

### 3、错误分支

失败不一定要终止流程，可以走"错误分支"：

```text
                 ┌── 成功 ──► 继续
调用外部服务 ────┤
                 └── 失败 ──► 降级处理 ──► 记录告警 ──► 结束
```

```java
graph.addConditionalEdges(
        "callService",
        state -> state.get("success", Boolean.class) ? "next" : "fallback"
);
```

**把错误当成一种正常的分支来处理**，而不是让异常直接冒出来中断整个流程。这样流程更健壮，也更容易观察失败发生在哪一步。

## 九、工作流幂等性与重复执行控制

工作流经常需要"重试"和"恢复"，这就要求**重复执行不能产生副作用**。

### 1、为什么需要幂等

```text
执行"扣款"节点 → 成功 → 保存检查点失败 → 恢复 → 又执行一次"扣款"
```

如果不幂等，就扣了两次钱。这类问题在长流程里非常常见。

### 2、怎么做幂等

**（1）幂等键**

每次操作带一个唯一键，服务端判断"这个键处理过没有"。

```java
public Map<String, Object> submitRefund(WorkflowState state) {
    String idempotencyKey = state.get("taskId", String.class) + ":refund";
    if (idempotencyStore.exists(idempotencyKey)) {
        return Map.of("refundResult", idempotencyStore.get(idempotencyKey));
    }
    var result = refundService.refund(...);
    idempotencyStore.save(idempotencyKey, result);
    return Map.of("refundResult", result);
}
```

**（2）状态检查**

执行前先看状态，已经做过就跳过。

```java
if (state.get("refundDone", Boolean.class)) {
    return Map.of();   // 已经做过了，跳过
}
```

**（3）去重表**

用数据库的唯一索引兜底：

```sql
CREATE TABLE operation_log (
    idempotency_key VARCHAR(128) PRIMARY KEY,
    result TEXT,
    created_at TIMESTAMP
);
```

**核心原则：凡是会改变外部状态的操作，都要能安全地重复执行。**

## 十、工作流执行记录与可视化追踪

### 1、执行记录

每一步都要记录：

```text
taskId: task_20261011_001
├── [10:00:01] node=validate    status=OK      cost=12ms
├── [10:00:02] node=fetch       status=OK      cost=340ms
├── [10:00:05] node=checkAmount status=OK      result=needApproval
├── [10:00:05] node=approve     status=WAITING (中断)
└── [10:30:12] node=approve     status=OK      approved=true (恢复)
```

有了这份记录：

- **排障**：哪一步慢了、哪一步错了，一目了然。
- **审计**：谁在什么时候审批了什么。
- **优化**：统计各节点耗时，找到瓶颈。

### 2、可视化

状态图的好处之一，是能**自动画出流程图**：

```text
        ┌──────────┐
        │  START   │
        └────┬─────┘
             ▼
        ┌──────────┐
        │ validate │
        └────┬─────┘
             ▼
        ┌──────────┐
        │  fetch   │
        └────┬─────┘
             ▼
        ┌──────────────┐
        │ checkAmount  │
        └──┬────────┬──┘
      ≤500 │        │ >500
           ▼        ▼
    ┌──────────┐ ┌──────────┐
    │ autoPass │ │ approve  │
    └────┬─────┘ └────┬─────┘
         └─────┬──────┘
               ▼
          ┌────────┐
          │ report │
          └───┬────┘
              ▼
          ┌───────┐
          │  END  │
        └───────┘
```

运行时还能**高亮当前执行到哪个节点**，这对理解 Agent 的行为、给非技术同事解释流程都很有帮助。

### 3、和可观测性的关系

这些执行记录，本质上是"追踪（Trace）"的一部分。第九篇讲评估和可观测性时，会把它和 Token 消耗、工具调用、模型响应串成完整的链路。

## 十一、实践验证：用状态图编排一条带人工审批的流程

前面讲了节点、边、状态、检查点和中断恢复。这一节用一个真实例子把它们全部跑通：**库存调拨流程**——采集数据 → AI 预测 → 发审批邮件 → **中断等待人工审批** → 审批通过则创建调拨单，拒绝则结束。

### 1、定义状态与合并策略

状态是图的中枢，先声明有哪些 Key、每个 Key 用什么更新策略：

```java
StateGraph graph = new StateGraph("transfer", () ->
        Map.of(
            TransferGraphConstant.KeyName.PRODUCT_ID, new ReplaceStrategy(),          // 覆盖
            TransferGraphConstant.KeyName.SALE_RECORD_DATA, new ReplaceStrategy(),
            TransferGraphConstant.KeyName.INVENTORY_TRANSFER_JSON_STR, new ReplaceStrategy(),
            TransferGraphConstant.KeyName.APPROVAL, new ReplaceStrategy(),
            TransferGraphConstant.KeyName.HUMAN_DECISION, new ReplaceStrategy()
        )
);
```

`ReplaceStrategy` 表示新值覆盖旧值（适合"当前状态"这类字段），`AppendStrategy` 表示追加（适合历史记录）——这正是前面"节点输入输出与状态更新"讲的两种语义。

### 2、注册节点

每个节点实现 `NodeAction`，输入是状态、输出是对状态的更新：

```java
// 采集销售数据
graph.addNode(TransferGraphConstant.NodeName.SALE_RECORD,
        AsyncNodeAction.node_async(new CollectSaleRecordDataNode(saleRecordService, bbInventoryService)));
// 采集库存数据
graph.addNode(TransferGraphConstant.NodeName.INVENTORY_ORDER,
        AsyncNodeAction.node_async(new CollectionInventoryOrderDataNode(inventoryOrderService)));
// AI 预测调拨建议
graph.addNode(TransferGraphConstant.NodeName.PREDICT,
        AsyncNodeAction.node_async(new PredictNode(builder.build())));
// 发送审批邮件
graph.addNode(TransferGraphConstant.NodeName.SEND_EMAIL,
        AsyncNodeAction.node_async(new SendEmailNode(emailSendService)));
// 人工决策
graph.addNode(TransferGraphConstant.NodeName.HUMAN_DECISION,
        AsyncNodeAction.node_async(new HumanDecisionNode()));
// 创建调拨单
graph.addNode(TransferGraphConstant.NodeName.CREATE,
        AsyncNodeAction.node_async(new CreateInventoryTransferNode(transferOrderService)));
```

节点不直接互相调用，而是**通过状态交互**——这就是前面强调的"节点之间用状态解耦"。

### 3、连边：并行 + 条件路由

```java
// 两条采集分支并行执行
graph.addEdge(StateGraph.START, TransferGraphConstant.NodeName.SALE_RECORD);
graph.addEdge(StateGraph.START, TransferGraphConstant.NodeName.INVENTORY_ORDER);
graph.addEdge(TransferGraphConstant.NodeName.SALE_RECORD, TransferGraphConstant.NodeName.PREDICT);
graph.addEdge(TransferGraphConstant.NodeName.INVENTORY_ORDER, TransferGraphConstant.NodeName.PREDICT);

graph.addEdge(TransferGraphConstant.NodeName.PREDICT, TransferGraphConstant.NodeName.EXTRACT);
graph.addEdge(TransferGraphConstant.NodeName.EXTRACT, TransferGraphConstant.NodeName.SEND_EMAIL);
graph.addEdge(TransferGraphConstant.NodeName.SEND_EMAIL, TransferGraphConstant.NodeName.HUMAN_DECISION);

// 条件路由：根据人工决策结果走不同分支
graph.addConditionalEdges(
        TransferGraphConstant.NodeName.HUMAN_DECISION,
        AsyncEdgeAction.edge_async(new HumanDecisionEdge()),
        Map.of(TransferGraphConstant.NodeName.CREATE, TransferGraphConstant.NodeName.CREATE,
               StateGraph.END, StateGraph.END));
graph.addEdge(TransferGraphConstant.NodeName.CREATE, StateGraph.END);
```

`START` 同时连到两个采集节点，就是**并行分支**；`addConditionalEdges` 就是**条件路由**。条件边本身只负责"决定去哪个节点"：

```java
public class HumanDecisionEdge implements EdgeAction {
    @Override
    public String apply(OverAllState state) throws Exception {
        // 直接读状态里的人工决策结果
        return state.value(TransferGraphConstant.KeyName.HUMAN_DECISION, "");
    }
}
```

### 4、检查点与中断

这是前面最核心的部分——**中断等待人工审批**。靠两样东西实现：

```java
// ① 检查点：把图状态持久化到 Redis，支持断点恢复
SaverConfig saverConfig = SaverConfig.builder()
        .register(RedisSaver.builder().redisson(redissonClient).build())
        .build();

// ② 中断点：在人工决策节点前暂停
CompileConfig compileConfig = CompileConfig.builder()
        .interruptBefore(TransferGraphConstant.NodeName.HUMAN_DECISION)
        .saverConfig(saverConfig)
        .build();

CompiledGraph compiledGraph = graph.compile(compileConfig);
```

图跑到 `HUMAN_DECISION` 之前会**自动暂停**，状态存在 Redis 里，服务重启也不丢。

### 5、恢复：人工审批后继续

审批人点邮件里的链接，触发 HTTP 回调，用 `threadId` 找回中断的图继续跑：

```java
@GetMapping("/decision")
public R<Void> decision(@RequestParam Boolean approval,
                        @RequestParam String threadId) throws Exception {
    productSaleService.decision(approval, threadId);   // 用 threadId 恢复
    return R.ok();
}
```

整个流程启动时是异步触发的（Kafka 消费商品销售消息）：

```java
long threadId = IdUtil.getSnowflakeNextId();
RunnableConfig runnableConfig = RunnableConfig.builder().threadId(threadId + "").build();
graph.invoke(Map.of("productId", productId, "threadId", threadId + ""), runnableConfig).get();
```

### 6、运行与观察

编译时会打印 PlantUML，可以直接看到图结构：

```text
transferGraph UML:@startuml
...
@enduml
```

![image-20261011106000001](assets/image-20261011106000001.png)

触发一次销售事件，会收到审批邮件；点"通过"后，调拨单被创建：

![image-20261011106000002](assets/image-20261011106000002.png)

![image-20261011106000003](assets/image-20261011106000003.png)

### 7、这一步验证了什么

- **节点、边、状态三件套**：`addNode` / `addEdge` / `StateGraph` 分别对应，状态用 `KeyStrategy` 控制更新语义。
- **并行分支**：`START` 连两个节点，两条采集链路同时跑——对应"顺序执行、分支与循环"。
- **条件路由**：`addConditionalEdges` + `EdgeAction` 决定走向，不是写死的顺序。
- **检查点 + 中断 + 恢复**：`RedisSaver` + `interruptBefore` 让流程能等几小时甚至几天，服务重启也不丢——这正是状态图相比普通函数调用的最大价值。
- **Human-in-the-Loop**：不可逆操作（创建调拨单）前必须人工确认，对应"人工审批"一节。

> 这里用 Redis 做检查点存储。如果换成内存存储，服务一重启中断状态就没了，审批链接点开也恢复不了——所以检查点**必须持久化**。

## 小结

这一篇把工作流和状态图讲清楚了：

- **Workflow 是人编排，Agent Loop 是模型决定**，成熟系统用"工作流搭骨架、Agent 填血肉"。
- 图的核心是**节点、边、状态、条件路由**。
- 三种基本结构：**顺序、分支、循环**，循环必须有退出条件。
- 节点通过**状态**交互，返回的是"更新"而不是整个状态。
- 状态图相比普通函数，多了**中断恢复、可视化、人工介入、并行、步骤级重试**的能力。
- **检查点 + 中断 + 恢复**是长流程的关键，让流程能等、能重启、能从断点继续。
- **Human-in-the-Loop** 让不可逆操作可控，审批要给全信息、要有超时兜底。
- **节点级重试/超时/错误分支**让流程更健壮，错误也是正常分支。
- **幂等**是重试和恢复的前提，凡改变外部状态的操作都要能安全重复。
- **执行记录和可视化**是排障、审计、优化的基础。

到这里，单个 Agent 的执行已经能组织得很好了。但有些任务，一个 Agent 确实搞不定，需要多个 Agent 分工。下一篇：《多 Agent 协作》。
