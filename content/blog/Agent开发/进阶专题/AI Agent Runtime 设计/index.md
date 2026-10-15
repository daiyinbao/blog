+++
title = "Agent Runtime 设计"
date = 2026-10-11T00:00:00+08:00
weight = 1
tags = ["Agent", "Runtime", "执行器", "状态机", "工具注册表"]
summary = "进阶专题（一）：拆开 Agent 的运行时，讲清执行上下文、执行器、状态机与工具注册表怎么设计。"
+++

这一篇开始，进入进阶专题。

前面十篇讲的是"怎么把 Agent 做出来"，这一组讲"怎么把 Agent 做扎实"。第一个专题，先把 Agent 的**运行时（Runtime）**拆开看。

一个能跑的 Agent 循环，代码可能就几十行。但一个能支撑生产、能并发、能被中断、能恢复的 Agent，中间要有一套完整的运行时。这一篇就把这套运行时拆成四块：**执行上下文、执行器、状态机、工具注册表**。

## 一、为什么需要 Runtime

### 1、循环之外的复杂性

最简单的 Agent 循环长这样：

```text
while 未完成:
    响应 = 模型(上下文)
    if 响应是工具调用:
        结果 = 执行工具(响应)
        上下文 += 结果
    else:
        return 响应
```

这段代码在 Demo 里够用，但一旦要上生产，立刻会遇到一堆问题：

- **这次的执行属于谁？** 哪个用户、哪个会话、哪个任务。
- **模型说要调工具，谁来真正执行？** 怎么找到对应的工具、怎么传参、怎么兜错。
- **跑到一半要停下怎么办？** 用户点了取消、要等人工审批。
- **服务重启了，跑到哪一步了？** 能不能接着跑。

**Runtime 就是把"能跑"和"能生产"之间的这段差距补上。**

### 2、Runtime 的四个部分

```text
┌───────────────────────────────────────────────┐
│                  Agent Runtime                 │
│                                                │
│  ┌────────────┐        ┌──────────────────┐   │
│  │  执行上下文 │◄──────►│    状态机        │   │
│  │ (谁/哪次/   │        │ (跑到哪/下一步)   │   │
│  │  什么权限)  │        └──────────────────┘   │
│  └─────┬──────┘                                │
│        │                                       │
│  ┌─────▼──────┐        ┌──────────────────┐   │
│  │   执行器    │───────►│   工具注册表      │   │
│  │ (调度/循环) │        │ (有哪些工具)      │   │
│  └────────────┘        └──────────────────┘   │
└───────────────────────────────────────────────┘
```

四块的分工：

- **执行上下文**：这次执行的身份和权限，贯穿始终。
- **执行器**：驱动整个循环，调度模型调用和工具执行。
- **状态机**：记录执行到哪一步、下一步该做什么。
- **工具注册表**：管理所有可用的工具，负责查找和分发。

## 二、执行上下文

### 1、上下文里放什么

执行上下文是**这次执行的身份凭证**，所有环节都能读到它。

```java
public class ExecutionContext {

    /** 当前计划的唯一 ID */
    private String currentPlanId;

    /** 根计划 ID（子任务用） */
    private String rootPlanId;

    /** 父计划 ID（子任务用） */
    private String parentPlanId;

    /** 工具调用 ID */
    private String toolCallId;

    /** 执行计划实体 */
    private PlanInterface plan;

    /** 对话 ID */
    private String conversationId;

    /** 计划在层级中的深度（0 是根） */
    private int planDepth = 0;

    /** 工具执行时的上下文信息 */
    private Map<String, String> toolsContext = new HashMap<>();

    /** 递归调用链，防止子任务无限套娃 */
    private List<String> recursiveCallChain = new ArrayList<>();
}
```

注意几个设计细节：

- **`currentPlanId` / `rootPlanId` / `parentPlanId` 三个 ID**：因为 Agent 任务可能是**嵌套**的——一个计划里派生子计划，子计划里再派生孙子计划。三个 ID 分别表示"当前是谁""根是谁""爹是谁"。
- **`planDepth`**：层级深度。用来限制嵌套层数，防止无限递归。
- **`recursiveCallChain`**：调用链，用来**检测循环调用**。
- **`toolsContext`**：工具执行时的临时上下文，跟着这次执行走。

