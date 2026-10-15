+++
title = "Agent 生产化"
date = 2026-10-11T00:00:00+08:00
weight = 6
tags = ["Agent", "生产化", "多租户", "成本预算", "限流", "并发控制", "故障恢复"]
summary = "进阶专题（六）：讲清多租户隔离、成本预算、限流、并发控制与故障恢复，把 Agent 做成能扛住真实流量的系统。"
+++

这是进阶专题的最后一篇。

前面五个专题把 Agent 的"内部"做扎实了：运行时、规划、代码执行、数据库、长任务。这一篇往"外部"看——**当 Agent 面向真实用户、真实流量时，会遇到什么。**

Demo 里一个用户慢慢用，什么架构都行。一旦上线：几百个租户、上万次调用、成本失控、被刷、上游挂了……这些才是生产化的真正考验。这一篇讲五件事：**多租户、成本预算、限流、并发控制、故障恢复。**

## 一、多租户

### 1、什么是多租户

一套系统，服务多个租户（客户/团队/业务线），彼此数据隔离。

```text
┌─────────────────────────────────────┐
│           Agent 服务                 │
│                                      │
│  ┌────────┐ ┌────────┐ ┌────────┐   │
│  │ 租户 A │ │ 租户 B │ │ 租户 C │   │
│  └────────┘ └────────┘ └────────┘   │
└─────────────────────────────────────┘
        │           │          │
      A 的数据    B 的数据   C 的数据
      （互相不可见）
```

### 2、隔离的层次

多租户的隔离要**层层设防**：

```text
① 认证层：请求进来先确定是哪个租户
② 上下文层：tenantId 放进执行上下文，贯穿全程
③ 数据层：所有查询强制带 tenantId 条件
④ 向量库层：RAG 检索强制按 tenantId 过滤
⑤ 存储层：缓存 key 带租户前缀
⑥ 资源层：配额按租户算
```

### 3、最容易出事的地方

**（1）向量库检索**——最隐蔽的坑。

如果所有租户的文档放在同一个 collection 里，检索时必须带 `tenantId` 过滤：

```java
SearchRequest.builder()
        .query(q)
        .topK(5)
        .filterExpression("tenantId == '" + tenantId + "'")   // 必须过滤
        .build();
```

**忘了这句，A 租户就能检索到 B 租户的私有文档**——这就是数据泄露。

**（2）缓存 key 没带租户**。

```java
// ❌ 不同租户读到同一份缓存
String key = "user:" + userId;

// ✅ 带上租户
String key = "tenant:" + tenantId + ":user:" + userId;
```

**（3）会话记忆串了**。

```java
// ❌
String conversationId = sessionId;
// ✅
String conversationId = tenantId + ":" + userId + ":" + sessionId;
```

### 4、tenantId 从哪来

**这是铁律：`tenantId` 只能来自认证信息，绝不能来自请求参数、用户输入或模型输出。**

```java
// ✅ 从认证上下文取
String tenantId = AgentContextHolder.get().tenantId();

// ❌ 从请求参数取——用户可以随便改
String tenantId = request.getParameter("tenantId");
```

如果从参数取，攻击者传一个别人的 `tenantId` 就能越权。

### 5、命名空间

工程上，多租户常用"命名空间（Namespace）"来表达：

```java
@Entity
@Table(name = "namespace")
public class NamespaceEntity {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private String name;      // 租户名

    @Column(nullable = false)
    private String code;      // 租户编码

    @Column(length = 1024)
    private String description;

    @Column
    private String host;      // 绑定域名
}
```

命名空间可以绑定不同的**配置**（用哪个模型、什么限额、哪些工具），这就把"租户隔离"和"租户定制"统一起来了。

## 二、成本预算

### 1、Agent 的成本特点

Agent 的成本是"乘法"，不是"加法"：

```text
一次任务 = N 次模型调用 × 每次 M 个 token
```

而且 N 是不确定的——ReAct 可能转 3 圈，也可能转 30 圈。所以**如果不加控制，单次任务的成本上限是不确定的**。

