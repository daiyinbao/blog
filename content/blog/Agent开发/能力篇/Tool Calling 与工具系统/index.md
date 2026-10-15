+++
title = "Tool Calling 与工具系统"
date = 2026-10-11T00:00:00+08:00
weight = 12
tags = ["Agent", "Tool Calling", "Function Calling", "Spring AI", "工具"]
summary = "Agent 系列（三）：讲清 Tool Calling 的完整流程，从工具定义、注册路由、执行器设计到 Java 方法封装，以及超时、重试、权限和审计。"

+++

上一篇结尾留下了一句话：模型只会"提出请求"，真正干活的是程序。这一篇就把"干活"这件事讲透。

Tool Calling 是 Agent 从"会说"到"会做"的分水岭。没有工具，模型再聪明也只能吐文本；有了工具，它才能查库、调接口、写文件、发消息。可以说，**Agent 的能力边界，很大程度上就是它手上工具的能力边界。**

这一篇会从流程讲到代码，把 Spring AI 里工具是怎么定义、怎么注册、怎么执行、怎么反馈结果，以及怎么保证它不出事，都过一遍。

## 一、Tool Calling 的完整执行流程

先把一次工具调用的全过程拆开。

```text
┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│  1.模型   │     │ 2.程序    │     │ 3.执行器  │     │ 4.模型    │
│  决定调用 │────►│ 解析调用  │────►│ 真正执行  │────►│ 结合结果  │
│  某工具   │     │ 校验参数  │     │ 返回结果  │     │ 继续决策  │
└──────────┘     └──────────┘     └──────────┘     └──────────┘
```

展开成消息层面：

```text
① 请求时，把工具清单一起发给模型：
   tools: [ queryOrder, refundOrder, sendSms ]

② 模型返回工具调用请求：
   assistant.tool_calls = [
       { id: "call_1", name: "queryOrder",
         arguments: {"orderId": "20261011001"} }
   ]

③ 程序执行工具，得到结果

④ 把结果包成 tool 消息塞回上下文：
   { role: "tool", tool_call_id: "call_1",
     content: "{\"status\":\"运输中\"}" }

⑤ 模型看着结果，决定下一步：
   要么再调工具，要么给出最终答案
```

有几个细节值得注意：

- **工具清单是每次请求都带的**。模型靠这份清单知道"我能用哪些工具、每个要什么参数"。清单越大，占的 Token 越多，所以不是工具越多越好。
- **一次可能返回多个 `tool_calls`**，即模型想并行调多个工具。程序要把每个都执行完，再一起塞回去。
- **`tool_call_id` 必须原样带回**，否则模型对不上号。

## 二、工具定义、参数 Schema 与返回结果

### 1、工具定义包含什么

一个工具的定义，本质上是给模型看的"说明书"，包含四部分：

- **name**：工具名，要能望文知义，比如 `queryOrder` 而不是 `func1`。
- **description**：干什么用的，什么时候用。**这是最重要的一项**，模型选不选这个工具，主要看描述。
- **parameters**：参数 Schema，说明每个参数叫什么、什么类型、什么含义、是否必填。
- **返回结果**：工具执行后返回什么。虽然模型看不到"返回类型的严格定义"，但返回内容的格式会直接影响它下一步的判断。

### 2、description 怎么写

description 写得好不好，直接决定工具被选对还是选错。对比一下：

```text
❌ 查询订单

✅ 根据订单号查询订单的当前状态和物流信息。
   适用场景：用户询问某个订单的进度、位置、是否发货。
   不适用：查询用户的历史订单列表（用 listOrders），
          或修改订单（用 updateOrder）。
   参数 orderId 必须是 20 位数字，格式如 20261011001000000001。
```

第二种写法的好处：

- 说清了**干什么**。
- 说清了**什么时候用、什么时候不用**，避免和别的工具混淆。
- 给出了**参数格式**，减少模型填错。

**当发现模型总是选错工具时，第一件事就是回去改 description，而不是改代码。**

## 三、工具注册与工具路由

### 1、Spring AI 里怎么注册工具

Spring AI 里最简单的注册方式，是用 `@Tool` 注解：

