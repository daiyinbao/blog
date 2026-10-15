+++
title = "大模型调用与上下文工程"
date = 2026-10-11T00:00:00+08:00
weight = 11
tags = ["Agent", "大模型", "Prompt", "上下文工程", "Spring AI"]
summary = "Agent 系列（二）：讲清大模型 API 的消息结构、Prompt 设计、结构化输出、Token 与上下文管理，以及流式、超时、重试、限流和降级。"

+++

上一篇我们把 Agent 拆成了"模型、指令、工具、状态、循环"五部分。这一篇从最底层的"模型"开始，把它怎么接进来讲清楚。

Agent 的所有智能，最终都落在一次次的模型调用上。调用本身不难——发一段文本，收一段文本。难的是**每一次调用时，到底该把哪些信息放进去**。这就是"上下文工程"。上下文给得好，模型判断就准；上下文给得乱，再强的模型也会犯迷糊。

这一篇是后面所有内容的地基。工具怎么调、记忆怎么存、知识库怎么接，说到底都是在回答同一个问题：**怎么把正确的信息，放进这一次调用的上下文里。**

## 一、大模型 API 与消息结构

### 1、一次调用的最小结构

最早的大模型接口是"补全式"的：给一段文本，模型接着往下写。现在主流的是"对话式"接口：给一串消息，模型生成下一条消息。

用 Spring AI 写一次最简单的调用：

```java
ChatClient chatClient = ChatClient.builder(chatModel).build();

String answer = chatClient.prompt()
        .user("用一句话解释什么是 Agent")
        .call()
        .content();
```

看起来就是"发一句话、收一句话"，但接口内部实际传过去的，是一组**有角色的消息**。上面这段代码，展开成真正发给模型的内容大概是这样：

```json
[
  { "role": "user", "content": "用一句话解释什么是 Agent" }
]
```

理解这一点很关键：**模型看到的不是"一段对话文本"，而是一个消息列表。** 上下文工程，本质上就是在决定这个列表里放什么、按什么顺序放。

### 2、System、User、Assistant、Tool 四种消息

主流模型 API 里的消息，基本都归为四种角色。

| 角色 | 作用 | 谁来写 |
| --- | --- | --- |
| `system` | 给模型定角色、定规则、定约束 | 开发者 |
| `user` | 用户的输入 | 用户 |
| `assistant` | 模型之前的回复（含工具调用请求） | 模型 |
| `tool` | 工具执行的结果 | 程序 |

#### 2.1、System 消息

System 消息是"总规则"，优先级最高，通常放在列表最前面，整个会话保持不变。

```java
String systemPrompt = """
        你是一个订单助手。
        你只能查询当前用户自己的订单，不能查询其他用户的数据。
        如果用户的问题和订单无关，礼貌地说明你只能处理订单问题。
        """;

chatClient.prompt()
        .system(systemPrompt)
        .user("帮我查下订单 20261011001")
        .call()
        .content();
```

System 里适合放：角色定位、行为约束、输出格式要求。**它是最省事的控制手段**，改一句规则比改一堆代码快得多。

#### 2.2、User 消息

User 消息就是用户的输入。多轮对话里，会有多条 User 消息，和 Assistant 消息交替出现。

#### 2.3、Assistant 消息

Assistant 消息是模型之前的输出。它有两个用途：

- 在历史里，让模型知道自己之前说过什么。
- 当模型决定调用工具时，它产出的不是文本，而是一条**带工具调用请求的 Assistant 消息**。

```json
{
  "role": "assistant",
  "content": null,
  "tool_calls": [
    {
      "id": "call_abc123",
      "type": "function",
      "function": { "name": "queryOrder", "arguments": "{\"orderId\":\"20261011001\"}" }
    }
  ]
}
```

注意这里的 `tool_calls`：模型没有直接回答，而是**"说"它想调用 `queryOrder`**。真正去执行的，是外面的程序。

#### 2.4、Tool 消息

程序执行完工具，把结果包成 Tool 消息塞回上下文，并带上对应的 `tool_call_id`：

```json
{
  "role": "tool",
  "tool_call_id": "call_abc123",
  "content": "{\"status\":\"运输中\",\"location\":\"杭州转运中心\"}"
}
```

