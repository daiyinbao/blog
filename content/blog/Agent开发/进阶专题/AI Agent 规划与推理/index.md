+++
title = "Agent 规划与推理"
date = 2026-10-11T00:00:00+08:00
weight = 2
tags = ["Agent", "ReAct", "Plan-and-Execute", "任务分解", "重规划"]
summary = "进阶专题（二）：讲清 Agent 怎么规划——ReAct、Plan-and-Execute、任务分解与重规划，以及执行中跑偏了怎么办。"
+++

上一篇讲了 Runtime 怎么驱动 Agent，其中反复出现一个词：**循环**。但循环里到底在发生什么？Agent 是"走一步看一步"，还是"先想清楚再做"？这一步想错了怎么回头？

这就是规划与推理要解决的问题。这一篇讲三种东西：**推理模式（ReAct）、规划模式（Plan-and-Execute）、以及执行中的动态调整（重规划）**。

## 一、ReAct：边想边做

### 1、回顾

前面第一篇文章讲过 ReAct，这里从"运行时"的角度再看一遍。

ReAct 的每一轮是"思考 → 行动 → 观察"：

```text
Thought:  我需要先查一下这个订单
Action:   queryOrder
Action Input: {"orderId": "20261011001"}
Observation: {"status": "运输中"}
Thought:  信息够了
Final Answer: 你的订单已到达杭州转运中心
```

关键点：**"要不要行动"是每一步现算的**。模型看到当前的全部上下文，判断"下一步该调工具还是给答案"。

### 2、为什么"边想边做"有优势

- **适应性强**：每一步都基于最新的观察，遇到意外能立刻调整。
- **不需要预知全貌**：任务一开始不清楚要几步，ReAct 也能往下走。
- **实现简单**：就是一个循环，不需要额外的规划模块。

### 3、代价

- **容易迷失**：没有全局目标，可能绕来绕去，或者做了一半忘了要干嘛。
- **步数不可控**：可能转很多圈。
- **无法提前评估**：计划是"涌现"出来的，事前看不见，人也审不了。

## 二、Plan-and-Execute：先规划再执行

### 1、核心思想

Plan-and-Execute 把"想"和"做"拆成两个阶段：

```text
【规划阶段】
目标 ──► Planner（规划器）──► 计划：[步骤1, 步骤2, 步骤3, ...]

【执行阶段】
计划 ──► Executor（执行器）──► 逐步执行 ──► 汇总结果
```

- **Planner**：把大目标拆成有序的、原子化的步骤。
- **Executor**：拿着步骤清单，一步一步执行。

### 2、为什么要先规划

对比 ReAct，先规划带来几个好处：

- **全局视角**：先想清楚整体路线，避免"低头拉车不抬头看路"。
- **可审查**：计划是显式的，执行前就能给人看，人可以在**动手之前**纠正方向。
- **可并行**：步骤间的依赖关系明确了，没有依赖的可以同时跑。
- **可恢复**：计划是持久化对象，某一步失败可以只重试那一步。
- **成本可控**：规划的调用次数是固定的，不像 ReAct 那样不确定。

### 3、计划的表示

计划本质上是一个**结构化的任务列表**：

```java
public class ExecutionStep {
    /** 步骤序号 */
    private int stepIndex;

    /** 这一步要做什么 */
    private String stepRequirement;

    /** 由哪个 Agent 执行 */
    private String agentName;

    /** 这一步需要哪些工具 */
    private List<String> selectedToolKeys;

    /** 用哪个模型 */
    private String modelName;

    /** 执行状态 */
    private AgentState status;
}
```

注意这几个字段的分工：

- `stepRequirement` 说"做什么"，是**自然语言**描述的。
- `agentName` 说"谁来做"。
- `selectedToolKeys` 说"用什么工具"——**这一步在规划阶段就把工具选好了**。
- `modelName` 说"用哪个模型"——复杂的步骤用强模型，简单的用小模型。

**关键点：计划和执行是解耦的。** 计划只是一个数据结构，可以被保存、展示、修改、重新执行。这就是为什么它能支持"人工审查计划"和"断点恢复"。

## 三、任务分解

规划的核心动作是**任务分解**：把一个模糊的大目标，拆成一组具体的、可执行的步骤。

### 1、分解的原则

- **原子性**：每个步骤只做一件事，做完能明确判断"成了没成"。
- **可验证**：每步有明确的产出或成功标准。
- **依赖清晰**：步骤之间的先后关系明确。
- **粒度适中**：太粗（一步干不完）、太细（步骤爆炸）都不好。

举个例子：

```text
目标：帮我分析这个季度的销售情况并生成报告

分解：
1. 从数据库取出本季度的销售记录
2. 按商品维度汇总销售额
3. 找出销售额环比下降最多的商品
4. 分析下降原因（结合库存和促销数据）
5. 生成分析报告
6. 把报告发送到指定邮箱
```