```java
@Component
public class OrderTools {

    @Tool(description = "根据订单号查询订单状态和物流信息。" +
            "适用于用户询问订单进度、位置。orderId 为 20 位数字。")
    public OrderStatus queryOrder(
            @ToolParam(description = "订单号，20 位数字") String orderId) {
        return orderService.getStatus(orderId);
    }

    @Tool(description = "查询某用户的最近订单列表")
    public List<OrderSummary> listOrders(
            @ToolParam(description = "用户 ID") String userId,
            @ToolParam(description = "返回条数，默认 10") Integer limit) {
        return orderService.listRecent(userId, limit == null ? 10 : limit);
    }
}
```

然后在构建 `ChatClient` 时把工具挂上去：

```java
ChatClient chatClient = ChatClient.builder(chatModel)
        .defaultTools(new OrderTools())
        .build();

String answer = chatClient.prompt()
        .user("帮我看看订单 20261011001000000001 到哪了")
        .call()
        .content();
```

Spring AI 会自动：

1. 扫描 `@Tool` 方法，生成对应的 JSON Schema。
2. 把工具清单随请求发给模型。
3. 收到模型的工具调用请求后，反射调用对应方法。
4. 把返回值序列化，包成 tool 消息塞回上下文。
5. 再次请求模型，直到它给出最终答案。

**这一整套"循环"，框架帮我们做掉了。** 我们只需要把方法写好、描述写清楚。

### 2、工具路由

当工具变多，就需要"路由"——决定把哪些工具给模型。做法有两种：

**（1）全量注册**

所有工具都挂上去，模型自己选。简单，但工具一多就有两个问题：Token 消耗大；模型在几十个工具里挑，容易选错。

**（2）按场景分组**

不同场景挂不同的工具集：

```java
// 售前咨询场景，只给商品和库存工具
ChatClient presaleClient = ChatClient.builder(chatModel)
        .defaultTools(new ProductTools(), new InventoryTools())
        .build();

// 售后场景，只给订单和退款工具
ChatClient aftersaleClient = ChatClient.builder(chatModel)
        .defaultTools(new OrderTools(), new RefundTools())
        .build();
```

**推荐按场景分组。** 它同时解决了三个问题：省 Token、减少误选、缩小权限（售前 Agent 根本没有退款工具，也就不可能误退款）。

更进一步的动态路由，是先让模型判断意图，再决定加载哪组工具。这属于"工具检索"，工具特别多（几十上百个）时才需要。

## 四、工具执行器的设计

框架帮我们做了执行，但**真实项目里，我们通常要在执行外面包一层**，加上校验、权限、超时、日志、重试。

一个典型的执行器分层：

```text
┌─────────────────────────────────────┐
│  工具执行器 ToolExecutor             │
│  ┌───────────────────────────────┐  │
│  │ 1. 参数校验（格式、范围、权限） │  │
│  ├───────────────────────────────┤  │
│  │ 2. 权限校验（这个用户能调吗）   │  │
│  ├───────────────────────────────┤  │
│  │ 3. 超时控制                    │  │
│  ├───────────────────────────────┤  │
│  │ 4. 真正执行                    │  │
│  ├───────────────────────────────┤  │
│  │ 5. 结果裁剪（别太长）           │  │
│  ├───────────────────────────────┤  │
│  │ 6. 日志与审计                  │  │
│  └───────────────────────────────┘  │
└─────────────────────────────────────┘
```

用 AOP 或者显式的包装方法都能实现。关键是把这些"横切关注点"**从业务方法里抽出来**，不要让每个工具方法都重复写一遍超时和日志。

```java
public <T> T executeWithGuard(String toolName, Supplier<T> action, ToolContext ctx) {
    long start = System.currentTimeMillis();
    try {
        // 1. 权限
        if (!ctx.hasPermission(toolName)) {
            throw new ToolAccessDeniedException(toolName);
        }
        // 2. 执行 + 超时
        T result = CompletableFuture
                .supplyAsync(action, executor)
                .get(5, TimeUnit.SECONDS);
        // 3. 记录
        log.info("tool={} cost={}ms ok", toolName, System.currentTimeMillis() - start);
        return result;
    } catch (TimeoutException e) {
        log.warn("tool={} timeout", toolName);
        throw new ToolTimeoutException(toolName);
    }
}
```

