+++
title = "Java Agent 工程化实战"
date = 2026-10-11T00:00:00+08:00
weight = 19
tags = ["Agent", "Spring AI", "工程化", "部署", "Java"]
summary = "Agent 系列（十）：把前面所有内容落到一个可维护、可部署的 Java 系统，讲清 Spring AI 抽象、运行时上下文、存储协同、异步与幂等、部署与可观测。"

+++

这是本系列的最后一篇。

前面九篇把 Agent 的每个零件都讲了一遍：模型、工具、RAG、记忆、工作流、多 Agent、MCP、评估安全。但零件不等于系统。这一篇把它们**组装成一个能部署、能维护、能上线的 Java 后端服务**。

这一篇不引入太多新概念，重点是**怎么组织代码、怎么划分层次、怎么处理那些"零件都对但组装起来就出问题"的地方**。

## 一、Spring AI 核心抽象与模型集成

先把 Spring AI 的核心抽象理一遍，后面所有代码都建立在这些抽象上。

### 1、四个核心接口

```text
ChatModel      —— 最底层，负责和具体模型通信
ChatClient     —— 上层封装，流式 API，日常主要用它
EmbeddingModel —— 负责把文本转向量（RAG 用）
ChatMemory     —— 负责对话历史（记忆用）
```

层次关系：

```text
业务代码
   │
   ▼
ChatClient（Fluent API，带 Advisor 链）
   │
   ▼
ChatModel（具体模型的实现：OpenAI / DashScope / Ollama...）
   │
   ▼
HTTP / SDK
```

**日常开发用 `ChatClient`，需要更底层控制时才碰 `ChatModel`。**

### 2、模型集成

以 OpenAI 兼容接口为例：

```yaml
spring:
  ai:
    openai:
      api-key: ${OPENAI_API_KEY}
      base-url: https://api.openai.com
      chat:
        options:
          model: gpt-4o-mini
          temperature: 0.2
      embedding:
        options:
          model: text-embedding-3-small
```

```java
@Bean
public ChatClient chatClient(ChatModel chatModel) {
    return ChatClient.builder(chatModel).build();
}
```

**要点：配置和代码分离。** 模型名、地址、密钥都放配置，方便在不同环境切换、也方便做降级（备用模型）。

### 3、多模型分层

前面讲过模型分层，工程上一般配两套：

```java
@Bean("strongClient")
public ChatClient strongClient(@Qualifier("strongModel") ChatModel model) {
    return ChatClient.builder(model)
            .defaultOptions(ChatOptions.builder().temperature(0.0).build())
            .build();
}

@Bean("cheapClient")
public ChatClient cheapClient(@Qualifier("cheapModel") ChatModel model) {
    return ChatClient.builder(model)
            .defaultOptions(ChatOptions.builder().temperature(0.0).build())
            .build();
}
```

复杂决策用 `strongClient`，分类抽取用 `cheapClient`。

## 二、ChatClient 与 Tool Calling

工具系统的工程化封装，关键在于**让工具的定义、注册、执行分层清晰**。

### 1、工具的分层组织

```text
┌──────────────────────────────────────┐
│  业务 Service 层（真正的业务逻辑）      │
│  OrderService / RefundService ...     │
└──────────────────────────────────────┘
              ▲ 调用
┌──────────────────────────────────────┐
│  工具层（Agent 的工具，只做适配）       │
│  OrderTools / RefundTools ...         │
│  - 描述、参数校验、权限、结果裁剪       │
└──────────────────────────────────────┘
              ▲ 注册
┌──────────────────────────────────────┐
│  ChatClient（按场景组合工具）           │
└──────────────────────────────────────┘
```

**工具层不写业务逻辑，只做"适配"**：把 Service 的能力包装成模型能用的形式。业务逻辑留在 Service 里，这样才能被复用、被测试。