`tool_call_id` 是**把"这次请求"和"这次结果"配对上**的关键。一次可能有多个工具调用，模型靠这个 id 知道哪份结果对应哪个请求。

把四者串起来，一次带工具的调用完整长这样：

```text
system   : 你是订单助手，只能查当前用户的订单
user     : 帮我查下订单 20261011001
assistant: (tool_calls: queryOrder{orderId:20261011001})
tool     : {"status":"运输中","location":"杭州转运中心"}
assistant: 你的订单已到达杭州转运中心，预计明天下午送达。
```

**这一串消息列表，就是 Agent 每一轮真正"看"到的东西。** 后面讲的记忆、RAG、工具，全都是在往这个列表里加料。

## 二、Prompt 设计与结构化输出

### 1、System Prompt 怎么写

写 System Prompt 有个很实用的原则：**具体、可执行、给例子**。

对比一下两种写法：

```text
❌ 模糊：你要专业、友好地回答用户问题。

✅ 具体：你是电商客服。回答要求：
        1. 先直接给结论，再补充说明，不要绕弯子；
        2. 不确定的信息不要编，直接说"我需要再核实"；
        3. 涉及退款金额时，必须提示"最终金额以系统结算为准"。
```

第二种把"专业友好"这种没法执行的要求，翻译成了模型能照做的具体规则。

几个常见技巧：

- **给角色和边界**：你是谁、你能做什么、你不能做什么。
- **给输出格式**：要求分点、要求先结论后原因、要求用某种结构。
- **给示例**：一两个"输入→输出"的例子，比十条抽象规则都管用。
- **用分隔符**：把用户输入用 `"""` 或 XML 标签包起来，避免和指令混在一起（这也能降低提示词注入的风险，后面安全篇会讲）。

```java
String systemPrompt = """
        你是订单助手。根据下面提供的订单数据回答用户问题。

        规则：
        1. 只依据 <order> 标签内的数据回答，数据里没有的不要编造。
        2. 回答要简洁，先给结论。
        3. 无法从数据中得出答案时，明确说"当前信息无法判断"。

        <order>
        %s
        </order>
        """.formatted(orderJson);
```

### 2、结构化输出

很多时候我们要的不是一段自然语言，而是**一个能直接用的对象**。比如从用户的话里抽出下单意图：

```text
用户：帮我买两杯拿铁，送到公司，越快越好
```

我们希望拿到的是：

```java
public record OrderIntent(
        String product,
        int quantity,
        String address,
        String urgency) {}
```

Spring AI 提供了 `.entity()` 直接做这件事：

```java
OrderIntent intent = chatClient.prompt()
        .system("从用户的话里提取下单信息，字段缺失就留空。")
        .user("帮我买两杯拿铁，送到公司，越快越好")
        .call()
        .entity(OrderIntent.class);
```

它的原理是：Spring AI 自动生成一份 JSON Schema，要求模型按这个结构输出，再把返回的 JSON 反序列化成对象。如果模型输出的格式不对，还会自动重试。

**结构化输出是 Agent 工程里极其重要的一环。** 因为模型要驱动程序，它的输出就必须是程序能解析的——自由文本没法直接变成代码里的分支和参数。

## 三、JSON Schema 与参数校验

`.entity()` 背后靠的是 JSON Schema。它的作用是：**用一份明确的"格式说明"，约束模型必须按结构输出。**

比如上面那个 `OrderIntent`，生成的 Schema 大致是：

```json
{
  "type": "object",
  "properties": {
    "product":  { "type": "string",  "description": "商品名称" },
    "quantity": { "type": "integer", "description": "数量" },
    "address":  { "type": "string",  "description": "配送地址" },
    "urgency":  { "type": "string",  "description": "紧急程度" }
  },
  "required": ["product", "quantity"]
}
```

Schema 能约束的东西：

- 有哪些字段（properties）。
- 每个字段是什么类型（string、integer、boolean、array、object）。
- 哪些字段必填（required）。
- 每个字段的含义（description）——**这一项对模型理解影响最大**，描述写得越清楚，模型填得越准。

但要注意：**Schema 只保证"结构对"，不保证"内容对"。** 模型可能给你 `quantity: -3`，或者 `address` 填成一段废话。所以拿到结果后，程序里必须再校验一次：