### 2、分解的两种方式

**（1）模型分解**

直接用大模型把目标拆开：

```java
String prompt = """
        把下面的任务拆解成有序的执行步骤，每步要具体、可执行。
        输出 JSON 数组，每个元素包含 stepRequirement 和 selectedToolKeys。

        任务：%s

        可用工具：%s
        """.formatted(goal, availableTools);
```

优点：灵活，能处理各种目标。
缺点：可能拆得不合理，依赖关系可能乱。

**（2）模板分解**

预先定义好计划模板，用的时候套用：

```text
模板：竞品分析
  1. 收集竞品资料 → [搜集工具]
  2. 整理功能对比 → [分析工具]
  3. 输出分析报告 → [写作工具]
```

优点：稳定、可复用、质量可控。
缺点：不够灵活，只能处理预定义的场景。

**实践中常常是"模板优先、模型兜底"**：常见任务走模板保证质量，模板覆盖不到的地方用模型动态生成。

### 3、子任务与递归

复杂任务分解后，一个步骤本身可能还是个复杂任务，需要**再分解**。这就是递归：

```text
根计划
├── 步骤 1
├── 步骤 2（复杂）──► 子计划
│                     ├── 子步骤 2.1
│                     └── 子步骤 2.2
└── 步骤 3
```

这正好解释了上一篇 Runtime 里为什么要有 `currentPlanId` / `parentPlanId` / `planDepth` / `recursiveCallChain`：**因为计划是可以嵌套的树**。

防递归失控靠两个东西：

- **`planDepth` 限制深度**：超过最大层数就拒绝分解。
- **`recursiveCallChain` 检测循环**：同一类子任务重复出现就打断。

## 四、重规划

### 1、为什么要重规划

计划赶不上变化。执行中可能发现：

- **信息不足**：某一步需要的资料没有，得先补收集。
- **计划有误**：某步的方案根本行不通。
- **目标变了**：用户中途改了需求。
- **执行失败**：某步反复失败，得换方案。

这时候不能硬着头皮往下走，要**重新规划**。

### 2、重规划的层次

重规划有两种粒度：

```text
粗粒度：推翻整个计划，重新规划
  └─ 适合：目标变了、整体方案错了

细粒度：只调整后面的步骤
  └─ 适合：某一步失败、局部信息不足
```

**优先用细粒度**：能局部修就别整体推倒，因为整体重规划会丢掉已经完成的成果，代价大。

### 3、重规划要有护栏

重规划本身也可能失控——不停地改计划，永远执行不完。所以要有护栏：

```java
/** 重规划次数上限 */
private static final int MAX_REPLAN = 3;

public boolean shouldReplan(ExecutionContext ctx) {
    if (ctx.getReplanCount() >= MAX_REPLAN) {
        logger.warn("重规划次数超过上限 {}，停止调整", MAX_REPLAN);
        return false;   // 不再重规划，返回当前结果
    }
    return true;
}
```

**迭代次数、总步数、总时长、总成本，都要设上限。** 这是所有 Agent 循环的铁律，前面几篇反复出现过。

## 五、推理：让模型"想"得更清楚

规划之后，每一步的推理质量也很关键。几种常用的推理增强手段。

### 1、思维链（CoT）

让模型把推理过程写出来，而不是直接给答案：

```text
❌ 直接回答：答案是 42

✅ 思维链：
   先看已知条件……
   根据规则 A，可以推导出……
   再结合规则 B，得到……
   所以答案是 42
```

**写草稿比直接抢答准**，这是被反复验证的结论。

### 2、显式思考工具

ReAct 里"思考"和"行动"是混在一起的。有的实现会把"思考"单独做成一个工具：

```java
public class ThinkTool extends AbstractBaseTool<Map<String, Object>> {

    public static final String name = "__think_internal__";

    @Override
    public ToolExecuteResult run(Map<String, Object> input) {
        String message = String.valueOf(input.get("message"));
        // 记录思考，并要求模型下一步必须真正调用工具
        return new ToolExecuteResult(message
                + "\n\n⚠️ IMPORTANT: You must call at least one tool to proceed.");
    }
}
```

这样做有两个好处：

- **思考被显式记录**：可以作为执行轨迹的一部分，便于观察和调试。
- **防止"只想不做"**：思考工具返回时会提示"你必须调用一个真正的工具"，把模型从"空想"拉回"行动"。

### 3、把"想"当成一种工具调用

这个设计很巧妙：对模型来说，"思考"和"调用工具"是同一种输出形式（都是工具调用），**Runtime 不用为"思考"单独写一套解析逻辑**。

这体现了 Runtime 设计的一个通用思路：**统一抽象，减少特例。**

## 六、实践验证：ReAct 循环与规划工具

这一节看 Lynxe 里规划和推理是怎么落地的。