### 2、成本从哪来

```text
模型调用    ← 主要成本，按 input/output token 计费
向量检索    ← embedding 调用 + 向量库
工具调用    ← 外部 API 可能也收费
基础设施    ← 服务器、存储
```

模型调用通常是大头，尤其是长上下文 + 多轮循环。

### 3、怎么控成本

**（1）模型分层**

```text
复杂决策（规划、推理）  →  强模型（贵）
简单任务（分类、抽取、改写）→  小模型（便宜）
```

前面《大模型调用与上下文工程》讲过分层，这里再强调一次：**不是所有调用都需要最强的模型。**

**（2）上下文压缩**

历史太长就摘要，工具结果太长就截断。**token 直接等于钱。**

**（3）缓存**

相同的问题直接返回缓存结果：

```java
String cacheKey = "tenant:" + tenantId + ":answer:" + hash(question);
String cached = redis.get(cacheKey);
if (cached != null) return cached;
```

FAQ 类场景命中率很高，能省下大量调用。

**（4）预算上限**

给每个任务设 token 预算：

```java
public class CostBudget {
    private int maxTokens;          // 最大 token 数
    private BigDecimal maxCost;     // 最大金额
    private int maxLlmCalls;        // 最大模型调用次数

    private int usedTokens;
    private BigDecimal usedCost;
    private int usedLlmCalls;
}
```

超过就中断：

```java
if (budget.getUsedTokens() > budget.getMaxTokens()) {
    throw new BudgetExceededException("任务超出 token 预算");
}
```

**（5）按租户计量**

```text
租户 A：本月已用 120 万 token，预算 500 万
租户 B：本月已用 480 万 token，预算 500 万  ← 快超了，要提醒
```

按租户统计，才能发现"谁在烧钱"，也才能做计费和配额。

### 4、成本一定要"看得见"

**不统计就没法优化。** 每次调用都要记：

```java
log.info("llm_call tenant={} task={} model={} inTokens={} outTokens={} cost={}",
        tenantId, taskId, model, inTokens, outTokens, cost);
```

然后按维度聚合：租户、任务类型、模型、工具。

## 三、限流

### 1、为什么要限流

- **保护自己**：防止某个租户或用户把配额打满。
- **保护上游**：别把模型 API、外部接口打爆（会被封）。
- **防滥用**：被刷、被恶意调用。

### 2、限流的维度

```text
用户级：  单个用户 QPS / 每日调用次数
租户级：  单租户 QPS / 每月 token 配额
全局级：  整个服务的并发上限
上游级：  针对某个模型 API 的调用速率
```

**按租户限流最关键**：一个租户不能影响其他租户。

### 3、常见限流算法

| 算法 | 特点 | 适用 |
| --- | --- | --- |
| 计数器 | 简单，有临界问题 | 粗粒度限制 |
| 滑动窗口 | 平滑，精度高 | **推荐**，通用 |
| 漏桶 | 恒定速率 | 需要严格匀速 |
| 令牌桶 | 允许突发 | 允许一定突发的场景 |

滑动窗口是最常用的：

```text
窗口大小 1 分钟，限制 100 次
       ┌───────────────┐
       │  最近 60 秒    │
       │  计数 +1       │
       └───────────────┘
        超过 100 就拒绝
```

### 4、多实例限流要用共享存储

单机限流计数在内存里就行，但**多实例部署时，必须用 Redis 等共享存储**：

```java
String key = "ratelimit:tenant:" + tenantId + ":" + currentMinute();
Long count = redisTemplate.opsForValue().increment(key);
redisTemplate.expire(key, Duration.ofMinutes(2));

if (count > limitPerMinute) {
    throw new RateLimitExceededException("请求过于频繁，请稍后再试");
}
```

否则每个实例各限各的，总量是实例数 × 限制值，等于没限。

### 5、限流的用户体验

限流不能只是"拒绝"，还要：