```java
if (intent.quantity() <= 0 || intent.quantity() > 100) {
    throw new IllegalArgumentException("数量不合法：" + intent.quantity());
}
if (!allowedCities.contains(extractCity(intent.address()))) {
    throw new IllegalArgumentException("暂不支持该配送区域");
}
```

用 Jakarta Validation 会更省事：

```java
public record OrderIntent(
        @NotBlank String product,
        @Min(1) @Max(100) int quantity,
        @NotBlank String address,
        String urgency) {}
```

再配合 `@Valid` 触发校验，把"模型输出"当成不可信的外部输入来对待。

> 一条重要原则：**凡是模型生成的内容，进入业务逻辑前都要校验。** 模型不是可信数据源，它的输出和用户输入一样需要防御。

## 四、Function Calling / Tool Calling

这里先引出概念，具体实现放在下一篇。

前面看到，模型可以在 Assistant 消息里返回 `tool_calls`，说"我想调用某个工具"。这就是 Function Calling（现在更多叫 Tool Calling）。

它的流程是：

```text
1. 开发者把"有哪些工具、每个工具要什么参数"告诉模型
2. 模型判断需要工具时，返回 tool_calls（工具名 + 参数 JSON）
3. 程序执行工具，把结果包成 tool 消息塞回去
4. 模型看着结果，继续决策
```

关键在于：**模型只负责"决定调什么、参数填什么"，实际执行永远是程序做的。** 模型本身没有执行能力，它只是"提出请求"。

这一点想清楚了，工具的安全边界就清楚了：**能不能调、允不允许调、参数合不合法，全都是程序说了算，不能让模型说了算。**

## 五、Token、上下文窗口与截断

### 1、Token 是什么

模型不是按"字"处理文本的，而是按 **Token**。一个 Token 大约对应：

- 英文：约 0.75 个单词，或 4 个字符。
- 中文：大约 1 到 2 个汉字（取决于分词器）。

调用模型时，`输入 Token + 输出 Token` 一起计费，也一起占用上下文窗口。

### 2、上下文窗口

上下文窗口是模型一次能"看到"的 Token 上限，比如 8K、32K、128K。**System + 历史 + 本轮输入 + 工具结果，全都算在里面。**

Agent 场景特别容易把窗口撑爆，因为：

- 多轮对话，历史不断累积。
- 工具返回的结果可能很长（比如一次查了 200 条订单）。
- RAG 检索回来的文档片段很占地方。

### 3、超了怎么办

一旦接近或超过窗口，就必须做取舍。常见手段：

- **截断**：丢掉最早的历史。简单，但可能丢关键信息。
- **摘要**：把早期历史压缩成一段摘要。比直接丢更保信息。
- **检索**：历史不全放，需要时再查出来。这是记忆机制的核心思路。

```text
窗口预算示意（假设 32K）：

┌───────────────────────────────────────────────┐
│ System 指令        │  约 500 token             │
├────────────────────┼──────────────────────────┤
│ 历史消息           │  动态，需要压缩/截断      │
├────────────────────┼──────────────────────────┤
│ 工具结果           │  动态，可能要裁剪         │
├────────────────────┼──────────────────────────┤
│ 预留输出空间       │  至少留 2K                │
└────────────────────┴──────────────────────────┘
```

**工程上一定要给上下文做"预算管理"**：哪部分固定占多少、哪部分可以压缩、永远给输出留够空间。这个话题在《Agent 状态与记忆机制》里会展开。

## 六、对话历史管理

### 1、为什么要管

如果每次调用都把全部历史带上，会有三个问题：

- **贵**：Token 数随轮数线性增长。
- **慢**：输入越长，响应越慢。
- **乱**：太久远的信息可能反而干扰当前判断。

### 2、Spring AI 的对话记忆

Spring AI 用 `ChatMemory` 来管历史：

```java
ChatMemory chatMemory = MessageWindowChatMemory.builder()
        .chatMemoryRepository(new InMemoryChatMemoryRepository())
        .maxMessages(20)
        .build();

ChatClient chatClient = ChatClient.builder(chatModel)
        .defaultAdvisors(MessageChatMemoryAdvisor.builder(chatMemory).build())
        .build();

String answer = chatClient.prompt()
        .user("我刚才说的那个订单，现在到哪了？")
        .advisors(a -> a.param(ChatMemory.CONVERSATION_ID, "user-1001"))
        .call()
        .content();
```

