+++
title = "Agent 状态与记忆机制"
date = 2026-10-11T00:00:00+08:00
weight = 14
tags = ["Agent", "记忆", "状态", "Redis", "上下文压缩"]
summary = "Agent 系列（五）：区分对话历史与 Agent State，讲清短期/长期记忆、摘要压缩、持久化恢复、存储选型与多用户隔离。"

+++

上一篇的 RAG 解决的是"知识从哪来"。这一篇解决另一个问题：**"发生过什么，Agent 怎么记住"。**

一个只会答单轮问题的 Agent 是没用的。用户说"帮我订张去杭州的票"，Agent 问"哪天走"，用户答"下周三"——如果 Agent 记不住上一句在聊什么，这个对话就没法进行。多轮对话、长任务、跨会话，都要求 Agent 有记忆。

但"记忆"这个词在 Agent 里其实包含了好几层不同的东西，混在一起讲会乱。这一篇先把它们分开，再讲怎么存、怎么取、怎么管。

## 一、对话历史与 Agent State 的区别

先做最重要的一个区分。

### 1、对话历史（Conversation History）

对话历史就是**消息列表**：用户说了什么、Agent 回了什么。

```text
user      : 帮我订张去杭州的票
assistant : 好的，请问哪天出发？
user      : 下周三
```

它的特点是：**线性、只增不减、直接作为模型的上下文。**

### 2、Agent State（执行状态）

Agent State 是**任务执行的状态**，比对话历史结构化得多：

```java
public record AgentState(
        String taskId,
        String goal,                    // 目标：订一张去杭州的票
        Map<String, Object> slots,      // 槽位：{date: "2026-10-14", from: "北京"}
        List<String> completedSteps,    // 已完成：["确认日期", "查询车次"]
        String currentStep,             // 当前：等待用户选车次
        int retryCount,                 // 重试次数
        List<String> toolHistory        // 工具调用记录
) {}
```

它的特点是：**结构化、有明确字段、可以查询和修改、可以持久化。**

### 3、两者的关系

```text
┌─────────────────────────────────────────┐
│           Agent State                    │
│  goal / slots / steps / retry / ...      │
│                                          │
│   ┌──────────────────────────────────┐   │
│   │      对话历史（消息列表）          │   │
│   │  user: ... / assistant: ...       │   │
│   └──────────────────────────────────┘   │
└─────────────────────────────────────────┘
```

- 对话历史是 State 的一部分，但 State 远不止对话历史。
- **对话历史给模型"看"，State 给程序"用"。**
- 恢复任务时，光有对话历史不够，还要有 State——知道任务进行到哪一步、槽位填了什么。

这个区分很重要，因为很多"Agent 记不住"的 bug，根源就是把两者混为一谈：只存了对话历史，丢了执行状态。

## 二、短期记忆与长期记忆

按"存活时间"分，记忆有两类。

### 1、短期记忆

短期记忆是**当前这次会话/任务内**的信息，任务结束就没了。

- 当前对话的消息。
- 当前任务的槽位、中间结果。

它通常放在**内存或 Redis** 里，生命周期跟着会话走。

### 2、长期记忆

长期记忆是**跨会话、跨任务**的信息。

- 用户的偏好：喜欢靠窗座位、不吃辣。
- 用户的画像：VIP 客户、常用地址。
- 历史事实：上次投诉的问题。

它要**持久化到数据库**，能长期保存、能被检索。

### 3、两者的配合

```text
用户提问
   │
   ▼
┌──────────────────────────────┐
│  组装上下文                    │
│  ┌────────────┐ ┌───────────┐ │
│  │ 短期记忆    │ │ 长期记忆   │ │
│  │ 最近对话    │ │ 用户偏好   │ │
│  │ 当前槽位    │ │ 历史事实   │ │
│  └────────────┘ └───────────┘ │
└──────────────────────────────┘
   │
   ▼
模型决策
```

**短期记忆保证"这次聊得下去"，长期记忆保证"每次都记得你"。** 两者都要，缺一不可。