### 2、为什么上下文要单独抽出来

如果不抽上下文，这些信息就只能靠**层层传参**：

```java
// ❌ 每个方法都要传一堆参数
void think(String planId, String rootPlanId, String conversationId, ...) {}
void act(String planId, String rootPlanId, String toolCallId, ...) {}
void executeTool(String planId, String rootPlanId, String toolCallId, ...) {}
```

抽成上下文后：

```java
// ✅ 方法签名干净，需要时从上下文取
void think() {
    String planId = context.getCurrentPlanId();
}
```

**更重要的是安全**：用户身份、租户、权限这类信息必须来自上下文（认证信息），不能靠参数传（参数可能被模型或用户影响）。这一点在前面的《Agent 评估、可观测性与安全》里强调过。

### 3、上下文的传递

单线程里用 `ThreadLocal` 就够，但 Agent 大量用异步（线程池、`CompletableFuture`），**`ThreadLocal` 在异步线程里会丢**。所以工程上要么用可传递的 `ThreadLocal`，要么把上下文**显式挂到执行的任务上**。

一个常见做法是：**把上下文作为执行器的成员变量**，而不是全局静态的。这样每个执行器实例有自己的上下文，天然隔离，也没有线程安全问题。

## 三、执行器

### 1、执行器的职责

执行器是 Runtime 的"发动机"，负责：

- 驱动主循环（思考 → 行动 → 观察）。
- 调用模型。
- 解析模型的工具调用请求。
- 从工具注册表找到工具并执行。
- 把结果回灌给模型。
- 控制循环的退出（完成、超步数、被中断）。

一个抽象的执行器基类，通常长这样：

```java
public abstract class AbstractPlanExecutor implements PlanExecutorInterface {

    /** 执行记录器：把每一步记下来 */
    protected final PlanExecutionRecorder recorder;

    /** 可用的 Agent 列表 */
    protected final List<DynamicAgentEntity> agents;

    /** 执行器线程池 */
    protected final LevelBasedExecutorPool levelBasedExecutorPool;

    /** 中断检查辅助类 */
    protected AgentInterruptionHelper agentInterruptionHelper;

    /** 记录执行状态的 Key */
    public static final String PLAN_STATUS_KEY = "planStatus";
    public static final String CURRENT_STEP_INDEX_KEY = "currentStepIndex";
    public static final String STEP_TEXT_KEY = "stepText";
    public static final String RECURSIVE_CALL_CHAIN_KEY = "recursiveCallChain";

    /** 生成唯一的步骤 ID，用于追踪 */
    protected String generateStepId() {
        return planIdDispatcher.generateStepId();
    }
}
```

### 2、执行器的三层结构

生产级的 Runtime，执行器往往不止一层：

```text
┌────────────────────────────────────────┐
│  PlanExecutor（计划级）                  │
│  负责整个计划的调度、步骤推进             │
└────────────────┬───────────────────────┘
                 │
┌────────────────▼───────────────────────┐
│  AgentExecutor（Agent 级）              │
│  负责单个 Agent 的 ReAct 循环            │
└────────────────┬───────────────────────┘
                 │
┌────────────────▼───────────────────────┐
│  ToolExecutor（工具级）                 │
│  负责单个工具的执行、超时、校验           │
└────────────────────────────────────────┘
```

三层各自的关注点不同：**计划级管流程，Agent 级管循环，工具级管执行。**

### 3、按层级隔离线程池

一个容易被忽略的设计：**执行器的线程池按"层级"隔离**。

```java
public class LevelBasedExecutorPool implements ExecutorPoolProvider {

    private static final int MAX_DEPTH_LEVEL = 10;
    private static final int DEFAULT_QUEUE_CAPACITY = 100;

    /** 每个深度层级一个线程池 */
    private final Map<Integer, ExecutorService> levelPools = new ConcurrentHashMap<>();

    private final AtomicInteger poolCounter = new AtomicInteger(0);

    private volatile int currentPoolSize = -1;
}
```