```text
清晰的提示：   "当前请求过多，请 30 秒后重试"
退避建议：     Retry-After: 30
降级选项：     高峰期切到小模型，或者排队等待
```

**限流是为了系统健康，不是为了惩罚用户。**

## 四、并发控制

### 1、并发的三个层面

```text
① 请求级并发：同时有多少个任务在跑
② 会话级并发：同一个会话不能同时跑多个任务
③ 资源级并发：模型调用、工具调用、连接的并发上限
```

### 2、请求级：线程池隔离

前面 Runtime 篇讲过**按层级隔离线程池**，防止父子任务互相饿死。生产环境还要：

```text
不同租户  →  配额不同（VIP 租户给更大的池）
不同任务类型 →  隔离（长任务不占用交互任务的线程）
```

### 3、会话级：同一会话串行

**同一个会话（同一个用户）的任务应该串行**，否则会出现：

```text
用户：帮我查订单
（同时）
用户：改成查退款
   ↓
两个任务并发跑，上下文互相干扰，结果错乱
```

做法是**按会话加锁**：

```java
String lockKey = "session-lock:" + tenantId + ":" + conversationId;
Boolean locked = redisTemplate.opsForValue()
        .setIfAbsent(lockKey, taskId, 60, TimeUnit.SECONDS);
if (Boolean.FALSE.equals(locked)) {
    throw new SessionBusyException("当前会话有任务正在执行");
}
```

### 4、资源级：信号量

对模型 API、数据库连接这些**有限资源**，用信号量控制并发：

```java
private final Semaphore llmSemaphore = new Semaphore(20);   // 最多 20 个并发模型调用

public String callModel(String prompt) {
    if (!llmSemaphore.tryAcquire(5, TimeUnit.SECONDS)) {
        throw new ServiceBusyException("模型调用繁忙");
    }
    try {
        return doCallModel(prompt);
    } finally {
        llmSemaphore.release();   // 必须释放
    }
}
```

**`release()` 必须放在 `finally` 里**，否则异常时信号量泄漏，最终池子耗尽。

### 5、并发控制的目标

不是"限制并发"，而是**"让并发在可控范围内，且公平分配"**：

- 防止一个租户/会话独占。
- 防止资源耗尽。
- 保证 VIP 的体验（优先级）。

## 五、故障恢复

### 1、故障从哪来

```text
模型侧：限流（429）、超时、服务不可用（5xx）、内容被拒
工具侧：外部接口挂了、超时、返回异常
中间件：Redis / MySQL / Kafka 抖动
自身：OOM、GC 停顿、部署重启
```

**Agent 的调用链很长，任意一环挂了都可能影响整体。**

### 2、四层容错

前面零散讲过，这里统一收拢：

```text
第一层：重试   —— 临时故障，退避重试
第二层：降级   —— 重试不行，换备用
第三层：熔断   —— 持续失败，快速失败
第四层：兜底   —— 全部失败，体面回复
```

### 3、重试

```java
Retry.backoff(3, Duration.ofMillis(500))
     .filter(e -> e instanceof ResourceAccessException          // 超时
               || e instanceof TooManyRequestsException);        // 限流
```

- **只重试临时性错误**：超时、限流、5xx。
- **不重试永久性错误**：参数错、内容被拒。
- **必须带退避**：不能立刻重打。
- **注意幂等**：写操作重试前确认是否已执行。

### 4、降级

```java
public String callWithFallback(String question) {
    try {
        return primaryClient.prompt().user(question).call().content();
    } catch (Exception e1) {
        log.warn("主模型失败，切换备用模型", e1);
        try {
            return backupClient.prompt().user(question).call().content();
        } catch (Exception e2) {
            log.error("备用模型也失败", e2);
            return "抱歉，服务繁忙，请稍后再试。";
        }
    }
}
```

**降级链**：主模型 → 备用模型 → 静态兜底。

### 5、熔断

某个依赖持续失败，就"跳闸"，一段时间内不再尝试：