```java
@Component
public class OrderTools {

    private final OrderService orderService;

    @Tool(description = "根据订单号查询订单状态和物流信息。"
            + "适用于用户询问订单进度、位置。orderId 为 20 位数字。")
    public OrderBrief queryOrder(
            @ToolParam(description = "订单号，20 位数字") String orderId,
            ToolContext ctx) {
        // 1. 参数校验
        if (!orderId.matches("\\d{20}")) {
            return OrderBrief.error("订单号格式不正确，应为 20 位数字");
        }
        // 2. 权限校验（在代码里，不在 Prompt 里）
        Order order = orderService.get(orderId);
        if (!order.getUserId().equals(ctx.userId())) {
            return OrderBrief.error("无权访问该订单");
        }
        // 3. 调用业务，裁剪结果
        return OrderBrief.from(order);
    }
}
```

### 2、按场景组合

```java
@Configuration
public class AgentConfig {

    @Bean("aftersaleAgent")
    public ChatClient aftersaleAgent(ChatModel model,
                                     OrderTools orderTools,
                                     RefundTools refundTools) {
        return ChatClient.builder(model)
                .defaultSystem("""
                        你是售后客服。职责：处理订单查询、退换货、物流问题。
                        规则：
                        1. 只依据工具返回的数据回答，不编造。
                        2. 退款金额超过 500 元，必须提示需要人工审批。
                        3. 无法处理的问题，引导用户联系人工客服。
                        """)
                .defaultTools(orderTools, refundTools)
                .build();
    }
}
```

**每个场景一个 ChatClient**，工具集不同、System Prompt 不同，权限边界也就自然收窄了。

## 三、Advisor、对话记忆与 RAG 集成

Advisor 是 Spring AI 里"横切逻辑"的挂载点，记忆和 RAG 都是通过它接入的。

### 1、Advisor 是什么

Advisor 在"请求模型之前"和"模型返回之后"插入逻辑：

```text
请求 ──► [Advisor 链] ──► 模型 ──► [Advisor 链] ──► 响应
             │                          │
        注入历史/RAG资料            记录日志/统计
```

常用的 Advisor：

- `MessageChatMemoryAdvisor`：注入对话历史。
- `QuestionAnswerAdvisor`：RAG 检索并注入资料。
- 自定义 Advisor：日志、限流、脱敏。

### 2、记忆集成

```java
@Bean
public ChatMemory chatMemory(ChatMemoryRepository repository) {
    return MessageWindowChatMemory.builder()
            .chatMemoryRepository(repository)
            .maxMessages(20)
            .build();
}

// 挂到 ChatClient 上
ChatClient client = ChatClient.builder(model)
        .defaultAdvisors(
            MessageChatMemoryAdvisor.builder(chatMemory).build()
        )
        .build();

// 调用时指定会话 ID
String answer = client.prompt()
        .user(question)
        .advisors(a -> a.param(ChatMemory.CONVERSATION_ID, conversationId))
        .call()
        .content();
```

**工程要点：`ChatMemoryRepository` 要用持久化实现（Redis / MySQL），不能用默认的内存实现**，否则重启就丢历史。第 5 篇讲过的持久化，这里落地。

### 3、RAG 集成

```java
@Bean
public ChatClient ragClient(ChatModel model,
                            VectorStore vectorStore,
                            ChatMemory chatMemory) {
    return ChatClient.builder(model)
            .defaultSystem("""
                    你是知识助手。只依据提供的资料回答。
                    资料中没有的内容，明确说"资料中没有提到"。
                    回答时标注引用的资料编号。
                    """)
            .defaultAdvisors(
                MessageChatMemoryAdvisor.builder(chatMemory).build(),
                QuestionAnswerAdvisor.builder(vectorStore)
                        .searchRequest(SearchRequest.builder()
                                .topK(5)
                                .similarityThreshold(0.6)
                                .build())
                        .build()
            )
            .build();
}
```

### 4、自定义 Advisor 做横切

日志、脱敏、限流这些，都可以做成 Advisor：