## 五、Java 方法如何封装成 Agent 工具

把现有 Java 方法变成 Agent 工具，有几个反复出现的坑。

### 1、返回值要"模型友好"

模型要读工具返回值，所以**返回结果要简短、结构清晰**。别把整个实体对象原样返回：

```java
// ❌ 返回一个巨大的对象，几十个字段全塞进去
public Order queryOrder(String orderId) {
    return orderRepository.findById(orderId).orElseThrow();
}

// ✅ 只返回模型需要的字段
public OrderBrief queryOrder(String orderId) {
    Order order = orderRepository.findById(orderId).orElseThrow();
    return new OrderBrief(
            order.getId(),
            order.getStatus(),
            order.getLogisticsLocation(),
            order.getEstimatedDelivery()
    );
}
```

一个订单实体可能有 50 个字段，但模型只关心状态和位置。返回越多，Token 越费，还容易干扰判断。

### 2、参数尽量用基础类型

模型填参数的能力，和参数类型强相关。**基础类型（String、int、boolean）最稳，复杂嵌套对象最容易出错。**

```java
// ❌ 嵌套对象，模型容易填错
public void refund(RefundRequest request) { }

// ✅ 拆成基础参数，每个都有描述
public void refund(
        @ToolParam(description = "订单号，20 位数字") String orderId,
        @ToolParam(description = "退款金额，单位元，最多两位小数") BigDecimal amount,
        @ToolParam(description = "退款原因，如：不想要了、商品质量问题") String reason) { }
```

### 3、失败要返回"能看懂的信息"

工具抛异常，如果直接把堆栈丢回去，模型看不懂，也不知道该怎么办。**要把错误翻译成模型能理解的自然语言。**

```java
@Tool(description = "查询订单状态")
public String queryOrder(String orderId) {
    try {
        OrderBrief order = orderService.getBrief(orderId);
        return toJson(order);
    } catch (OrderNotFoundException e) {
        // 告诉模型"为什么失败"，它才知道下一步怎么办
        return "查询失败：没有找到订单号 " + orderId + "，请确认订单号是否正确。";
    }
}
```

对比一下：

```text
❌ 模型看不懂：
   java.lang.NullPointerException at OrderService.java:42 ...

✅ 模型能处理：
   查询失败：没有找到订单号 20261011001，请确认订单号是否正确。
   → 模型：那我提醒用户核对一下订单号。
```

### 4、把"写操作"和"读操作"分开

读操作（查）通常可以放开，写操作（改、删、发）要谨慎。命名上就区分开，权限上也区别对待：

```text
读：queryOrder、listOrders、getUserProfile
写：refundOrder、cancelOrder、sendSms、updateAddress
```

写操作一般要额外加：二次确认、金额上限、频率限制。这些放在第九篇安全里细讲。

## 六、数据库查询、HTTP 请求与文件操作工具

三类最常见的工具，各有各的注意事项。

### 1、数据库查询工具

**最要紧的是防注入、防全表扫描。**

```java
@Tool(description = "按订单号查询订单")
public String queryOrderByNo(
        @ToolParam(description = "订单号，20 位数字") String orderId) {
    // ✅ 参数化查询，别拼 SQL
    return jdbcTemplate.queryForObject(
            "SELECT id, status, location FROM orders WHERE id = ?",
            rowMapper, orderId);
}
```

要点：

- **永远用参数化查询**，模型给的参数也是不可信输入。
- **只给查询权限**，别让工具能跑 `DELETE`/`UPDATE`。
- **限制返回条数**，加 `LIMIT`，防止一次拉回几万行。
- **限制字段**，只 `SELECT` 需要的列。

### 2、HTTP 请求工具

调外部接口时要注意：

- **超时**：必须设，外部接口卡住不能拖垮自己。
- **白名单**：只能调允许的域名，防止模型被诱导去调内网地址（SSRF）。
- **鉴权**：密钥放在服务端，别暴露给模型。
- **结果裁剪**：外部接口返回的大 JSON 要裁剪后再给模型。