这里 `MessageWindowChatMemory` 用的是**滑动窗口**：只保留最近 N 条消息，超出的自动丢弃。`CONVERSATION_ID` 用来区分不同用户/会话——**不同会话的记忆必须隔离**，否则 A 用户的历史会串到 B 用户。

### 3、滑动窗口的问题

滑动窗口简单，但有个硬伤：**它会硬生生丢掉最早的信息**。

比如用户在第一轮说"我住在杭州"，聊了二十轮后问"帮我推荐个附近的餐厅"，此时"杭州"这条信息可能已经被挤出去了。

解决办法是**用摘要替代丢弃**：把超出的历史交给模型压缩成一段话，再放回去。

```java
// 伪代码：超出窗口的部分，先摘要再放回
String summary = summarize(oldMessages);
chatMemory.add(conversationId, new SystemMessage("之前对话摘要：" + summary));
```

"摘要 + 保留最近若干条原文"是目前最常用的组合，兼顾了信息量和成本。

## 七、模型选择、温度参数与输出约束

### 1、怎么选模型

选模型通常在这几个维度上权衡：

| 维度 | 说明 |
| --- | --- |
| 能力 | 复杂推理、代码、多语言，不同模型强弱不同 |
| 成本 | 按 Token 计费，差价可能几十倍 |
| 延迟 | 直接影响用户体验 |
| 上下文窗口 | 决定能塞多少信息 |
| 是否支持工具调用 | Agent 的硬性要求 |
| 是否支持结构化输出 | 影响解析的稳定性 |

一个实用的思路是**分层**：主流程用强模型保证质量，简单的分类、抽取、改写用小模型降本。

```java
// 复杂决策用强模型
ChatClient strongClient = ChatClient.builder(strongModel).build();
// 简单改写用小模型
ChatClient cheapClient = ChatClient.builder(cheapModel).build();
```

### 2、温度参数

温度（temperature）控制输出的随机性：

- **低温度（0 ~ 0.3）**：输出稳定、可复现，适合工具调用、结构化输出、事实问答。
- **高温度（0.7 ~ 1.0）**：输出多样、有创造性，适合文案、头脑风暴。

```java
ChatOptions options = OpenAiChatOptions.builder()
        .temperature(0.0)   // Agent 做决策时，稳定优先
        .build();

chatClient.prompt()
        .user("判断这句话是查询订单还是投诉：...")
        .options(options)
        .call()
        .content();
```

**Agent 里大量调用都该用低温度。** 因为我们要的是"稳定地做对决策"，不是"有创意"。需要创意的地方（比如生成回复文案），才调高。

### 3、输出约束

除了温度，还能用这些手段约束输出：

- **最大 Token 数**：防止模型长篇大论，控制成本。
- **停止词**：遇到特定字符串就停。
- **结构化输出 / JSON Schema**：强制格式。
- **System Prompt 里的格式要求**：比如"只输出 JSON，不要任何解释"。

## 八、流式输出与异常处理

### 1、流式输出

模型生成是逐字进行的。非流式要等全部生成完才返回，用户会觉得卡；流式则边生成边返回，体验好得多。

```java
Flux<String> stream = chatClient.prompt()
        .user("介绍一下 RAG")
        .stream()
        .content();

stream.subscribe(chunk -> {
    // 每收到一小段就推给前端（SSE / WebSocket）
    sseEmitter.send(chunk);
});
```

Spring AI 的流式接口返回 `Flux<String>`，可以直接对接 WebFlux 的 SSE。

需要注意：**流式下拿不到完整的结构化对象**。所以流式一般只用在"给用户看最终回复"这一步；需要工具调用、需要解析结构的地方，还是用非流式。

### 2、异常处理

调模型会失败，而且是经常失败。常见的异常：

- **超时**：模型响应慢，或网络问题。
- **限流（429）**：请求太频繁，超过配额。
- **服务不可用（5xx）**：上游临时故障。
- **内容被拒**：触发了安全策略。
- **输出无法解析**：结构化输出格式不对。

处理原则是**分类对待**：