为什么要按层级分池？考虑这个场景：

```text
根计划（深度 0）──► 子计划 A（深度 1）──► 子子计划 A1（深度 2）
                                     └──► 子子计划 A2（深度 2）
                └──► 子计划 B（深度 1）
```

如果所有任务共用一个线程池，**深度 0 的任务可能把池子占满**，导致深度 1、2 的子任务全都在排队，出现"父任务等子任务、子任务没线程"的**死锁**。

按层级分池后：

- 深度 0 用池 0，深度 1 用池 1……**父子不抢同一个池**。
- `MAX_DEPTH_LEVEL = 10` 限制最大嵌套深度，超过就拒绝。
- `currentPoolSize` 会动态调整，负载高时扩、低时缩。

**这是 Runtime 设计里很关键的一个细节：并发不只是"够不够"，还要防"互相饿死"。**

## 四、状态机

### 4.1、为什么需要状态机

Agent 的执行不是一条直线，而是有状态的：

```text
NOT_STARTED → RUNNING → （可能）WAITING → RUNNING → COMPLETED
                │                          │
                └────────► FAILED ◄────────┘
```

每一步都要记录"当前状态"，才能支持：

- **暂停/恢复**：用户暂停后，从当前状态接着跑。
- **中断**：收到取消信号，停下来。
- **等输入**：等用户填表、等人工审批。

### 2、任务状态

生产级的 Runtime 会定义一个明确的"用户期望状态"：

```java
public enum DesiredTaskState {
    START,    // 用户想开始任务
    STOP,     // 用户想停止任务
    PAUSE,    // 用户想暂停
    RESUME,   // 用户想恢复
    CANCEL,   // 用户想取消
    WAIT      // 用户想等待输入
}
```

注意这是**用户"期望"的状态**，不是任务"实际"的状态。两者分开的好处是：用户的意图（我想要它停）和执行的现状（它跑到哪了）解耦，执行器在合适的检查点**读用户的期望，再决定要不要停**。

### 3、状态怎么流转

用户点"暂停"时，Runtime 不会粗暴地杀线程，而是**把期望状态写下来**：

```text
用户点暂停 → 写入 desiredTaskState = PAUSE
                        │
                        ▼
执行器在检查点读到 PAUSE → 主动停下 → 保存状态 → 返回
```

执行器在循环里埋检查点：

```java
public class AgentInterruptionHelper {

    /** 检查是否该中断；该中断就抛异常，让执行停下来 */
    public void checkInterruptionAndThrow(String rootPlanId)
            throws TaskInterruptedException {
        interruptionCheckerService.checkAndThrowIfInterrupted(rootPlanId);
    }

    /** 检查是否该中断，不抛异常，返回布尔 */
    public boolean checkInterruptionAndContinue(String rootPlanId) {
        try {
            interruptionCheckerService.checkAndThrowIfInterrupted(rootPlanId);
            return true;   // 继续执行
        } catch (TaskInterruptedException e) {
            return false;  // 停下
        }
    }

    /** 只查询状态，不做处理 */
    public boolean isInterruptionRequested(String rootPlanId) {
        return interruptionCheckerService.shouldInterruptExecution(rootPlanId);
    }
}
```

**为什么用"抛异常"而不是"直接杀线程"？** 因为线程被强杀时，资源没释放、状态没保存、日志没写完。用异常让执行流程**自己走到一个安全点再退出**，才能保证状态一致。

### 4、等待输入也是一种状态

"等用户填表"同样是一种状态：

```java
public class UserInputWaitState implements Serializable {
    private String planId;                       // 哪个计划在等
    private String title;                        // 等什么
    private boolean waiting;                     // 是否在等待
    private String formDescription;              // 表单说明
    private List<Map<String, String>> formInputs; // 要填的字段
}
```

这样执行器可以在"需要用户输入"时挂起，等用户提交后**从挂起点恢复**。

## 五、工具注册表

### 1、注册表要解决什么

Agent 可能有几十上百个工具，Runtime 需要：