```java
@Tool(description = "查询某城市的天气")
public String getWeather(
        @ToolParam(description = "城市名，如 杭州") String city) {
    // 白名单校验
    if (!ALLOWED_HOSTS.contains("api.weather.com")) {
        throw new IllegalStateException("host not allowed");
    }
    return restClient.get()
            .uri("/weather?city={city}", city)
            .retrieve()
            .body(String.class);
}
```

### 3、文件操作工具

文件工具最危险，因为能直接读写服务器。原则：

- **限定根目录**：所有路径必须落在允许的目录下，防止 `../../etc/passwd` 这类路径穿越。
- **区分读写**：读工具和写工具分开授权。
- **限制大小**：写文件要限制大小，读文件要限制行数。

```java
private static final Path ROOT = Path.of("/data/agent/workspace");

@Tool(description = "读取工作区内的文件")
public String readFile(@ToolParam(description = "相对路径") String relativePath) {
    Path target = ROOT.resolve(relativePath).normalize();
    // 防止路径穿越
    if (!target.startsWith(ROOT)) {
        return "读取失败：路径不合法。";
    }
    if (!Files.exists(target)) {
        return "读取失败：文件不存在。";
    }
    return Files.readString(target);
}
```

`normalize()` 加 `startsWith(ROOT)` 这两步，是防路径穿越的标准做法，缺一不可。

## 七、工具结果如何反馈给模型

工具执行完，结果怎么塞回去，也有讲究。

### 1、要结构化、要精简

结果最好是一段干净的 JSON，字段名有意义：

```text
✅ {"status":"运输中","location":"杭州转运中心","eta":"2026-10-12"}
```

而不是：

```text
❌ 你的订单状态是运输中 位置在杭州转运中心 预计到达时间是2026年10月12日
```

JSON 结构清晰，模型解析准确率更高，程序也好裁剪。

### 2、要控制长度

一次查了 200 条记录全塞回去，会瞬间吃掉大量 Token。做法是**在工具里就裁剪**：

```java
List<OrderSummary> orders = orderService.listRecent(userId, 50);
// 只取前 10 条给模型
return orders.stream().limit(10).toList();
```

或者返回"总数 + 前 N 条"，让模型知道还有更多：

```text
{"total": 50, "showing": 10, "items": [ ... ]}
```

### 3、失败也要反馈

工具失败时，别让整个流程直接崩，而是**把失败信息作为结果返回**，让模型有机会补救：

```text
{"error": "订单不存在", "hint": "请用户核对订单号"}
```

模型看到这个，可能会转而问用户要正确的订单号，而不是直接报错。**把工具失败也当成一种"观察结果"，循环才能继续转下去。**

## 八、工具超时、重试与错误处理

### 1、超时

每个工具都要有超时。**注意：不同工具的超时值应该不一样。**

- 查缓存：100ms 级。
- 查数据库：1s 级。
- 调外部接口：5s 级。
- 跑长任务：几十秒甚至异步化。

### 2、重试

重试要**分工具、分错误**：

```java
// 幂等查询，可以放心重试
@Retryable(retryFor = ResourceAccessException.class, maxAttempts = 3)
public String queryOrder(String orderId) { }

// 非幂等的写操作，不能随便重试，否则可能重复退款
@Retryable(retryFor = ResourceAccessException.class, maxAttempts = 1)
public String refundOrder(String orderId, BigDecimal amount) { }
```

**幂等工具可以重试，非幂等工具要谨慎。** 退款、扣款、发消息这类操作，重试前必须确认是否已经执行过（用幂等键）。

### 3、错误分类

把错误分成三类，分别处理：

| 类型 | 例子 | 处理 |
| --- | --- | --- |
| 可重试 | 超时、限流、5xx | 退避重试 |
| 参数错误 | 订单号格式不对 | 返回给模型，让它修正 |
| 业务失败 | 订单不存在、无权限 | 返回给模型，让它调整方案 |

**核心思想：尽量把错误变成"模型能读到的信息"，而不是直接抛异常中断流程。**

## 九、工具权限、参数校验与安全边界