```java
public class ObservabilityAdvisor implements CallAdvisor {

    @Override
    public ChatClientResponse adviseCall(ChatClientRequest request,
                                         CallAdvisorChain chain) {
        long start = System.currentTimeMillis();
        try {
            ChatClientResponse response = chain.nextCall(request);
            // 记录：耗时、token、traceId
            metrics.record(response, System.currentTimeMillis() - start);
            return response;
        } catch (Exception e) {
            metrics.recordFailure(e);
            throw e;
        }
    }

    @Override
    public String getName() { return "observability"; }

    @Override
    public int getOrder() { return Ordered.LOWEST_PRECEDENCE; }
}
```

**把横切逻辑做成 Advisor，业务代码就干净了**，这和工具执行器的思路是一样的。

## 四、Spring AI Alibaba 与 Graph 工作流

复杂流程用第 6 篇讲的状态图来编排。Spring AI Alibaba 提供了 Graph 的实现。

### 1、定义状态

```java
public class OrderFlowState {
    private String taskId;
    private String userId;
    private String orderId;
    private BigDecimal amount;
    private Boolean approved;
    private String result;

    // getter / setter
}
```

### 2、构建图

```java
StateGraph<OrderFlowState> graph = new StateGraph<>(OrderFlowState.class);

// 节点
graph.addNode("validate", this::validate);
graph.addNode("fetchOrder", this::fetchOrder);
graph.addNode("autoApprove", this::autoApprove);
graph.addNode("manualApprove", this::manualApprove);
graph.addNode("executeRefund", this::executeRefund);
graph.addNode("report", this::report);

// 边
graph.addEdge(StateGraph.START, "validate");
graph.addEdge("validate", "fetchOrder");

// 条件路由：金额决定走自动还是人工
graph.addConditionalEdges("fetchOrder",
        state -> state.getAmount().compareTo(new BigDecimal("500")) <= 0
                ? "autoApprove" : "manualApprove",
        Map.of("autoApprove", "autoApprove",
               "manualApprove", "manualApprove"));

graph.addEdge("autoApprove", "executeRefund");
graph.addEdge("manualApprove", "executeRefund");
graph.addEdge("executeRefund", "report");
graph.addEdge("report", StateGraph.END);
```

### 3、加检查点

```java
CompiledGraph<OrderFlowState> compiled = graph.compile(
        CompileConfig.builder()
                .saverConfig(SaverConfig.builder()
                        .type(SaverType.REDIS)   // 检查点存 Redis
                        .build())
                .build()
);
```

有了检查点，人工审批挂几小时也不怕，服务重启也能从断点恢复。

### 4、什么时候用 Graph

**流程长、需要中断恢复、需要人工介入、需要可视化时，用 Graph。** 简单的单轮问答，直接 `ChatClient` 就够了，不用上图。

## 五、Agent 运行时上下文设计

Agent 执行时需要一堆"环境信息"，这些信息要统一管理，不能到处传参。

### 1、上下文里放什么

```java
public record AgentContext(
        String traceId,          // 链路追踪 ID
        String userId,           // 当前用户
        String tenantId,         // 租户（多租户隔离）
        String conversationId,   // 会话 ID
        String taskId,           // 任务 ID
        Set<String> permissions, // 权限
        String channel           // 来源渠道（App / Web / API）
) {}
```

### 2、怎么传递

用 ThreadLocal 或者框架的上下文机制，**避免每个方法都传一遍**：

```java
public class AgentContextHolder {
    private static final ThreadLocal<AgentContext> CONTEXT = new ThreadLocal<>();

    public static void set(AgentContext ctx) { CONTEXT.set(ctx); }
    public static AgentContext get() { return CONTEXT.get(); }
    public static void clear() { CONTEXT.remove(); }
}
```

**注意异步场景下 ThreadLocal 会丢**，要用 `TransmittableThreadLocal` 或者手动传递：

```java
CompletableFuture.supplyAsync(
        () -> {
            AgentContextHolder.set(ctx);   // 异步线程里重新设置
            try { return doWork(); }
            finally { AgentContextHolder.clear(); }
        },
        executor
);
```