## 三、对话摘要与上下文压缩

短期记忆不能无限增长，前面讲过上下文窗口的问题。这一节讲具体的压缩手段。

### 1、滑动窗口

最简单的做法：只保留最近 N 条。

```java
MessageWindowChatMemory memory = MessageWindowChatMemory.builder()
        .maxMessages(20)
        .build();
```

缺点是会**硬丢掉早期信息**。前面举过的例子：用户第一轮说"我住杭州"，聊了 20 轮后这条信息可能被挤掉了。

### 2、摘要压缩

更好的做法是：**把要丢弃的旧消息，交给模型压缩成一段摘要，再放回上下文。**

```java
public void compress(ChatMemory memory, String conversationId) {
    List<Message> all = memory.get(conversationId);
    if (all.size() <= 20) {
        return;   // 还没到需要压缩的程度
    }

    List<Message> toCompress = all.subList(0, all.size() - 10);  // 保留最近 10 条
    String summary = chatClient.prompt()
            .system("把下面的对话压缩成一段简短摘要，保留关键事实、用户偏好、未完成的事项。")
            .user(toMessagesText(toCompress))
            .call()
            .content();

    memory.clear(conversationId);
    memory.add(conversationId, new SystemMessage("【历史对话摘要】" + summary));
    memory.addAll(conversationId, all.subList(all.size() - 10, all.size()));
}
```

### 3、压缩策略对比

| 策略 | 优点 | 缺点 |
| --- | --- | --- |
| 滑动窗口 | 简单、快 | 丢信息 |
| 摘要压缩 | 保留关键信息 | 多一次模型调用，摘要也可能丢细节 |
| 关键信息抽取 | 结构化、精准 | 需要定义抽取什么 |
| 分层摘要 | 信息层次清晰 | 实现复杂 |

**"最近 N 条原文 + 早期摘要"是最实用的组合**：近处保留细节，远处保留要点。

### 4、压缩的时机

不要每次都压缩，太费。一般是**接近窗口上限时**才触发：

```text
消息数 < 20        → 不动
消息数 20 ~ 40     → 压缩早期消息
消息数 > 40        → 更激进的压缩
```

## 四、用户偏好与长期记忆存储

长期记忆要解决三个问题：**存什么、怎么存、怎么取。**

### 1、存什么

不是所有信息都值得长期存。通常存这几类：

- **偏好**：喜欢靠窗、不吃辣、常用支付方式。
- **画像**：会员等级、所在城市、职业。
- **事实**：上次咨询的问题、已购买的产品。
- **习惯**：常问的问题类型、常用的地址。

**关键是要"提取"出来，而不是把整段对话存下去。** 从对话里抽出结构化的偏好：

```java
public record UserPreference(
        String userId,
        String key,        // "seat_preference"
        String value,      // "window"
        String source,     // 来自哪次对话
        Instant updatedAt
) {}
```

### 2、怎么存

长期记忆的存储，按检索方式分两种：

**（1）结构化存储（MySQL / Redis）**

适合明确的键值型记忆：`seat_preference = window`。查询快、更新简单。

**（2）向量存储**

适合模糊的、语义化的记忆：把"用户上次说想找个人少安静的地方"存成向量，需要时按语义检索。

```java
// 存长期记忆
longTermMemoryStore.save(userId, memoryText);

// 按语义检索
List<Memory> relevant = longTermMemoryStore.search(userId, currentQuestion, 5);
```

### 3、什么时候写

长期记忆的写入，一般有两种时机：

- **实时提取**：每轮对话后，让模型判断"有没有值得记的信息"，有就抽取存入。
- **离线整理**：会话结束后，批量整理成记忆。

实时提取响应快，但每次都要多调一次模型；离线整理省调用，但记忆有延迟。**通常用"实时提取 + 定期整理"结合。**

