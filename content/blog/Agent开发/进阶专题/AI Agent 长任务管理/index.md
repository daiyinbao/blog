+++
title = "Agent 长任务管理"
date = 2026-10-11T00:00:00+08:00
weight = 5
tags = ["Agent", "长任务", "检查点", "暂停恢复", "补偿", "幂等"]
summary = "进阶专题（五）：讲清长任务的检查点保存、暂停恢复、审批中断、补偿事务与幂等控制，让 Agent 能跑几小时也不丢状态。"
+++

前面几篇讲的 Agent 任务，大多是"几十秒出结果"。但真实业务里，长任务很常见：**跑几分钟的数据分析、等几小时的人工审批、跨天的批量处理**。

长任务的核心矛盾是：**任务越长，中间出岔子的概率越大。** 网络会断、服务会重启、用户会取消、审批要等。如果任务是"一口气跑完、不能中断"，那基本等于不能上线。

这一篇讲的就是：**怎么把长任务做成"随时可以停、停了能接着跑"的。**

## 一、长任务为什么难

### 1、短任务 vs 长任务

```text
短任务（10 秒）：
  用户 → 执行 → 返回
  中间出错的概率 ≈ 0，出错了重来一次就行

长任务（30 分钟）：
  用户 → 执行 30 分钟 → 返回
  中间：服务可能重启、网络可能断、用户可能关掉页面……
```

**问题不在于"长"，而在于"中间状态"。** 短任务没有中间状态，长任务有一堆。

### 2、长任务必须回答的问题

- 跑到第 5 步时服务重启了，能接着跑吗？
- 用户点了暂停，怎么停？停了之后怎么继续？
- 要等人工审批，等 8 小时，怎么等？
- 第 3 步调用外部服务超时了，重试会不会重复扣款？
- 上下游都成功了，但通知失败了，要不要回滚？

这些问题，短任务都可以不管，长任务一个都躲不掉。

## 二、检查点：把进度存下来

### 1、核心思想

**每执行完一步，就把"当前状态"存下来。** 这样任何一步出问题，都能从上一个检查点恢复，不用从头再来。

```text
执行节点 A ──► 保存检查点 ──► 执行节点 B ──► 保存检查点 ──► 执行节点 C
                  │                              │
                  └── 崩溃后从这里恢复 ───────────┘
```

### 2、检查点里存什么

```java
public class Checkpoint {
    /** 任务 ID */
    private String taskId;

    /** 执行到哪一步了 */
    private int currentStepIndex;

    /** 已完成哪些步骤 */
    private List<String> completedSteps;

    /** 全局状态（槽位、中间结果） */
    private Map<String, Object> state;

    /** 任务状态 */
    private String status;        // RUNNING / WAITING / DONE / FAILED

    /** 保存时间 */
    private Instant updatedAt;
}
```

**关键是 `state`**：要能把"任务进行到哪了"完整还原出来。

### 3、存到哪里

```text
Redis   →  正在执行的任务（读写快，可设 TTL）
MySQL   →  需要长期保存、要审计的任务
```

工程上常用"**Redis 存热数据 + MySQL 归档**"的组合：

- 进行中的任务状态放 Redis，读写快，还能设过期时间自动清理。
- 任务结束后归档到 MySQL，长期保存、可查、可审计。

### 4、检查点的存储要有事务性

存检查点这个动作本身，也可能失败（Redis 挂了、网络抖了）。所以要注意：

- **先执行、后存检查点**：如果顺序反了（先存后执行），崩在中间会"以为做了、其实没做"。
- **重试时要幂等**：因为"执行成功但存检查点失败"会导致重试时重复执行。

这就引出了后面要讲的**幂等**。

## 三、暂停与恢复

### 1、暂停：不要杀线程

用户点"暂停"时，最粗暴的做法是 `Thread.interrupt()` 或者直接杀线程。但这会带来一堆问题：

- 资源没释放（连接、文件句柄）。
- 状态没保存（不知道停在哪了）。
- 可能停在"执行到一半"的中间态。

**正确做法是"协作式暂停"**：把用户的期望写成状态，执行器在检查点读到后，主动走到一个安全点再停。

```text
用户点暂停
   │
   ▼
写入 desiredTaskState = PAUSE
   │
   ▼
执行器在下一个检查点读到 PAUSE
   │
   ▼
保存当前检查点 → 释放资源 → 优雅退出
```

### 2、用户意图 vs 执行现实

这里有个重要的设计：**区分"用户想要什么"和"实际在做什么"**。