**`clear()` 一定要在 finally 里调**，否则线程池复用时会串数据——这是最容易出事故的地方。

### 3、上下文怎么用

工具、Advisor、工作流节点，都从上下文里取需要的信息：

```java
@Tool(description = "查询我的订单")
public OrderBrief queryOrder(String orderId) {
    AgentContext ctx = AgentContextHolder.get();
    // 用 ctx.userId() 做权限校验，而不是从参数里取
    ...
}
```

**关键原则：`userId`、`tenantId` 这些安全相关的信息，只能来自上下文（认证信息），绝不能来自模型输出或用户输入。**

## 六、任务状态、业务数据与执行状态分离

这是工程化里很重要的一条设计原则：**三种"状态"要分开存。**

### 1、三种状态

```text
① 业务数据：订单、用户、商品 —— 属于业务系统，Agent 只是读它
② 执行状态：Agent 跑到哪一步了 —— 属于 Agent，业务系统不关心
③ 会话状态：对话历史、记忆 —— 属于交互层
```

### 2、为什么要分开

- **职责不同**：业务数据的生命周期由业务决定，执行状态由 Agent 决定。
- **存储不同**：业务数据在业务库，执行状态在 Redis/任务库。
- **访问不同**：业务数据要严格权限控制，执行状态相对内部。

如果混在一起，会出现"Agent 的执行日志污染了业务表""清理 Agent 状态时误删了业务数据"这类问题。

### 3、工程结构

```text
┌─────────────────────────────────────────┐
│  业务库（MySQL）                          │
│  orders / users / products ...           │
└─────────────────────────────────────────┘
              ▲ 只读（通过工具）
┌─────────────────────────────────────────┐
│  Agent 执行库（MySQL）                    │
│  agent_task / agent_step / agent_trace   │
└─────────────────────────────────────────┘
              ▲ 读写
┌─────────────────────────────────────────┐
│  Agent 运行时缓存（Redis）                │
│  agent:state:* / agent:memory:*          │
└─────────────────────────────────────────┘
```

**Agent 通过工具"读"业务数据，但不直接"写"业务库**——写操作要经过业务 Service，走业务的校验和事务。

## 七、Redis、MySQL 与向量存储的协同

第 5 篇讲了选型原则，这里讲工程上怎么协同。

### 1. 各司其职

| 存储 | 存什么 | 生命周期 |
| --- | --- | --- |
| Redis | 进行中的会话、执行状态、限流计数 | 小时级，带 TTL |
| MySQL | 任务记录、长期记忆、审计日志 | 永久或长期 |
| 向量库 | 知识库切片、语义记忆 | 长期，随知识更新 |

### 2. 数据流转

```text
任务开始
   │
   ▼
写执行状态到 Redis（带 TTL）
   │
   ├── 过程中：读写 Redis
   │
   ▼
任务结束
   │
   ├── 归档到 MySQL（任务记录）
   ├── 提取长期记忆 → MySQL / 向量库
   └── 清理 Redis
```

### 3. 一致性

跨存储没有强事务，要靠**补偿和幂等**：

```java
// 先写 MySQL（可靠），再删 Redis 缓存
taskRepository.save(task);
redisTemplate.delete("agent:state:" + taskId);
```

**顺序很重要：先写可靠存储，再清理缓存。** 反过来的话，中间失败会导致数据丢失。

## 八、异步任务、超时、取消与恢复

Agent 任务往往很长（几十秒到几分钟），不能占着 HTTP 线程等。

### 1. 异步化

```java
@PostMapping("/agent/tasks")
public TaskResponse submit(@RequestBody TaskRequest request) {
    String taskId = taskService.create(request);
    // 提交到线程池，立即返回
    taskExecutor.execute(() -> agentRunner.run(taskId));
    return new TaskResponse(taskId, "RUNNING");
}

@GetMapping("/agent/tasks/{taskId}")
public TaskStatus query(@PathVariable String taskId) {
    return taskService.getStatus(taskId);
}
```

**提交返回 taskId，然后轮询或推送结果。** 这是长任务的标准做法。