- **登记**：有哪些工具、每个工具的定义是什么。
- **查找**：模型说要调 `get_weather`，得能找到它。
- **分发**：把参数传进去，拿到结果。
- **隔离**：不同计划、不同租户的工具上下文不能串。

### 2、工具的统一抽象

所有工具继承同一个基类，Runtime 才能统一处理：

```java
public abstract class AbstractBaseTool<I> implements ToolCallBiFunctionDef<I> {

    /** 当前计划 ID */
    protected String currentPlanId;

    /** 根计划 ID */
    protected String rootPlanId;

    /** 工具是否可被前端选择 */
    public abstract boolean isSelectable();

    /** 统一入口：传入参数，返回结果 */
    @Override
    public ToolExecuteResult apply(I input, ToolContext toolContext) {
        return run(input);
    }

    public void setCurrentPlanId(String planId) {
        this.currentPlanId = planId;
    }

    public void setRootPlanId(String rootPlanId) {
        this.rootPlanId = rootPlanId;
    }
}
```

关键点：

- **统一的 `apply` 入口**：不管什么工具，Runtime 都用同一个方法调用。
- **`currentPlanId` / `rootPlanId` 由 Runtime 注入**：工具不用自己操心"我是谁在调"，从基类就能拿到——**上下文自动传递，而不是每个工具方法都加参数。**

### 3、工具要能被模型"看懂"

注册表里每个工具都要向模型描述自己：

```java
public interface ToolCallBiFunctionDef<I> {
    String getName();            // 工具名，模型用它来调用
    String getDescription();     // 描述，模型靠它判断何时用
    String getParameters();      // 参数的 JSON Schema
    Class<I> getInputType();     // 入参类型，用于反序列化

    ToolExecuteResult run(I input);
}
```

这正是前面《Tool Calling 与工具系统》讲过的"工具定义四要素"，这里是它在 Runtime 层的接口形态。

### 4、注册与分组

工具多起来后，注册表还要支持**分组**，按场景/权限给不同的 Agent：

```java
public interface ToolCallbackProvider {
    List<ToolCallback> getToolCallbacks();
}
```

```text
注册表
├── 文件工具组    （读文件、写文件）
├── 数据库工具组  （查元数据、执行只读 SQL）
├── 浏览器工具组  （导航、点击、截图）
├── 代码工具组    （执行 Python、执行 Shell）
└── 内部工具组    （think、terminate）
```

**按组分配工具，等于按组划分权限**——Agent 没有某组工具，就不可能做那类操作。这和《Tool Calling 与工具系统》里"按场景分组"是同一个道理，只是在 Runtime 层做。

### 5、内部工具：控制循环

注册表里还有一类**不暴露给模型**的内部工具，专门用来控制循环。

比如"只有思考、没有行动"时的兜底：

```java
public class ThinkTool extends AbstractBaseTool<Map<String, Object>> {

    public static final String name = "__think_internal__";

    public String getDescription() {
        return "";   // 不暴露给 LLM
    }

    @Override
    public ToolExecuteResult run(Map<String, Object> input) {
        String message = String.valueOf(input.get("message"));
        // 逼模型至少调用一个真正的工具，不能只"想"不"做"
        return new ToolExecuteResult(message
                + "\n\n⚠️ IMPORTANT: You must call at least one tool to proceed.");
    }
}
```

再比如"终止"工具，让模型能主动结束：

```java
public class TerminateTool extends AbstractBaseTool<Map<String, Object>>
        implements TerminableTool {

    public static final String name = "terminate";
    // 模型的输出必须符合预定义的 JSON 结构，
    // 这样返回结果才能被程序直接消费
}
```

**这两个工具是 Runtime 设计里很典型的技巧**：用"工具"的形式，实现"控制循环"的逻辑。因为对模型来说，"结束"和"调用工具"是同一种动作，不如就让它们统一。

## 六、实践验证：执行上下文与工具注册表

这一节看一个真实的 Agent Runtime——**Lynxe（原 JManus）**——它是怎么组织这四块的。

### 1、工程结构