```java
public enum DesiredTaskState {
    START,    // 用户想开始
    STOP,     // 用户想停止
    PAUSE,    // 用户想暂停
    RESUME,   // 用户想恢复
    CANCEL,   // 用户想取消
    WAIT      // 用户想等待输入
}
```

用户点"暂停"，只是写入一个 `PAUSE`。**什么时候真正停下，由执行器决定**——它会在"步骤之间"这个安全点停，而不是在"调接口调到一半"时停。

### 3、恢复：从检查点接着跑

```text
恢复任务
   │
   ▼
从存储加载检查点
   │
   ▼
还原状态（currentStepIndex、completedSteps、state）
   │
   ▼
从 currentStepIndex + 1 继续执行
```

```java
public void resume(String taskId) {
    Checkpoint cp = checkpointStore.load(taskId);
    if (cp == null) {
        throw new TaskNotFoundException(taskId);
    }

    switch (cp.getStatus()) {
        case "WAITING":
            // 在等外部输入，不主动推进
            break;
        case "RUNNING":
            // 从断点继续
            continueFrom(cp);
            break;
        case "DONE":
            // 已经完成，什么都不做
            break;
    }
}
```

### 4、恢复的前提

恢复能work，依赖三个前提，缺一不可：

- **状态可持久化**：检查点真的存下来了。
- **步骤幂等**：恢复时重跑某一步，不会产生副作用。
- **进度可定位**：能准确知道"从哪继续"。

**"恢复"听起来简单，实际上是对整个系统设计的要求。**

## 四、审批中断

长任务里最常见的一种"等"，是**等人工审批**。

### 1、为什么需要审批

不是所有事都能让 Agent 自己决定。这几类必须人工确认：

- **不可逆操作**：退款、删除、发消息。
- **金额/风险超阈值**。
- **模型不确定性高**：反复失败、置信度低。
- **合规要求**。

### 2、中断机制

在审批节点**之前**设置中断点，执行到那里自动停下：

```java
CompileConfig compileConfig = CompileConfig.builder()
        .interruptBefore(NODE_HUMAN_DECISION)    // 审批前中断
        .saverConfig(saverConfig)                // 状态存 Redis，不丢
        .build();
```

流程：

```text
... → 生成调拨建议 → 发审批邮件 → [中断] ──────────────► 创建调拨单 → END
                                     │                        ▲
                                     │ 审批人点链接            │
                                     ▼                        │
                              回调接口，带 threadId ───────────┘
```

### 3、恢复的关键：threadId

中断时，要能**找回这个任务**。所以每次执行都要带一个唯一 ID：

```java
long threadId = IdUtil.getSnowflakeNextId();
RunnableConfig runnableConfig = RunnableConfig.builder()
        .threadId(threadId + "")
        .build();
graph.invoke(Map.of("productId", productId, "threadId", threadId + ""), runnableConfig);
```

审批邮件里带上这个 `threadId`，用户点链接时就把它传回来，系统据此**恢复对应的那个中断任务**：

```java
@GetMapping("/decision")
public R<Void> decision(@RequestParam Boolean approval,
                        @RequestParam String threadId) throws Exception {
    productSaleService.decision(approval, threadId);   // 用 threadId 恢复
    return R.ok();
}
```

### 4、安全细节

注意一个容易被忽视的点：**审批结果不能经过模型转述。**

```text
❌ 错误做法：模型说"用户已经批准了" → 系统执行退款
✅ 正确做法：审批结果由回调接口的参数直接传入
```

因为模型可能被诱导，也可能理解错。**"人工确认"这件事，关键信息必须由程序直接从人那里拿到，不经过模型这一层。**

### 5、中断也要有超时

审批不能无限等：

```text
超时未审批 → 自动驳回 / 转交上级 / 提醒催办
```

## 五、补偿

### 1、为什么需要补偿

长任务往往不是"一步搞定"，而是"多步叠加"：

```text
第 1 步：扣库存   ✅
第 2 步：扣款     ✅
第 3 步：发通知   ❌ 失败
```

第 3 步失败了，前两步怎么办？**不能就这么算了**，得把前两步"补回来"。

### 2、补偿 vs 回滚

- **回滚**：数据库事务的 `ROLLBACK`，能恢复到事务开始前的状态。
- **补偿**：对于**跨服务、跨系统**的操作，没有全局事务，只能做"反向操作"。

```text
扣了库存  →  补偿：把库存加回来
扣了款    →  补偿：退款
发了通知  →  补偿：发一条更正通知
```