```java
try {
    return chatClient.prompt().user(q).call().content();
} catch (ResourceAccessException e) {
    // 超时/网络：可以重试
    return retryWithBackoff(q);
} catch (WebClientResponseException.TooManyRequests e) {
    // 限流：退避后重试，或切换到备用模型
    return fallbackModel(q);
} catch (Exception e) {
    // 其他：记录并降级
    log.error("模型调用失败", e);
    return "服务暂时不可用，请稍后再试";
}
```

## 九、超时、重试、限流与降级

这四件事是生产环境的标配，缺一个都可能被线上流量打垮。

### 1、超时

必须设超时。不设的话，一个卡住的请求会一直占着线程。

```java
WebClient.builder()
    .clientConnector(new ReactorClientHttpConnector(
        HttpClient.create()
            .responseTimeout(Duration.ofSeconds(30))))
    .build();
```

超时值要分场景：给用户看的对话可以短一点（10~15 秒），后台批处理可以长一点。

### 2、重试

不是所有失败都该重试：

- **该重试**：超时、限流、5xx——这些是临时的。
- **不该重试**：参数错误、内容被拒——重试多少次都一样。

重试要**带退避**，不能立刻重打：

```java
Retry.backoff(3, Duration.ofMillis(500))
     .filter(e -> e instanceof ResourceAccessException
               || e instanceof WebClientResponseException.TooManyRequests);
```

### 3、限流

限流有两层：

- **客户端限流**：自己控制发出去的速率，别把上游打爆（用 Resilience4j 的 RateLimiter 或信号量）。
- **服务端配额**：注意自己的账号 QPS 上限，超了会被拒。

### 4、降级

降级是最后的兜底：**主模型挂了，切到备用模型；都挂了，给用户一个体面的回复，而不是报错。**

```text
请求 → 主模型 ──失败──► 备用模型 ──失败──► 静态兜底回复
         │                  │
         └──成功───────────┴──成功
```

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

## 十、实践验证：把模型调用、流式与记忆跑一遍

这一节用 Spring AI 的 `ChatModel` 和 `ChatClient` 把前面的消息结构、流式输出、对话记忆都跑一遍，代码来自 `Demo-SpringAi`。

### 1、ChatModel 与 ChatClient

`ChatModel` 是最底层的接口，`ChatClient` 是对它的封装。两者调用同一个模型：

```java
@RestController
public class ChatController {

    private final ChatModel chatModel;
    private final ChatClient chatClient;

    public ChatController(ChatModel chatModel,
                          ChatClient.Builder chatClientBuilder,
                          ToolCallbackProvider toolCallbackProvider) {
        this.chatModel = chatModel;
        // 把工具清单挂到 ChatClient 上
        this.chatClient = chatClientBuilder
                .defaultToolCallbacks(toolCallbackProvider)
                .build();
    }

    /** 用 ChatModel 调用：手动组装 Prompt */
    @GetMapping("/simple/chat")
    public String simpleChat() {
        UserMessage userMessage = new UserMessage("在咖啡馆里，想要杯星巴克");
        Prompt prompt = new Prompt(userMessage);          // 一条 user 消息
        ChatResponse chatResponse = chatModel.call(prompt);
        return chatResponse.getResult().getOutput().getText();
    }

    /** 用 ChatClient 调用：链式 API */
    @GetMapping("/simple/chatclient")
    public String simpleChatByChatClient() {
        return this.chatClient
                .prompt("在咖啡馆里，想要杯星巴克")   // 构建 prompt
                .call()                              // 发送到大模型
                .content();                          // 取文本结果
    }
}
```

对比着看就明白第一篇讲的"消息结构"了：

- `ChatModel` 这层，我们**显式**构造了 `UserMessage` 和 `Prompt`，能直接看到"发过去的是一条 user 消息"。
- `ChatClient` 这层，`.prompt("...")` 只是把这个过程包了一层，**底层还是同样的消息列表**。

`ChatModel` 是 `ChatClient` 的基础，日常开发用 `ChatClient`，需要精细控制消息时才下沉到 `ChatModel`。

### 2、流式输出

把 `.call()` 换成 `.stream()`，返回值从 `String` 变成 `Flux<String>`：

```java
@GetMapping(value = "/chat/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
public Flux<String> streamChat() {
    return this.chatClient
            .prompt("在咖啡馆里，想要杯星巴克")
            .stream()     // 流式响应
            .content();   // 每个元素是一小段增量文本
}
```