```java
// 会话结束后提取记忆（伪代码）
List<Memory> extracted = memoryExtractor.extract(conversation);
for (Memory m : extracted) {
    if (m.importance() >= 0.6) {   // 只存重要的
        longTermMemoryStore.save(userId, m);
    }
}
```

### 4、什么时候读

读长期记忆通常是**每次组装上下文时**：根据当前问题，检索相关的长期记忆，一起放进去。

```java
List<Memory> memories = longTermMemoryStore.search(userId, question, 5);
String memoryContext = memories.stream()
        .map(Memory::content)
        .collect(Collectors.joining("\n"));
```

## 五、状态持久化与恢复

Agent 跑长任务时，可能中途挂掉、重启、或者用户过一会儿再回来。**状态必须能持久化，才能恢复。**

### 1、存什么

```java
public record PersistedAgentState(
        String taskId,
        String userId,
        String goal,
        Map<String, Object> slots,
        List<String> completedSteps,
        String currentStep,
        String status,          // RUNNING / WAITING_USER / DONE / FAILED
        List<Message> messages,
        Instant updatedAt
) {}
```

### 2、存到哪

- **Redis**：适合正在进行的任务状态，读写快，可以设 TTL 自动过期。
- **MySQL**：适合需要长期保存、要审计的任务，可靠。
- **两者结合**：热数据放 Redis，定期归档到 MySQL。

```java
// 用 Redis 存进行中的任务状态
redisTemplate.opsForValue().set(
        "agent:state:" + taskId,
        objectMapper.writeValueAsString(state),
        Duration.ofHours(24)   // 24 小时后自动过期
);
```

### 3、怎么恢复

恢复的核心是：**重新加载 State，从中断的地方继续。**

```java
public AgentState resume(String taskId) {
    String json = redisTemplate.opsForValue().get("agent:state:" + taskId);
    if (json == null) {
        throw new TaskNotFoundException(taskId);
    }
    AgentState state = objectMapper.readValue(json, AgentState.class);

    // 根据状态决定从哪继续
    switch (state.status()) {
        case "WAITING_USER":
            // 等用户输入，不继续跑
            return state;
        case "RUNNING":
            // 从中断的步骤继续
            return continueFrom(state, state.currentStep());
        default:
            return state;
    }
}
```

**恢复能力是 Agent 和"一次性脚本"的重要区别。** 生产环境的任务可能跑几分钟甚至几小时，中间任何环节都可能出问题，没有恢复能力就不敢上线。

## 六、多轮任务中的中间结果管理

长任务里会产生大量中间结果：查到的数据、生成的草稿、计算的结果。这些怎么管？

### 1、别都塞进上下文

中间结果如果全塞进上下文，很快就把窗口撑爆了。做法是**分层**：

```text
┌──────────────────────────────────────────┐
│ 上下文（模型看得到的）                     │
│  - 目标                                    │
│  - 关键中间结论（摘要过的）                │
│  - 当前步骤需要的数据                      │
└──────────────────────────────────────────┘
              ▲ 按需取用
┌──────────────────────────────────────────┐
│ 外部存储（模型看不到，需要时才取）         │
│  - 完整的查询结果                          │
│  - 中间生成的文档                          │
│  - 大体积数据                              │
└──────────────────────────────────────────┘
```

**核心思路：上下文里只放"结论"，完整数据放外部，需要时通过工具或检索取回。**

### 2、用引用代替内容

一个很实用的技巧：**上下文里存的是"引用"，不是"内容"**。

```text
❌ 把 200 条订单全塞进上下文
✅ 上下文里写："订单查询结果已保存，共 200 条，ID: result_abc123，
   需要时可用 getResult('result_abc123') 取回"
```

模型需要细节时，再调工具取。这样上下文保持精简，信息又不丢。

### 3、中间结果的清理

任务结束后要清理中间结果，否则存储会无限膨胀：

```java
// 任务完成后，标记中间结果可回收
resultStore.markCompleted(taskId);
// 定时任务清理超过 7 天的中间结果
```

## 七、Redis、关系数据库与向量数据库的选型

三种存储各有各的定位，别指望一种存所有。