### 2. 超时

整个任务要有总超时，单个步骤也要有超时：

```java
// 总超时
CompletableFuture<Result> future = CompletableFuture.supplyAsync(
        () -> agentRunner.run(taskId), executor);
future.orTimeout(5, TimeUnit.MINUTES)
      .exceptionally(ex -> {
          taskService.markTimeout(taskId);
          return null;
      });
```

### 3. 取消

用户可能想取消正在跑的任务：

```java
public void cancel(String taskId) {
    Future<?> future = runningTasks.get(taskId);
    if (future != null) {
        future.cancel(true);   // 中断
    }
    taskService.markCancelled(taskId);
    stateStore.delete(taskId);
}
```

**取消要能真正停下**：检查中断标志、及时释放资源。

```java
for (Step step : steps) {
    if (Thread.currentThread().isInterrupted()) {
        throw new TaskCancelledException(taskId);
    }
    execute(step);
}
```

### 4. 恢复

结合第 6 篇的检查点机制：

```java
public void resume(String taskId) {
    AgentState state = stateStore.load(taskId);
    switch (state.status()) {
        case "WAITING_USER":
            // 用户还没回复，不动
            break;
        case "RUNNING":
            // 从断点继续
            agentRunner.continueFrom(state);
            break;
    }
}
```

**恢复的前提是状态持久化和步骤幂等**，这两点前面都讲过了。

## 九、幂等控制、权限校验与事务边界

### 1. 幂等控制

前面讲过，这里给出工程上统一的实现方式——**用注解 + 幂等表**：

```java
@Idempotent(key = "#taskId + ':refund'")
public void executeRefund(String taskId, BigDecimal amount) {
    // ...
}
```

底层用一张幂等表：

```sql
CREATE TABLE idempotent_record (
    idempotent_key VARCHAR(191) PRIMARY KEY,
    result         TEXT,
    status         VARCHAR(20),
    created_at     DATETIME
);
```

```java
public Object invoke(ProceedingJoinPoint pjp, String key) {
    // 尝试插入，插入成功说明是第一次
    if (!idempotentRepository.tryInsert(key)) {
        return idempotentRepository.getResult(key);   // 已执行过，返回旧结果
    }
    Object result = pjp.proceed();
    idempotentRepository.saveResult(key, result);
    return result;
}
```

**用数据库唯一索引兜底，是幂等最可靠的实现**：并发下也不会重复。

### 2. 权限校验

权限校验分三层：

```text
① 接口层：用户能不能访问这个 Agent
② 工具层：这个用户能不能调这个工具、能不能操作这条数据
③ 数据层：查询时强制带上 userId / tenantId 条件
```

```java
// ① 接口层
@PreAuthorize("hasAuthority('AGENT_AFTERSALE')")
@PostMapping("/agent/aftersale")
public ... { }

// ② 工具层（前面讲过）
if (!order.getUserId().equals(ctx.userId())) {
    return error("无权访问");
}

// ③ 数据层：所有查询强制带条件
// WHERE user_id = #{userId}
```

**三层都要，缺一层都可能漏。** 尤其是数据层，很多越权问题就是"查询忘了带 userId 条件"。

### 3. 事务边界

**Agent 的整个执行过程不能放在一个大事务里**，因为：

- 执行时间长，长事务会拖垮数据库。
- 中间要等用户输入，事务根本没法保持。
- 涉及外部调用（模型、HTTP），事务管不了。

正确做法是**每个业务操作单独事务**：

```java
// ❌ 错误：整个 Agent 流程一个事务
@Transactional
public void runAgent(String taskId) {
    ... // 几十秒的执行，中间还调模型、等用户
}

// ✅ 正确：每个写操作各自事务
public void runAgent(String taskId) {
    step1();   // 内部有 @Transactional
    step2();   // 内部有 @Transactional
}
```

**事务只包住"需要原子性的那一段"**，通常是一个业务写操作。跨步骤的一致性，靠幂等和补偿，不靠大事务。