`produces = MediaType.TEXT_EVENT_STREAM_VALUE` 让接口按 **SSE（Server-Sent Events）** 协议持续推送，前端就能一个字一个字地显示。

如果要自己控制 SSE 事件格式，可以用 `ServerSentEvent` 组装：

```java
return Flux.interval(Duration.ofSeconds(1))
        .map(seq -> ServerSentEvent.<String>builder()
                .event("message")
                .data("...")
                .id(String.valueOf(seq))
                .build());
```

SSE 的格式是 `event:` / `data:` / `id:` 三段，两个换行 `\n\n` 表示一个事件结束。

![image-20261011102000001](assets/image-20261011102000001.png)

### 3、对话记忆

多轮对话靠 Advisor 里的 `MessageChatMemoryAdvisor` 实现。关键是用一个 `chatId` 区分不同会话：

```java
@GetMapping(value = "/chat/memory", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
public Flux<String> chatMemory(@RequestParam String message,
                               @RequestParam String chatId) {
    return this.chatClient
            .prompt(message)
            .advisors(advisorSpec ->
                    // 用 chatId 标记这次对话属于哪个会话
                    advisorSpec.param(ChatMemory.CONVERSATION_ID, chatId))
            .stream()
            .content();
}
```

记忆的存储由 `ChatMemory` 和 `ChatMemoryRepository` 管：

- `MessageWindowChatMemory` 实现了 `ChatMemory`，是**滑动窗口**策略——只保留最近 N 条。
- `InMemoryChatMemoryRepository` 实现了 `ChatMemoryRepository`，把历史**存在内存**里。

在 `application.yml` 里把 Advisor 的日志打开，就能看到每次请求实际带了哪些历史消息：

```yaml
logging:
  level:
    org.springframework.ai.chat.client.advisor: debug
```

启动后，先用同一个 `chatId` 说一句带上下文的话，再追问：

```bash
# 第一句
curl "http://localhost:8080/chat/memory?message=我叫小明&chatId=u1"
# 追问（能答出"小明"）
curl "http://localhost:8080/chat/memory?message=我叫什么名字？&chatId=u1"
# 换个 chatId，就"失忆"了
curl "http://localhost:8080/chat/memory?message=我叫什么名字？&chatId=u2"
```

![image-20261011102000002](assets/image-20261011102000002.png)

![image-20261011102000003](assets/image-20261011102000003.png)

### 4、这一步验证了什么

- **消息结构是真的**：`ChatModel` 那层能直接看到 `UserMessage`、`Prompt`，印证了"模型看到的是一组带角色的消息"。
- **流式就是增量返回**：`.call()` → `.stream()`，返回类型从 `String` 变成 `Flux<String>`，对应"流式输出"一节。
- **记忆靠 Advisor + 会话 ID**：`CONVERSATION_ID` 决定历史归属，**不同 `chatId` 之间记忆隔离**——这正是后面《Agent 状态与记忆机制》要展开的话题。
- **内存存储的局限**：`InMemoryChatMemoryRepository` 一重启就丢，生产环境要换成 Redis 或数据库实现。

> 这里用的是 `InMemoryChatMemoryRepository`。真实项目要换成持久化实现，否则服务重启后所有会话记忆都会丢失。

## 小结

这一篇把"怎么接模型"讲透了：

- 模型看到的是**一组带角色的消息**（system、user、assistant、tool），不是一段文本。
- System Prompt 是最省事的控制手段，要**具体、可执行、给例子**。
- 结构化输出（JSON Schema + `.entity()`）让模型输出能被程序直接使用，但**结果必须校验**。
- Tool Calling 的本质是**模型提出请求，程序负责执行**。
- 上下文窗口是稀缺资源，要做**预算管理**，靠截断、摘要、检索来腾地方。
- 对话历史要管好，注意**会话隔离**和滑动窗口的丢信息问题。
- 模型要**分层选型**，Agent 决策场景**优先低温度**。
- 生产环境必须配齐**超时、重试、限流、降级**。

现在模型能稳定接进来、能结构化地吐结果了。但光会"想"还不够，Agent 要能"做"事。下一篇进入《Tool Calling 与工具系统》——把 Java 方法封装成 Agent 能调用的工具，让模型真正动起来。