| 存储 | 适合存 | 优点 | 缺点 |
| --- | --- | --- | --- |
| Redis | 会话上下文、进行中状态、缓存 | 快、有 TTL、支持原子操作 | 容量有限、持久化弱 |
| MySQL | 任务记录、长期记忆、审计 | 可靠、能查询、事务 | 慢一些、无向量能力 |
| 向量库 | 语义记忆、知识片段 | 语义检索强 | 不适合精确查询和更新 |

### 1、典型组合

```text
会话进行中    → Redis（带 TTL，自动过期）
任务持久记录  → MySQL（可靠，可审计）
语义记忆      → 向量库（按语义检索）
用户偏好      → MySQL（结构化键值，查询快）
```

### 2、一个常见错误

**别把长期记忆全塞进向量库。** 向量库擅长"语义相似"，但用户偏好这种"精确键值"（`seat_preference = window`），用 MySQL 查又快又准。**能用结构化查询的，就别用向量检索。**

判断标准很简单：

- 问题是"找出语义相似的" → 向量库。
- 问题是"找出 key = x 的" → MySQL / Redis。

## 八、记忆检索、更新与过期策略

### 1、检索

长期记忆的检索，要结合当前问题：

```java
// 用当前问题检索相关记忆
List<Memory> relevant = memoryStore.search(userId, currentQuestion, topK = 5);
```

如果记忆很多，还要考虑**排序和筛选**：

- 相关性（和当前问题的语义距离）。
- 时间新近度（越新的越重要）。
- 重要程度（用户明确说的 > 推断出来的）。

一个简单的综合打分：

```text
score = 0.6 * 相关性 + 0.2 * 新近度 + 0.2 * 重要度
```

### 2、更新

记忆会变。用户之前说"喜欢靠窗"，后来说"还是靠过道吧"。

处理原则：

- **同 key 覆盖**：`seat_preference` 这类明确偏好，新的覆盖旧的。
- **冲突标记**：语义记忆冲突时，保留新的并标注时间，让模型自己判断。
- **来源可追溯**：每条记忆记下来自哪次对话，方便核对。

```java
// 偏好类：直接覆盖
preferenceStore.upsert(userId, "seat_preference", "aisle");

// 语义类：保留历史，标注时间
memoryStore.save(userId, new Memory(text, Instant.now(), source));
```

### 3、过期

不是所有记忆都永久有效。

- **时效性记忆**：比如"这周在出差"，过期就该失效。用 TTL。
- **偏好类记忆**：相对长期有效，但也要能手动删除。
- **一次性信息**：任务完成后就删。

```java
// Redis 设置 TTL
redisTemplate.expire("memory:" + userId + ":" + key, Duration.ofDays(30));
```

## 九、多用户之间的状态隔离

这是最容易出事故的地方。**A 用户的记忆串到 B 用户，就是数据泄露。**

### 1、隔离的层次

```text
① 存储隔离：不同用户的数据分开存
② 查询隔离：所有查询强制带 userId 条件
③ 上下文隔离：组装上下文时只取当前用户的记忆
④ 向量库隔离：向量检索必须按 userId 过滤
```

### 2、代码上怎么保证

**关键原则：userId 从认证信息里取，绝不能从模型输出或用户输入里取。**

```java
@Tool(description = "查询我的订单")
public String queryMyOrder(String orderId, ToolContext ctx) {
    // ✅ userId 来自认证上下文
    String userId = ctx.currentUserId();

    Order order = orderService.get(orderId);
    if (!order.getUserId().equals(userId)) {
        return "无权访问该订单。";
    }
    return toJson(order);
}
```

会话 ID 也要带上用户维度：

```java
String conversationId = userId + ":" + sessionId;
```

**向量库尤其要注意**：如果不同用户的文档放在同一个 collection 里，检索时必须带 `userId` 过滤条件，否则会检索到别人的内容。

```java
SearchRequest.builder()
        .query(q)
        .filterExpression("userId == '" + userId + "'")  // 强制隔离
        .build();
```