工具是 Agent 唯一能真正改变外部世界的地方，所以安全必须在这里守住。

### 1、最小权限

每个工具只给完成它职责所必需的最小权限：

- 只读工具不给写权限。
- 查订单的工具只能查当前用户的订单（**用户隔离在服务端做，不能靠模型自觉**）。
- 敏感操作单独授权。

```java
@Tool(description = "查询订单")
public String queryOrder(String orderId, ToolContext ctx) {
    Order order = orderService.get(orderId);
    // ✅ 服务端强制校验归属，不依赖模型的"自觉"
    if (!order.getUserId().equals(ctx.currentUserId())) {
        return "查询失败：无权访问该订单。";
    }
    return toJson(order);
}
```

**这里有个关键认知：模型是"可能被诱导的"，权限校验绝不能写在 Prompt 里，必须写在代码里。** 用户可以通过提示词注入让模型"假装"有权限，但代码这一关它绕不过去。

### 2、参数校验

参数要当成用户输入来校验：

```java
if (!orderId.matches("\\d{20}")) {
    return "参数错误：订单号必须是 20 位数字。";
}
if (amount.compareTo(new BigDecimal("500")) > 0) {
    return "退款金额超过 500 元，需要人工审批。";
}
```

校验失败时返回清晰的原因，模型就能调整；返回一句"参数错误"，模型只能瞎猜。

### 3、危险操作要确认

对于不可逆的操作（退款、删除、发消息），采用**Human-in-the-Loop**：Agent 准备好参数后先不执行，等用户确认。

```text
Agent：即将为你申请退款：订单 20261011001，金额 128 元。
       确认后回复"确认退款"。
用户：确认退款
Agent：→ 执行 refundOrder
```

这个模式在《Agent 工作流与状态图》里会结合中断恢复机制细讲。

## 十、工具调用的日志、追踪与审计

### 1、记什么

每次工具调用至少要记：

- 哪个会话、哪个用户。
- 调了哪个工具。
- 参数是什么。
- 结果是什么（或失败原因）。
- 耗时多少。
- 是否成功。

```java
log.info("tool_call conversationId={} user={} tool={} args={} cost={}ms result={}",
        ctx.conversationId(), ctx.userId(), toolName, args, cost, brief(result));
```

### 2、为什么要记

- **排障**：Agent 结果不对时，回看它调了什么、拿到了什么，一目了然。
- **审计**：谁在什么时候发起了退款、金额多少，要有据可查。
- **优化**：统计哪些工具最常被调、哪些总失败、哪些描述容易被误解，据此改进。
- **成本**：工具结果的大小直接影响 Token 消耗，统计后能发现"哪个工具返回太啰嗦"。

### 3、敏感信息要脱敏

日志里别记明文手机号、身份证、银行卡。参数和结果都过一遍脱敏：

```java
private String mask(String s) {
    return s.replaceAll("(\\d{3})\\d{4}(\\d{4})", "$1****$2");
}
```

审计和隐私的平衡，在第九篇还会展开。

## 十一、实践验证：把一个 Java 方法变成 Agent 工具

前面讲了工具的定义、注册和调用流程，这一节动手把一个普通 Java 方法变成 Agent 能调的工具，并观察它是怎么被选中的。

### 1、注解式：最省事的写法

给方法加上 `@Tool` 和 `@ToolParam` 就行：

```java
@Component
public class WeatherTool {

    @Tool(description = "获取指定城市当前时间的温度")
    public String getTemperature(@ToolParam String cityName) {
        return cityName + "温度值是30度";
    }

    @Tool(description = "获取指定城市的紫外线值")
    public String getUltraviolet(@ToolParam String cityName) {
        return cityName + "紫外线值：";
    }
}
```

对照前面讲的"工具定义四要素"：

| 要素 | 代码里的位置 |
| --- | --- |
| name | 方法名 `getTemperature` |
| description | `@Tool(description = "...")` |
| parameters | `@ToolParam` 标注的参数 |
| 返回结果 | 方法返回值 |

**`description` 是最关键的一项。** 模型选不选这个工具、选得对不对，主要看它。如果发现模型老是选错工具，先回来改这句描述。

### 2、把工具注册进工具清单