### 1、ReAct 的抽象

ReAct 的核心是"思考"和"行动"交替，代码上把它抽象成两个方法：

```java
public abstract class ReActAgent extends BaseAgent {

    /**
     * 执行思考过程，判断是否需要行动
     *
     * 子类实现要求：
     * 1. 分析当前状态和上下文
     * 2. 做逻辑推理，决定下一步动作
     * 3. 返回"是否需要执行行动"
     *
     * 返回 true 表示需要调用工具
     * 返回 false 表示当前步骤已完成
     */
    protected abstract boolean think();
}
```

**把"要不要行动"做成 `think()` 的返回值**，主循环就变成了：

```text
while (未完成) {
    if (think()) {
        act();      // 执行工具
    } else {
        break;      // 这一步完成
    }
}
```

### 2、步数护栏

主循环必须有上限：

```java
private int maxSteps;

public void setMaxSteps(int maxSteps) {
    if (maxSteps > 0) {
        this.maxSteps = maxSteps;
    } else {
        log.warn("Invalid maxSteps value: {}, ignoring", maxSteps);
    }
}
```

在循环里检查：

```java
if (stepNum > maxSteps) {
    log.info("Agent reached max rounds ({}), generating final summary and terminating", maxSteps);
    // 超过步数，生成一个总结然后收尾，而不是直接抛异常
}
```

注意这里的设计：**超过步数不是报错，而是"生成总结后收尾"**。因为 Agent 可能已经做了很多有用的事，直接失败会丢掉成果。

`maxSteps` 从配置里读，默认 30：

```java
this.maxSteps = lynxeProperties.getMaxSteps();
```

**做成配置项，就能按场景调整**：简单任务给 10 步，复杂任务给 50 步。

### 3、计划与步骤的数据结构

```java
public class ExecutionStep {
    private int stepIndex;                  // 步骤序号
    private String stepRequirement;         // 这一步要做什么
    private String agentName;               // 由哪个 Agent 执行
    private List<String> selectedToolKeys;  // 用哪些工具
    private String modelName;               // 用哪个模型
    private AgentState status;              // 执行状态
}
```

步骤的展示形式也很直观：

```java
public String getStepInStr() {
    String state = (status != null) ? status.toString() : AgentState.NOT_STARTED.toString();
    return stepIndex + ". [" + state + "] " + stepRequirement;
}
```

输出就是：`1. [RUNNING] 从数据库取出本季度的销售记录`。

### 4、把规划做成"工具"

规划本身也可以是 Agent 的一个工具（`TodoWriteTool`），模型可以"写待办"来规划任务：

```text
模型：我要先规划一下
  → 调用 todo_write，写入：
     [ ] 查销售数据
     [ ] 汇总分析
     [ ] 生成报告
  → 然后逐步执行
```

这样做的好处是：**规划和执行走同一套机制**（都是工具调用），Runtime 不用为"规划"单独写一套。

![image-20261011112000001](assets/image-20261011112000001.png)

![image-20261011112000002](assets/image-20261011112000002.png)

### 5、这一步验证了什么

- **ReAct 就是"思考决定要不要行动"**：`think()` 返回布尔，主循环按返回值走。
- **步数必须有上限**：`maxSteps` 默认 30，从配置读；超限不是报错，而是"总结后收尾"。
- **计划要结构化**：`ExecutionStep` 把"做什么/谁做/用什么工具/用哪个模型"都存下来，才能被审查和恢复。
- **规划和执行统一为工具调用**：`ThinkTool`、`TodoWriteTool` 都是工具，减少 Runtime 的特例。
- **子任务靠 `planDepth` 和 `recursiveCallChain` 控制**：防止递归失控。

> 规划不是"一次性把计划想明白"就完事。真实任务里，计划会随着执行不断调整——重规划、局部重试、动态加步骤，都要有护栏。下一篇讲代码执行，会看到一个更具体的"计划 + 执行 + 校验"闭环。

## 小结

这一篇把 Agent 的规划与推理讲清楚了：

- **ReAct 是边想边做**：适应性强，但容易迷失、步数不可控。
- **Plan-and-Execute 是先规划再执行**：全局视角、可审查、可并行、可恢复。
- **任务分解**要原子、可验证、依赖清晰、粒度适中；模板分解保稳定，模型分解保灵活。
- **计划是可嵌套的树**，靠 `planDepth` 限制深度、`recursiveCallChain` 检测循环。
- **重规划优先局部**，且必须有次数上限。
- **推理增强**靠思维链和显式思考工具；把"想"做成工具调用，能统一 Runtime 的处理逻辑。
- **所有循环都要护栏**：步数、时长、成本、迭代次数。

下一篇：《Agent 与代码执行》——Agent 要真正"动手"，就得能执行代码。这中间的沙箱、超时、资源限制和输出采集，是安全和工程的重头戏。