### 3、测试要覆盖隔离

隔离问题往往在开发环境测不出来（因为只有一个用户）。**上线前一定要专门测多用户场景**：用两个账号交叉操作，确认彼此看不到对方的数据。

## 十、记忆污染、过期信息与隐私风险

### 1、记忆污染

如果记忆提取环节把关不严，可能把**错误信息**存进去，之后一直被影响。

```text
用户开玩笑：我是世界首富
Agent 提取记忆：用户资产状况 = 世界首富   ← 污染了
```

对策：

- **只提取可信、稳定的信息**，用户的玩笑、假设、引用别当事实。
- **区分来源**：用户明确说的、模型推断的，标清楚。
- **允许修正**：用户说"记错了，我其实不是"，要能更新。

### 2、过期信息

记忆越老越可能不准。对策：

- 给记忆加**时间戳**，检索时考虑新近度。
- 关键记忆**定期复核**，或者在使用时提示"这是 xx 时间记录的信息"。
- 明确的时效信息（出差、临时地址）用 **TTL 自动过期**。

### 3、隐私风险

记忆里可能存了敏感信息，风险包括：

- **越权访问**：隔离没做好，串数据。
- **过度存储**：存了不该存的敏感信息（身份证、银行卡）。
- **无法删除**：用户要求删除，却删不干净。

对策：

- **最小化存储**：不存用不到的敏感信息，能脱敏就脱敏。
- **支持删除**：提供"清除我的记忆"的能力，删得彻底（包括向量库、缓存、归档）。
- **加密存储**：敏感记忆加密。
- **审计**：谁在什么时候读写了哪条记忆，要有记录。

```java
// 提供用户自主删除记忆的能力
public void clearUserMemory(String userId) {
    preferenceStore.deleteByUser(userId);
    memoryStore.deleteByUser(userId);
    vectorStore.deleteByFilter("userId == '" + userId + "'");
    redisTemplate.delete("agent:state:*:" + userId);
}
```

**记忆是把双刃剑**：它让 Agent 更懂用户，也让隐私风险变高。设计时必须把"能存什么、存多久、谁能看、怎么删"想清楚。

## 十一、实践验证：让记忆活过多轮对话与重启

前面讲了短期记忆、长期记忆和持久化。这一节动手把"多轮记忆"跑起来，并验证一个关键问题：**内存记忆一重启就丢，怎么换成持久化存储。**

### 1、先看默认的内存记忆

Spring AI 的记忆由两个接口分工：

- `ChatMemory`：记忆的**策略**（保留多少条、怎么压缩）。
- `ChatMemoryRepository`：记忆的**存储**（存在哪里）。

默认实现是内存版：

```java
ChatMemory chatMemory = MessageWindowChatMemory.builder()
        .chatMemoryRepository(new InMemoryChatMemoryRepository())  // 存在内存
        .maxMessages(20)                                           // 滑动窗口：只留最近 20 条
        .build();

ChatClient chatClient = ChatClient.builder(chatModel)
        .defaultAdvisors(MessageChatMemoryAdvisor.builder(chatMemory).build())
        .build();
```

调用时用 `CONVERSATION_ID` 指定会话：

```java
String answer = chatClient.prompt()
        .user(message)
        .advisors(a -> a.param(ChatMemory.CONVERSATION_ID, chatId))
        .call()
        .content();
```

这就是前面讲的"短期记忆"：**存在内存、跟着会话走、进程一停就没了。**

### 2、验证会话隔离

用两个不同的 `chatId` 交叉提问，验证记忆是隔离的：

```bash
# 会话 A 说自己叫小明
curl "http://localhost:8080/chat/memory?message=我叫小明&chatId=A"
# 会话 A 追问，能答出来
curl "http://localhost:8080/chat/memory?message=我叫什么？&chatId=A"
# 会话 B 追问，答不出来（记忆隔离）
curl "http://localhost:8080/chat/memory?message=我叫什么？&chatId=B"
```