**补偿不是"撤销"，而是"做一件相反的事"。** 它本身也可能失败，所以要能重试。

### 3、补偿的设计要点

- **每个正向操作，都要有对应的补偿操作**。
- **补偿要幂等**：补偿可能重试很多次。
- **补偿要有记录**：补偿了什么、什么时候、结果如何。
- **补偿失败要告警**：人工介入。

### 4、Saga 模式

这是补偿的经典模式，把长事务拆成一系列本地事务，每个都有对应的补偿：

```text
T1 ──► T2 ──► T3 ──► T4
        │      │      │
      C2 ◄────┘      │        失败时依次执行补偿
      C1 ◄───────────┘
```

有两种补偿方向：

- **向后恢复**：T3 失败 → 补偿 C2、C1，回到起点。
- **向前恢复**：T3 失败 → 重试 T3，直到成功。

**不可逆的操作用向前恢复（重试），可逆的用向后恢复（补偿）。**

## 六、幂等

前面反复出现"幂等"这个词，因为长任务**离不开它**。

### 1、为什么长任务特别需要幂等

因为长任务里，"重试"和"恢复"是常态：

```text
场景 1：执行成功 → 存检查点失败 → 恢复 → 又执行一次
场景 2：调用超时 → 实际成功 → 重试 → 又执行一次
场景 3：中断 → 恢复 → 从断点重跑 → 又执行一次
```

**如果操作不幂等，每一次重试都是事故。**

### 2、怎么实现幂等

**（1）幂等键 + 唯一索引（最可靠）**

```sql
CREATE TABLE idempotent_record (
    idempotent_key VARCHAR(191) PRIMARY KEY,   -- 唯一索引兜底
    result         TEXT,
    status         VARCHAR(20),
    created_at     DATETIME
);
```

```java
public Object invoke(ProceedingJoinPoint pjp, String key) {
    // 尝试插入：插入成功说明是第一次执行
    if (!idempotentRepository.tryInsert(key)) {
        return idempotentRepository.getResult(key);   // 已执行过，返回旧结果
    }
    Object result = pjp.proceed();
    idempotentRepository.saveResult(key, result);
    return result;
}
```

**用数据库唯一索引做兜底，是最可靠的**：即使并发，也不会重复。

**（2）状态检查**

执行前先看状态，做过就跳过：

```java
if (state.get("refundDone", Boolean.class)) {
    return Map.of();   // 已经做过，跳过
}
```

**（3）分布式锁**

多实例部署时，用 Redis 锁保证同一时刻只有一个实例在处理：

```java
Boolean locked = redisTemplate.opsForValue()
        .setIfAbsent("lock:" + taskId, "1", 30, TimeUnit.SECONDS);
if (Boolean.FALSE.equals(locked)) {
    return;   // 别的实例在处理
}
```

### 3、幂等键怎么设计

```java
// 好的幂等键：能唯一标识"这一次操作"
String key = taskId + ":refund";           // 任务 + 动作
String key = orderId + ":deduct";          // 业务对象 + 动作
String key = productId + ":" + warehouseId + ":" + saleDate;  // 业务维度组合
```

**关键：同一个逻辑操作，重试时必须生成相同的键。** 如果用 `UUID.randomUUID()` 当键，那每次都不同，幂等就失效了。

## 七、实践验证：中断恢复与幂等消费

这一节看 Lynxe 和 double-ai-agent 里长任务管理是怎么落地的。

### 1、任务状态机

```java
public enum DesiredTaskState {
    START, STOP, PAUSE, RESUME, CANCEL, WAIT
}
```

```java
public class RootTaskManagerEntity {
    private String rootPlanId;
    private DesiredTaskState desiredTaskState;
    private LocalDateTime createdAt;
    private LocalDateTime lastUpdated;

    public RootTaskManagerEntity() {
        this.createdAt = LocalDateTime.now();
        this.lastUpdated = LocalDateTime.now();
        this.desiredTaskState = DesiredTaskState.WAIT;   // 默认等待
    }
}
```

### 2、中断检查：执行器的检查点

```java
@Component
public class AgentInterruptionHelper {

    @Autowired
    private TaskInterruptionCheckerService interruptionCheckerService;

    /** 检查是否该中断，该中断就抛异常，让执行优雅停下 */
    public void checkInterruptionAndThrow(String rootPlanId) throws TaskInterruptedException {
        interruptionCheckerService.checkAndThrowIfInterrupted(rootPlanId);
    }

    /** 检查是否该中断，不抛异常 */
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

**为什么用"异常"而不是"杀线程"？** 让执行流程走到安全点再退出，保证资源释放、状态保存。

### 3、中断状态的持久化

中断请求存在数据库里，**跨实例、跨重启都有效**：

```java
@Service
@Transactional(readOnly = true)
public class TaskInterruptionCheckerService {