```text
lynxe/
├── runtime/       执行器、上下文、状态机
│   ├── entity/vo/    ExecutionContext、ExecutionStep
│   ├── executor/     AbstractPlanExecutor、线程池
│   └── service/      AgentInterruptionHelper、TaskInterruptionCheckerService
├── agent/         Agent 实现（ReActAgent、DynamicAgent）
├── tool/          工具注册表与所有工具
│   ├── AbstractBaseTool
│   ├── bash/、database/、browser/、code/
│   └── ThinkTool、TerminateTool
├── planning/      规划
└── llm/           模型服务
```

对照前面讲的四块：`runtime/` 是执行器和状态机，`agent/` 是循环，`tool/` 是注册表，`ExecutionContext` 是上下文。

### 2、执行器的线程池

```java
/** 按层级隔离的线程池：每个深度层级一个池，避免父子任务互相饿死 */
public class LevelBasedExecutorPool implements ExecutorPoolProvider {
    private static final int MAX_DEPTH_LEVEL = 10;
    private final Map<Integer, ExecutorService> levelPools = new ConcurrentHashMap<>();
}
```

### 3、中断检查

```java
@Component
public class AgentInterruptionHelper {

    @Autowired
    private TaskInterruptionCheckerService interruptionCheckerService;

    public boolean checkInterruptionAndContinue(String rootPlanId) {
        try {
            interruptionCheckerService.checkAndThrowIfInterrupted(rootPlanId);
            return true;
        } catch (TaskInterruptedException e) {
            logger.info("Agent execution interrupted for planId: {}", rootPlanId);
            return false;
        }
    }
}
```

执行器在循环的每个关键点调它，实现"用户随时能停"。

![image-20261011111000001](assets/image-20261011111000001.png)

### 4、工具的注册与上下文注入

```java
public abstract class AbstractBaseTool<I> implements ToolCallBiFunctionDef<I> {
    protected String currentPlanId;
    protected String rootPlanId;

    @Override
    public ToolExecuteResult apply(I input, ToolContext toolContext) {
        return run(input);
    }
}
```

Runtime 在调用工具前，把 `currentPlanId` / `rootPlanId` 注入进去，工具执行时就能拿到自己的上下文。

![image-20261011111000002](assets/image-20261011111000002.png)

### 5、这一步验证了什么

- **上下文是 Runtime 的中枢**：`ExecutionContext` 把身份、层级、调用链都带上，避免层层传参，也保证了安全信息不被篡改。
- **执行器要分层**：计划级 / Agent 级 / 工具级各管一段，责任清晰。
- **线程池按层级隔离**：`LevelBasedExecutorPool` 证明了并发设计不只要"够用"，还要防"父子互锁"。
- **状态机区分"期望"与"实际"**：`DesiredTaskState` 是用户意图，执行状态是现实，两者解耦才能优雅地暂停。
- **中断用异常而非杀线程**：`checkInterruptionAndThrow` 让执行走到安全点再退出。
- **工具注册表统一抽象 + 上下文注入**：`apply(input, toolContext)` 是统一入口，`currentPlanId` 由 Runtime 注入。

> 这套 Runtime 设计看着比"一个 while 循环"复杂得多，但正是这些机制——上下文、按层隔离、状态机、中断检查——让 Agent 能跑长任务、能并发、能被用户控制。少了任何一个，到生产环境都会出问题。

## 小结

这一篇把 Agent 运行时拆成了四块：

- **执行上下文**：身份、权限、层级、调用链，贯穿始终，安全信息只能来自这里。
- **执行器**：驱动循环，分计划级 / Agent 级 / 工具级三层，**线程池按层级隔离**防止互相饿死。
- **状态机**：区分"用户期望状态"和"实际执行状态"，用**异常而非杀线程**来实现优雅中断。
- **工具注册表**：统一抽象 `apply(input, toolContext)`，按组分配工具即按组划分权限，还能用"内部工具"控制循环。

下一篇：《Agent 规划与推理》——讲 Agent 怎么把复杂目标拆成计划，用 ReAct、Plan-and-Execute 这些模式做推理，以及执行中发现不对怎么重规划。