## 十、Docker 部署、日志、指标与链路追踪

### 1. Docker 部署

```dockerfile
FROM eclipse-temurin:21-jre
WORKDIR /app
COPY target/agent-service.jar app.jar
ENV JAVA_OPTS="-Xms512m -Xmx2g"
EXPOSE 8080
ENTRYPOINT ["sh", "-c", "java $JAVA_OPTS -jar app.jar"]
```

```yaml
# docker-compose.yml
services:
  agent-service:
    build: .
    ports: ["8080:8080"]
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - REDIS_HOST=redis
      - MYSQL_HOST=mysql
    depends_on: [redis, mysql]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/actuator/health"]
      interval: 30s

  redis:
    image: redis:7-alpine

  mysql:
    image: mysql:8
    environment:
      - MYSQL_ROOT_PASSWORD=${MYSQL_PASSWORD}
```

**要点：密钥用环境变量注入，别写进镜像；配健康检查。**

### 2. 日志

日志要**结构化**，方便检索：

```java
log.info("agent_llm_call traceId={} taskId={} model={} inputTokens={} outputTokens={} cost={}ms",
        ctx.traceId(), ctx.taskId(), model, inTokens, outTokens, cost);
```

用 JSON 格式输出，配合 ELK / Loki 检索：

```json
{
  "level": "INFO",
  "event": "agent_llm_call",
  "traceId": "abc123",
  "taskId": "task_001",
  "model": "gpt-4o-mini",
  "inputTokens": 520,
  "outputTokens": 180,
  "cost": 1200
}
```

### 3. 指标

用 Micrometer 暴露指标，Prometheus 采集：

```java
@Component
public class AgentMetrics {

    private final Counter llmCalls;
    private final Timer llmLatency;
    private final Counter toolCalls;

    public AgentMetrics(MeterRegistry registry) {
        this.llmCalls = Counter.builder("agent.llm.calls")
                .tag("model", "unknown").register(registry);
        this.llmLatency = Timer.builder("agent.llm.latency").register(registry);
        this.toolCalls = Counter.builder("agent.tool.calls").register(registry);
    }

    public void recordLlm(String model, long ms) {
        llmCalls.increment();
        llmLatency.record(Duration.ofMillis(ms));
    }
}
```

要暴露的关键指标：

```text
agent.task.total         任务总数
agent.task.success       成功数（算成功率）
agent.llm.calls          模型调用次数
agent.llm.latency        模型调用延迟
agent.llm.tokens         模型 token 消耗
agent.tool.calls         工具调用次数
agent.tool.errors        工具失败次数
```

**这些指标直接对应第 9 篇讲的成本统计和可观测性。**

### 4. 链路追踪

用 OpenTelemetry 把一次 Agent 执行串成完整链路：

```java
@Bean
public ObservationRegistry observationRegistry() {
    return ObservationRegistry.create();
}

// 模型调用
ChatClient client = ChatClient.builder(model)
        .defaultAdvisors(new ObservationAdvisor(observationRegistry))
        .build();
```

这样在 Jaeger / Zipkin 里能看到：

```text
[HTTP POST /agent/tasks]  2100ms
  └─ [agent.run]  2050ms
       ├─ [llm.call]  900ms   tokens=520
       ├─ [tool.queryOrder]  340ms
       └─ [llm.call]  700ms   tokens=380
```

**一眼就能看出时间花在哪、token 花在哪。** 这就是前面反复强调的"可观测性"的最终形态。

### 5. 一个完整的上线检查清单

```text
□ 模型：多模型分层配置，有备用模型
□ 工具：描述清晰、参数校验、权限在代码里、有超时
□ 记忆：持久化到 Redis/MySQL，会话隔离
□ RAG：切分合理、有 Rerank、评估过召回率
□ 工作流：关键步骤有检查点，能中断恢复
□ 安全：最小权限、人工确认、敏感数据脱敏、注入防护
□ 容错：重试、降级、熔断、兜底齐全
□ 幂等：写操作都有幂等控制
□ 事务：没有大事务，事务边界清晰
□ 可观测：日志结构化、指标齐全、链路能串起来
□ 评估：有评估集，上线前跑过，有回归测试
□ 部署：密钥用环境变量、有健康检查
```