方法定义好了，还要注册成 `ToolCallbackProvider`，模型才看得到：

```java
@Configuration
public class ToolsRegister {

    @Bean
    public ToolCallbackProvider toolList(WeatherTool weatherTool) {
        // MethodToolCallbackProvider 扫描对象里所有 @Tool 方法，生成工具清单
        return MethodToolCallbackProvider.builder()
                .toolObjects(weatherTool)
                .build();
    }
}
```

然后挂到 `ChatClient` 上：

```java
public ChatController(ChatModel chatModel,
                      ChatClient.Builder chatClientBuilder,
                      ToolCallbackProvider toolCallbackProvider) {
    this.chatModel = chatModel;
    this.chatClient = chatClientBuilder
            .defaultToolCallbacks(toolCallbackProvider)   // 注入工具清单
            .build();
}
```

这一步对应前面讲的"工具注册"：**注册的本质，就是让框架知道有哪些工具、每个工具的 Schema 是什么。**

### 3、函数式：更灵活的写法

不想用注解，也可以实现 `BiFunction`，用 `FunctionToolCallback` 手动包装：

```java
public class WeatherTool implements BiFunction<String, ToolContext, String> {
    @Override
    public String apply(String city, ToolContext toolContext) {
        return "It's always sunny in " + city + "!";
    }
}

// 包装成 ToolCallback
ToolCallback weatherTool = FunctionToolCallback.builder("get_weather", new WeatherTool())
        .description("Get weather for a given city")   // 等价于 @Tool(description=...)
        .inputType(String.class)                        // 参数类型
        .build();
```

两种写法对比：

| 写法 | 适合 | 特点 |
| --- | --- | --- |
| `@Tool` 注解 | 已有的 Service 方法 | 改动小，扫描即用 |
| `FunctionToolCallback` | 需要动态构造、或来自第三方的逻辑 | 灵活，可运行时拼装 |

### 4、运行：观察工具被选中

启动后问一句带城市名的话，就能在控制台看到工具被调用：

```bash
curl "http://localhost:8080/simple/chatclient?message=杭州今天多少度"
```

日志里会出现模型的工具调用请求和工具返回：

```text
正在获取杭州天气信息...
```

![image-20261011103000001](assets/image-20261011103000001.png)

![image-20261011103000002](assets/image-20261011103000002.png)

### 5、这一步验证了什么

- **工具 = 方法 + 描述 + 参数 Schema**：`@Tool` 和 `@ToolParam` 分别对应 description 和 parameters。
- **注册 = 生成清单给模型看**：`MethodToolCallbackProvider` 扫描 `@Tool` 方法，产出模型能读的工具清单。
- **模型只提出请求，程序负责执行**：控制台里打印"正在获取杭州天气信息"的是**我们的 Java 方法**，模型只是"决定要调它"——这正是前面反复强调的一点。
- **description 决定选择正确率**：把 `@Tool` 的描述写清楚，模型才选得准。

> 这里的工具返回的是写死的字符串。真实项目里要接数据库或 HTTP，还要加参数校验、超时和权限——那些是前面"工具执行器的设计"和"安全边界"两节的内容。

## 小结

这一篇把工具系统从流程到代码走了一遍：

- Tool Calling 的循环是：**模型提出请求 → 程序执行 → 结果回灌 → 模型再决策**。
- 工具定义的关键在 **description**，模型选不选、选得对不对，主要看它。
- 工具注册推荐**按场景分组**，同时省 Token、减少误选、收窄权限。
- 执行器要把**校验、权限、超时、日志**这些横切逻辑抽出来。
- Java 方法封装成工具时：**返回值要精简、参数用基础类型、错误要翻译成人话、读写要分开**。
- 结果回灌要**结构化、精简、失败也反馈**。
- **权限校验必须写在代码里，不能写在 Prompt 里。**
- 每次调用都要**记日志**，为了排障、审计、优化和成本。

工具让 Agent 能动手了。但如果任务需要依赖企业内部的知识——比如产品手册、规章制度、历史工单——光靠工具和模型自身的知识还不够，得给它接一个知识库。下一篇：《RAG 与知识库增强》。