会话 A 能答出"小明"，会话 B 答不出——**说明 `CONVERSATION_ID` 确实把两个会话的记忆隔开了**。

![image-20261011105000001](assets/image-20261011105000001.png)

### 3、再看持久化：把记忆换成数据库

内存版的问题很直接：**服务重启，所有会话记忆全丢**。解决办法是把 `ChatMemoryRepository` 换成持久化实现。

一个成熟的做法是用 JDBC 存到关系数据库（参考 Lynxe 项目的实现）：

```java
@Bean
public ChatMemory chatMemory(JdbcChatMemoryRepository repository) {
    return MessageWindowChatMemory.builder()
            .chatMemoryRepository(repository)   // 换成 JDBC 存储
            .maxMessages(20)
            .build();
}
```

对应的表结构大致是"会话 ID + 消息内容 + 时间"：

```sql
CREATE TABLE chat_memory (
    conversation_id VARCHAR(128) NOT NULL,
    message_type    VARCHAR(32)  NOT NULL,   -- USER / ASSISTANT / SYSTEM
    content         TEXT         NOT NULL,
    created_at      DATETIME     NOT NULL,
    INDEX idx_conversation (conversation_id)
);
```

这样重启服务后，用同一个 `chatId` 继续问，Agent 依然记得之前说过什么。

### 4、长期记忆：从对话里抽偏好

短期记忆管"这次聊得下去"，长期记忆管"每次都记得你"。长期记忆要**抽取成结构化信息**，而不是整段存对话：

```java
// 会话结束后，让模型从对话里抽取值得长期记住的信息
List<Memory> extracted = memoryExtractor.extract(conversation);
for (Memory m : extracted) {
    if (m.importance() >= 0.6) {              // 只存重要的
        longTermMemoryStore.save(userId, m);  // 存进数据库或向量库
    }
}
```

### 5、这一步验证了什么

- **短期记忆 = 滑动窗口 + 会话 ID**：`MessageWindowChatMemory` 保留最近 N 条，`CONVERSATION_ID` 决定归属。
- **会话隔离靠 `CONVERSATION_ID`**：换个 ID 就"失忆"，这就是前面讲的**多用户隔离**——生产环境里这个 ID 必须带上 `userId`。
- **内存存储不可用于生产**：`InMemoryChatMemoryRepository` 重启即丢，必须换成 Redis / JDBC / 向量库实现。
- **短期与长期要分开存**：短期放 Redis（带 TTL），长期放数据库或向量库——对应"存储选型"和"Redis、关系数据库与向量数据库的选型"两节。

> 这里演示的是多轮记忆和持久化。更进阶的话题——上下文压缩（摘要替代丢弃）、记忆过期、隐私与"清除我的记忆"——是前面几节的内容，思路都建立在这条链路上。

## 小结

这一篇把 Agent 的记忆和状态讲清楚了：

- **对话历史是给模型看的消息列表，Agent State 是给程序用的结构化状态**，后者远不止前者。
- **短期记忆**管当前会话，**长期记忆**管跨会话，两者配合。
- 上下文压缩用**"最近原文 + 早期摘要"**，接近窗口上限时才触发。
- 长期记忆要**抽取成结构化信息**，而不是整段存。
- **状态要持久化**，才能在中断后恢复；Redis 存热数据，MySQL 存归档。
- 中间结果**别全塞上下文**，用"引用 + 外部存储"。
- 存储选型看查询方式：**语义相似用向量库，精确键值用 MySQL/Redis。**
- 记忆要能**更新和过期**，时效信息用 TTL。
- **多用户隔离是红线**，`userId` 只能来自认证信息，向量检索必须过滤。
- 警惕**记忆污染、过期信息和隐私风险**，设计时就想好怎么删。

到这里，Agent 已经能记事了。但当任务变复杂、步骤变多，光靠"循环"就不够控了——我们需要能编排、能中断、能恢复、能观察的执行流程。下一篇：《Agent 工作流与状态图》。