## 十一、实践验证：一个可部署的双 Agent 系统

前面讲的工程化设计，这一节用一个完整的开源项目来对照——**Double AI Agent**，它把"图编排 + RAG + 状态持久化 + 异步触发 + 人工审批 + 幂等"全用上了，正好可以逐条验证前面的设计原则。

### 1、项目结构：按能力分模块

```text
double-ai-agent/
├── ai-common/        公共模块：Redis、邮件、Excel、常量
├── ai-bi-helper/     BI 查询 Agent（RAG + 生成 SQL + 执行 + 发邮件）
└── ai-transfer/      库存调拨 Agent（并行采集 + AI 预测 + 人工审批）
```

两个 Agent 各自独立部署、独立配置，通过 Nacos 管理配置、通过 Redis 共享状态基础设施——对应"任务状态、业务数据与执行状态分离"一节：**业务数据在 MySQL，执行状态在 Redis，两者不混。**

### 2、Spring AI 核心抽象与配置

```yaml
spring:
  ai:
    dashscope:
      api-key: ${AI_DASHSCOPE_API_KEY}   # 密钥走环境变量，不写进代码
      chat:
        options:
          model: qwen3.6-plus
    vectorstore:
      milvus:
        collectionName: "vector_store"
        embeddingDimension: 768
```

**密钥用环境变量注入**，这是前面"部署"一节强调的第一条。

### 3、Graph 工作流 + Redis 检查点

两个 Agent 都是 Graph 编排，并且都用 Redis 做检查点：

```java
SaverConfig saverConfig = SaverConfig.builder()
        .register(RedisSaver.builder().redisson(redissonClient).build())
        .build();

CompileConfig compileConfig = CompileConfig.builder()
        .interruptBefore(TransferGraphConstant.NodeName.HUMAN_DECISION)  // 中断点
        .saverConfig(saverConfig)                                        // 持久化
        .build();

CompiledGraph compiledGraph = graph.compile(compileConfig);
```

对应前面"Spring AI Alibaba 与 Graph 工作流"：**长流程必须配检查点，才能中断和恢复。**

### 4、异步触发与幂等

调拨流程不是 HTTP 同步等待的，而是由 Kafka 消息**异步触发**：

```java
@KafkaListener(topics = KafkaConstant.KAFKA_PRODUCT_SALE_TOPIC, groupId = "group1")
public void productSaleConsume(List<String> jsonStrs, Acknowledgment acknowledgment) {
    for (String jsonStr : jsonStrs) {
        // 幂等：Redis 去重，同一天同一商品不重复处理
        Boolean res = redisTemplate.opsForValue()
                .setIfAbsent(redisKey, jsonStr, 1, TimeUnit.DAYS);
        if (Boolean.FALSE.equals(res)) continue;

        // 生成 threadId，异步触发图
        long threadId = IdUtil.getSnowflakeNextId();
        RunnableConfig runnableConfig = RunnableConfig.builder().threadId(threadId + "").build();
        graph.invoke(Map.of("productId", productId, "threadId", threadId + ""), runnableConfig).get();
    }
    acknowledgment.acknowledge();   // 手动提交
}
```

这一段同时验证了三件事：

- **异步任务**：长流程不占 HTTP 线程，由消息触发。
- **幂等控制**：`setIfAbsent` 保证重复消息不重复执行。
- **手动提交**：`acknowledgment.acknowledge()` 处理完才提交，对应 Kafka 的可靠性设计。

### 5、RAG 与 Advisor 集成

BI Agent 用 `RetrievalAugmentationAdvisor` 把 RAG 挂进 ChatClient：