```java
CircuitBreaker circuitBreaker = CircuitBreaker.ofDefaults("llm");
Supplier<String> guarded = CircuitBreaker.decorateSupplier(
        circuitBreaker, () -> callModel(q));
```

好处是**避免每次都等超时**——快速失败，保护自己和上游。

熔断的三个状态：

```text
CLOSED   →  正常，请求通过
OPEN     →  跳闸，直接失败（快速失败）
HALF_OPEN → 试探，少量请求通过，成功则恢复
```

### 6、兜底

最后的兜底，是给用户一个体面的回复：

```java
return "抱歉，服务暂时繁忙，请稍后再试。";
```

**永远不要让用户看到异常堆栈。**

### 7、故障恢复和长任务的结合

前面长任务篇讲的检查点 + 恢复，本身就是一种故障恢复：

```text
任务跑到一半 → 服务重启 → 从检查点恢复 → 继续跑
```

**所以长任务的"恢复能力"，和生产的"故障恢复"，是同一套机制。**

## 六、实践验证：生产化的关键设计

这一节看两个项目里生产化相关的实现。

### 1、多租户：命名空间

```java
@Entity
@Table(name = "namespace")
public class NamespaceEntity {
    private Long id;
    private String name;         // 租户名
    private String code;         // 租户编码
    private String description;
    private String host;         // 绑定域名
}
```

命名空间不仅隔离数据，还**绑定了租户的配置**（模型、限额、工具集），实现"一套系统、多租户定制"。

![image-20261011116000001](assets/image-20261011116000001.png)

### 2、Token 限额

按模型维护上下文和输出的上限：

```java
@Service
public class TokenLimitService {

    // 默认上下文 128K，默认输出 64K
    private static final int DEFAULT_CONTEXT_LIMIT = 131_072;
    private static final int DEFAULT_OUTPUT_LIMIT  = 65_536;

    // 按模型类型分别设置
    private static final Map<String, Integer> CONTEXT_LIMITS = new HashMap<>();
    private static final Map<String, Integer> OUTPUT_LIMITS  = new HashMap<>();

    static {
        CONTEXT_LIMITS.put("qwen3-coder-plus", 1_048_576);
        OUTPUT_LIMITS.put("qwen3-coder-plus", 65_536);
        CONTEXT_LIMITS.put("gpt-4o", 131_072);
        OUTPUT_LIMITS.put("gpt-4o", 16_384);
        CONTEXT_LIMITS.put("gpt-4", 8_192);
    }
}
```

**为什么要按模型维护？** 因为不同模型的窗口差很多（8K 到 1M），如果统一按最小的算，就浪费了强模型的能力；统一按最大的算，换到小模型就会超限报错。

### 3、对话记忆的自动压缩

成本控制的关键手段——**上下文压缩**：

```java
@Service
public class ConversationMemoryLimitService {

    // 压缩阈值：用到 70% 就开始压缩
    private static final double DEFAULT_COMPRESSION_THRESHOLD = 0.7;
    // 保留比例：保留最近 30%
    private static final double DEFAULT_RETENTION_RATIO = 0.3;
    // 标记压缩摘要的 metadata key
    public static final String COMPRESSION_SUMMARY_METADATA_KEY = "compression_summary";

    /**
     * 检查并限制对话记忆大小：
     * 保留最近一段完整对话，把更早的轮次用大模型摘要成一段。
     */
    public void checkAndLimitMemory(ChatMemory chatMemory, String conversationId) {
        List<Message> messages = chatMemory.get(conversationId);
        if (messages == null || messages.isEmpty()) return;
        // ... 超过阈值就摘要旧消息、保留最近消息
    }
}
```

**"阈值触发 + 保留最近 + 旧轮摘要"**，这就是前面《Agent 状态与记忆机制》讲的压缩策略，在生产里的具体实现。压缩直接省 token，也就是省成本。

### 4、并发：按层级隔离线程池