    public boolean shouldInterruptExecution(String rootPlanId) {
        // 从数据库查这个任务的期望状态
        return taskInterruptionManager.shouldInterruptTask(rootPlanId);
    }
}
```

**这一点很关键**：因为 Agent 可能部署在多个实例上，任务可能被调度到任意一个实例。把中断状态放在**共享存储（数据库）** 里，才能保证"用户点了暂停，不管任务跑到哪台机器上，都能停下来"。

### 4、等待用户输入

```java
public class UserInputWaitState implements Serializable {
    private String planId;
    private String title;
    private boolean waiting;
    private String formDescription;
    private List<Map<String, String>> formInputs;
}
```

执行到"需要用户填表"时挂起，等用户提交后恢复。

### 5、幂等消费

Kafka 消费端用 Redis 做幂等去重：

```java
String redisKey = String.format(PRODUCT_SALE_KEY, productId, warehouseId, saleDate);
Boolean res = redisTemplate.opsForValue()
        .setIfAbsent(redisKey, jsonStr, 1, TimeUnit.DAYS);

if (Boolean.FALSE.equals(res)) {
    log.warn("重复消息, 已跳过: productId={}, warehouseId={}", productId, warehouseId);
    continue;   // 已处理过，跳过
}
```

**幂等键是"商品 + 仓库 + 日期"的组合**——同一个商品、同一个仓库、同一天的销售事件，只处理一次。这就把"Kafka 至少一次投递"带来的重复，挡在了业务逻辑之外。

### 6、检查点 + 中断 + 恢复的组合

```java
// 编译时配置：Redis 保存检查点 + 审批前中断
SaverConfig saverConfig = SaverConfig.builder()
        .register(RedisSaver.builder().redisson(redissonClient).build())
        .build();

CompileConfig compileConfig = CompileConfig.builder()
        .interruptBefore(NODE_HUMAN_DECISION)
        .saverConfig(saverConfig)
        .build();

CompiledGraph compiledGraph = graph.compile(compileConfig);
```

- **`RedisSaver`**：每步状态存 Redis，服务重启不丢。
- **`interruptBefore`**：审批前中断，状态保持，等回调恢复。

![image-20261011115000001](assets/image-20261011115000001.png)

![image-20261011115000002](assets/image-20261011115000002.png)

### 7、这一步验证了什么

- **状态存共享存储**：`RootTaskManagerEntity` 存数据库、检查点存 Redis，保证跨实例、跨重启有效。
- **协作式中断**：用异常让执行走到安全点，而不是杀线程。
- **中断 + 检查点 + threadId 三者配合**：才能实现"等 8 小时审批还能恢复"。
- **幂等键要稳定**：`productId:warehouseId:saleDate` 保证同一逻辑操作重试时键相同。
- **审批不经过模型**：回调参数直接来自用户。

> 长任务管理说到底是在回答一句话：**"如果这一步做完了但没记上，或者记上了但没做完，会怎样？"** 检查点解决"没记上"，幂等解决"重复做"，补偿解决"做了一半"，中断恢复解决"停下来了"。四个机制配齐，长任务才敢上线。

## 小结

这一篇把 Agent 长任务管理讲清楚了：

- **长任务的难点在"中间状态"**：服务重启、用户取消、等待审批、外部超时。
- **检查点是基础**：每步后保存状态；先执行后存检查点；存 Redis 热数据 + MySQL 归档。
- **暂停用协作式**：写入期望状态，执行器在安全点主动停，**不要杀线程**。
- **恢复的三个前提**：状态可持久化、步骤幂等、进度可定位。
- **审批中断**靠 `interruptBefore` + 检查点 + `threadId`；**审批结果不经过模型**；审批要有超时。
- **补偿是"做相反的事"**，不是回滚；每个正向操作都要有补偿；不可逆的用重试（向前恢复）。
- **幂等是长任务的命根子**：幂等键 + 唯一索引最可靠；幂等键必须**稳定**，不能每次随机。

下一篇是进阶专题的最后一篇：《Agent 生产化》——多租户、成本预算、限流、并发控制和故障恢复，把前面所有东西组装成一个能扛住真实流量的系统。