```java
RetrievalAugmentationAdvisor advisor = RetrievalAugmentationAdvisor.builder()
        .queryTransformers(RewriteQueryTransformer.builder()
                .chatClientBuilder(builder).build())
        .documentRetriever(VectorStoreDocumentRetriever.builder()
                .similarityThreshold(0.50)
                .vectorStore(vectorStore).build())
        .queryAugmenter(ContextualQueryAugmenter.builder()
                .allowEmptyContext(true).build())
        .build();
```

对应前面"Advisor、对话记忆与 RAG 集成"：**记忆、RAG、日志这些横切逻辑，都用 Advisor 挂载，业务代码保持干净。**

### 6、完整链路

把两个 Agent 串起来看：

```text
【BI 查询】
用户提问 → RAG 检索表结构 → 生成 SQL → 评估 → 执行 → 转 Excel → 发邮件

【库存调拨】
销售消息(Kafka) → 幂等去重 → 并行采集 → AI 预测 → 发审批邮件
                                    → [中断] → 人工审批 → 创建调拨单
```

![image-20261011109000001](assets/image-20261011109000001.png)

![image-20261011109000002](assets/image-20261011109000002.png)

### 7、这一步验证了什么

对照前面那份"上线检查清单"，这个项目逐条落地了：

| 清单项 | 项目里的体现 |
| --- | --- |
| 工具/权限 | SQL 只允许 SELECT，自动加 LIMIT |
| 记忆/状态 | Redis 检查点，支持断点恢复 |
| RAG | Milvus + `RetrievalAugmentationAdvisor` |
| 工作流 | Graph + 条件路由 + 中断 |
| 安全 | 最小权限 + 人工确认 + 密钥走环境变量 |
| 幂等 | Kafka 消费端 Redis 去重 |
| 可观测 | 每步 `log.info` 记录，PlantUML 打印图结构 |
| 部署 | 多模块独立部署，Nacos 管配置 |

**它没有做的**（也正是可以继续完善的方向）：完整的链路追踪（OpenTelemetry）、Token 成本统计、评估集与回归测试——这些是前面"评估"和"可观测性"两节的内容，需要在项目里补上。

> 这个项目是很好的工程化参考：它证明了前面讲的设计原则不是纸上谈兵，而是真的能组装成一个跑得起来的系统。但要注意它的示例数据、邮件密码等都是演示用的，上线前必须替换。

## 小结

这一篇把前面所有内容落到了一个 Java 系统上：

- **Spring AI 的核心抽象**：`ChatClient` 日常用，`ChatModel` 底层用，配置和代码分离，模型分层。
- **工具要分层**：工具层只做适配，业务逻辑留在 Service，按场景组合工具集。
- **Advisor 是横切逻辑的挂载点**：记忆、RAG、日志、指标都挂这里。
- **复杂流程用 Graph**，配检查点支持中断恢复；简单场景直接 `ChatClient`。
- **运行时上下文统一管理**，注意异步传递和 `clear()`，安全信息只能来自认证。
- **业务数据、执行状态、会话状态三者分开存。**
- **Redis、MySQL、向量库各司其职**，跨存储靠补偿和幂等，先写可靠存储再清缓存。
- **长任务异步化**，配总超时、步骤超时、取消和恢复。
- **幂等用注解 + 唯一索引兜底；权限三层校验；不要大事务。**
- **部署用 Docker，密钥走环境变量；日志结构化、指标齐全、链路可追踪。**

回头看整个系列，从"Agent 是什么"一路走到"怎么上线一个 Agent 系统"，其实贯穿了三条主线：

- **模型负责决策，代码负责执行和约束。** 凡是安全、权限、幂等这类不能出错的地方，都要落在代码里，而不是指望 Prompt。
- **上下文是稀缺资源。** 模型、工具、知识、记忆，最终都是在争夺上下文窗口，所以要精简、要分层、要有预算。
- **Agent 的质量是养出来的。** 靠评估集、回归测试、线上监控形成闭环，持续迭代。

这套方法论不只适用于 Java，换个语言、换个框架，思路是一样的。真正重要的不是某个框架的 API，而是这些底层的判断。