```java
/** 按层级隔离线程池，防止父子任务互相饿死；最大深度 10 */
public class LevelBasedExecutorPool implements ExecutorPoolProvider {
    private static final int MAX_DEPTH_LEVEL = 10;
    private static final int DEFAULT_QUEUE_CAPACITY = 100;
    private final Map<Integer, ExecutorService> levelPools = new ConcurrentHashMap<>();
}
```

### 5、可配置的护栏

生产环境的护栏都应该**可配置**，才能按租户、按场景调整：

```java
// 最大执行步数
@ConfigProperty(key = "maxSteps", defaultValue = "30")
private volatile Integer maxSteps;

// 用户输入超时
private volatile Integer userInputTimeout;

// 最大记忆条数
private volatile Integer maxMemory;

// 执行器线程池大小
private volatile Integer executorPoolSize;

// 模型读取超时
private volatile Integer llmReadTimeout;

// MCP 连接超时 / 重试 / 并发
private volatile Integer mcpConnectionTimeoutSeconds;
private volatile Integer mcpMaxRetryCount;
private volatile Integer mcpMaxConcurrentConnections;
```

**注意这些配置的分组**：步数、超时、记忆、并发、重试——正好对应前面几篇讲的每一类护栏。**生产化的一个标志，就是所有硬编码的数字都变成了配置。**

![image-20261011116000002](assets/image-20261011116000002.png)

### 6、故障恢复：重试与降级

```java
// Spring AI 内置的重试机制
OpenAiChatModel.builder()
        .openAiApi(api)
        .retryTemplate(RetryUtils.DEFAULT_RETRY_TEMPLATE)   // 默认重试
        .build();
```

加上前面讲的降级链和熔断，就构成了完整的容错。

### 7、这一步验证了什么

- **多租户靠命名空间 + 层层过滤**：`NamespaceEntity` 绑定配置；数据、缓存、向量库都要带租户维度。
- **限额按模型区分**：`TokenLimitService` 说明不同模型窗口不同，不能一刀切。
- **压缩直接省成本**：`ConversationMemoryLimitService` 的阈值触发 + 摘要，是成本优化最有效的手段之一。
- **并发按层级隔离**：`LevelBasedExecutorPool` 防止父子任务互相饿死。
- **护栏全部可配**：步数、超时、记忆、并发、重试都做成配置，才能按租户调整。
- **容错四层**：重试、降级、熔断、兜底。

> 生产化和前面的专题是一体的：**多租户**建立在《Agent 状态与记忆机制》的隔离之上；**成本预算**建立在《大模型调用与上下文工程》的 token 管理之上；**并发控制**建立在《Agent Runtime 设计》的线程池隔离之上；**故障恢复**建立在《Agent 长任务管理》的检查点之上。生产化不是新东西，而是把前面所有东西**在真实流量下捏合好**。

## 小结

这一篇把 Agent 生产化讲清楚了：

- **多租户**要层层隔离：认证、上下文、数据、向量库、缓存、资源；`tenantId` 只能来自认证信息。
- **成本**是乘法，要分层用模型、压缩上下文、加缓存、设预算，并且**一定要能看得见**。
- **限流**按用户/租户/全局/上游分维度，多实例要用共享存储，还要给用户体面的提示。
- **并发控制**分请求级、会话级（同会话串行）、资源级（信号量，`release` 放 `finally`）。
- **故障恢复**四层：重试（只重试临时的）、降级（主→备→兜底）、熔断（快速失败）、兜底（体面回复）。
- **长任务的恢复能力就是生产的故障恢复能力**：检查点 + 幂等是共同的地基。
- **生产化的标志**：所有护栏都变成可配置，按租户、按场景可调。

到这里，整个 Agent 开发系列就讲完了：从基础概念、模型调用、工具、RAG、记忆、工作流、多 Agent、MCP、评估安全，到 Java 工程化落地，再到这个进阶专题的运行时、规划、代码执行、数据库、长任务和生产化。

回头看，贯穿全系列的是三条主线：**模型负责决策、代码负责约束；上下文是稀缺资源；质量是养出来的。** 这三条，比任何具体的 API 都更值得记住。
