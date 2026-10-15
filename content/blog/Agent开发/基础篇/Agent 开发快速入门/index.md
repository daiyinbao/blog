+++
title = "Agent 开发快速入门"
date = 2026-10-11T00:00:00+08:00
weight = 10
tags = ["Agent", "AI", "大模型", "ReAct", "架构"]
summary = "Agent 系列（一）：从一次普通对话讲起，说清 Agent 是什么、由什么组成、怎么运转，以及它和 Chatbot、Workflow 的区别与适用边界。"

+++

这是 Agent 开发系列的第一篇。后面的每一篇都会落到具体的代码和工程问题上，但在那之前，得先把最基本的问题回答清楚：Agent 到底是什么，它和我们现在用的"大模型聊天"有什么不一样，为什么有的场景需要 Agent，有的场景反而用不着。

这一篇先理清概念、组成、运行流程和边界，最后再动手把第一个 Agent 跑起来。理清这些，后面接模型、接工具、接知识库时，才知道每一步是为了什么。

## 一、什么是 AI Agent

### 1、先从一次对话说起

我们用大模型最熟悉的方式，是打开一个对话框，输入问题，等它回答。

```text
用户：帮我查一下订单 20261011001 现在到哪了
模型：抱歉，我无法查询实时的订单信息，建议你登录 App 查看。
```

这个回答没错，但也没用。因为**大模型本身只会"根据输入生成文本"**，它看不到你的订单系统，也调不了快递接口。它的知识停在训练数据那一刻，你的实时业务数据它一概不知。

如果希望它真的能把这件事办成，就需要让它具备三件事：

- 知道去哪查（有一个查订单的工具）。
- 判断该不该查、用哪个参数查（能做决策）。
- 拿到结果后继续判断下一步（能循环推进，而不是答一次就结束）。

当这三件事凑齐，它就从"会聊天的模型"变成了"会办事的 Agent"。

```text
用户：帮我查一下订单 20261011001 现在到哪了
Agent：  → 调用 queryOrder(orderId="20261011001")
        → 得到 {status: "运输中", location: "杭州转运中心"}
        → 组织语言回答：你的订单已到达杭州转运中心，预计明天下午送达。
```

### 2、Agent 的定义

可以给一个不那么严谨、但足够好用的定义：

> **Agent 是一个以大模型为决策核心，能够自主选择并调用工具、在循环中逐步推进、最终完成某个目标的程序。**

拆开看，这句话里有四个关键词：

- **大模型为决策核心**：判断"下一步做什么"的是模型，不是一堆写死的 if-else。
- **自主选择并调用工具**：模型可以决定用哪个工具、传什么参数。
- **在循环中推进**：不是一问一答，而是"想一想、做一步、看结果、再想一想"。
- **完成某个目标**：Agent 是为任务服务的，而不是为聊天服务的。

需要强调的是，Agent 不是某种新的模型，也不是某个具体的框架。**它是一种把模型、工具、状态和执行循环组织起来的程序结构**。同样的模型，套上 Agent 的结构，就能从"聊天"变成"办事"。

### 3、LLM、Chatbot、Workflow 与 Agent 的区别

这四个词经常被混用，但它们处在不同的层次上。

- **LLM（大语言模型）**：最底层的能力，输入文本、输出文本。它本身不做任何决策，也记不住上一次对话。
- **Chatbot（聊天机器人）**：在 LLM 外面套了一层对话管理，能记住上下文、能连续聊。但它的目标始终是"生成回复"，不会主动去执行任务。
- **Workflow（工作流）**：把固定的步骤串起来，比如"先取参数、再查库、再调接口、最后拼回复"。每一步都由**人预先编排**，路径是写死的。
- **Agent**：由**模型在运行时决定**走哪一步。路径不是写死的，而是根据中间结果动态产生的。

用一个对比表看得更清楚。

| 维度 | LLM | Chatbot | Workflow | Agent |
| --- | --- | --- | --- | --- |
| 决策者 | 无 | 无 | 人（编排） | 模型（运行时） |
| 能否用工具 | 否 | 通常否 | 是（写死） | 是（自主选） |
| 执行路径 | 无 | 固定一问一答 | 固定 | 动态生成 |
| 是否有循环 | 否 | 否 | 一般无 | 有 |
| 适合的场景 | 文本生成 | 客服问答 | 流程明确的业务 | 目标明确但路径不定 |

最容易混淆的是 Workflow 和 Agent。一句话区分：

- **Workflow 是"我告诉你每一步怎么做"。**
- **Agent 是"我告诉你目标，你自己想办法"。**

需要说明的是，这两者不是对立的。**成熟的系统往往是"Workflow 做骨架，Agent 做血肉"**：整体流程用工作流固定下来，保证可控；其中判断不了、需要灵活处理的环节，再交给 Agent。这个思路在后面的《Agent 工作流与状态图》里会展开。

## 二、Agent 的核心组成

不管用什么框架，一个 Agent 基本都逃不开下面几个部分。

```text
        ┌─────────────────────────────┐
        │           指令               │
        │   （角色、目标、约束）        │
        └──────────────┬──────────────┘
                       │
   ┌─────────┐   ┌─────▼─────┐   ┌─────────┐
   │  模型    │◄──│  执行循环  │──►│  工具    │
   └─────────┘   └─────┬─────┘   └─────────┘
                       │
                 ┌─────▼─────┐
                 │   状态     │
                 │（历史、记忆）│
                 └───────────┘
```

### 1、模型（Model）

模型是 Agent 的"大脑"，负责所有需要判断的地方：这句话是什么意思、要不要用工具、用哪个工具、参数填什么、结果够不够、要不要收尾。

模型选型直接影响 Agent 的能力上限。后面《大模型调用与上下文工程》会专门讲怎么选、怎么控。

### 2、指令（Instructions）

指令就是给模型的"岗位说明书"，通常写在 System Prompt 里。它规定了：

- 你是谁（角色）。
- 你要完成什么（目标）。
- 你必须遵守什么（约束），比如"只能查询本用户的订单""金额超过 500 元必须提示人工确认"。

指令是**成本最低、见效最快的控制手段**。很多"Agent 不听话"的问题，改指令就能解决一大半。

### 3、工具（Tools）

工具是 Agent 的"手脚"，决定了它能不能真正改变外部世界。查数据库、调 HTTP 接口、读文件、发消息，都要靠工具。

没有工具的 Agent，本质上还是个聊天机器人——只不过更会"想"，但什么也"做"不了。工具系统的设计是这一系列的重头戏，单独放在《Tool Calling 与工具系统》里讲。

### 4、状态（State）

状态是 Agent 的"记忆"，记录当前任务进行到哪了。它至少包含：

- 对话历史（用户说了什么、Agent 回了什么）。
- 中间结果（调了哪些工具、拿到了什么）。
- 任务进度（还差哪几步、有没有失败重试）。

没有状态，Agent 每走一步都会"失忆"。状态的设计和持久化在《Agent 状态与记忆机制》里讲。

### 5、执行循环（Loop）

把这四样东西串起来的，是一个循环：

```text
        ┌──────────────────────────────┐
        │                              │
        ▼                              │
   组装上下文 ──► 模型决策 ──► 执行动作 ─┘
        ▲             │
        │             ▼
        └──────── 观察结果
                 （够了就结束）
```

只要模型认为"还没完成"，这个循环就继续转下去；当它给出最终答案，或者触发了步数、时间、成本的限制，循环才结束。

**这个循环是 Agent 最本质的东西。** 前面那张对比表里，Agent 和 Workflow 最根本的差别，就在"循环由谁决定"——Workflow 的循环是写死的，Agent 的循环是模型驱动的。

## 三、Agent 的运行流程：感知、决策、行动、观察

把上面那个循环再展开一点，一次完整的 Agent 运行可以分成四个阶段。

### 1、感知（Perceive）

感知就是"收集当前能看到的全部信息"，包括：

- 用户这次说了什么。
- 之前的历史和记忆。
- 上一轮工具返回的结果。
- 外部环境的信号（比如当前时间、用户身份）。

感知阶段做的事情，本质上就是**把信息组装成模型能看懂的上下文**。上下文组装得好不好，直接决定模型判断得准不准。这是《大模型调用与上下文工程》的主题。

### 2、决策（Decide）

模型拿着上下文，决定下一步。决策的结果无非两类：

- **调用某个工具**（并给出参数）。
- **直接给出最终回答**（认为任务已经完成）。

决策靠的是模型的理解和推理能力，我们能做的，是通过指令、工具描述、示例来引导它做出正确判断。

### 3、行动（Act）

决策说"要调 `queryOrder(orderId=...)`"，行动阶段就真的去执行这个工具：连数据库、发 HTTP 请求、读文件。

行动阶段是**唯一真正和外部世界交互的地方**，所以也是权限、校验、超时、重试这些工程问题最集中的地方。

### 4、观察（Observe）

工具执行完会返回一个结果，观察阶段把这个结果收进上下文，作为下一轮决策的输入。

```text
感知：用户问"订单到哪了"，历史里知道用户是谁
  │
  ▼
决策：需要调 queryOrder，参数 orderId=20261011001
  │
  ▼
行动：执行工具，返回 {status:"运输中", location:"杭州"}
  │
  ▼
观察：把结果放进上下文
  │
  └──► 回到感知，进入下一轮：这次模型判断信息够了，输出最终回答
```

四步走一轮，转一圈就是一次"思考—执行"。**Agent 的能力，很大程度上取决于这个圈能转多稳、转多少圈、每圈的信息质量有多高。**

## 四、ReAct 模式

前面说的循环，落地成一个具体的提示词模式，最经典的就是 ReAct。

### 1、基本思想

ReAct 是 Reasoning + Acting 的缩写。它的核心想法很朴素：**让模型把"思考"和"行动"交替进行，并且把思考过程显式写出来。**

在 ReAct 里，模型每一轮会产出这样的结构：

```text
Thought:  我需要先查一下这个订单的状态
Action:   queryOrder
Action Input: {"orderId": "20261011001"}
Observation: {"status": "运输中", "location": "杭州转运中心"}
Thought:  信息够了，可以回答了
Final Answer: 你的订单已到达杭州转运中心，预计明天下午送达。
```

- **Thought**：模型自己的推理，说明为什么这么做。
- **Action**：决定调用的工具。
- **Action Input**：工具参数。
- **Observation**：工具返回的结果（由程序填回）。
- **Final Answer**：认为任务完成时给出的答案。

关键点在于：**Thought 是模型"想"出来的，Observation 是程序"填"进去的**。模型只能负责思考和决策，真正执行动作、把结果拼回上下文的，是外面的程序。

### 2、为什么"显式写思考"有用

让模型把推理写出来，好处有三个：

- **推理更准**：把中间步骤写出来，等于让它"打草稿"，复杂任务上比直接给答案更可靠。
- **过程可见**：我们能从 Thought 里看到它为什么这么判断，出问题时好排查。
- **便于纠正**：如果发现它的思路跑偏了，可以在指令或上下文里针对性地引导。

这也是现在 Function Calling 更常见的做法：模型不直接输出 `Action` 文本，而是返回一个结构化的工具调用请求。形式变了，但"思考—行动—观察"的循环没变。

### 3、ReAct 的局限

ReAct 不是万能的，它的短板也很明显：

- **容易绕圈**：模型可能反复调用同一个工具，或者一直找不到收敛条件。
- **缺少全局规划**：它是走一步看一步，没有"先想清楚整体路线"的环节。
- **步数不可控**：没有限制的话，可能转很多圈，token 和时间都烧掉。

所以工程上必须给它加上护栏：最大步数、超时、重复调用检测。这些会在后面的工具系统和工程化实战里具体讲。

## 五、单 Agent 与多 Agent

到目前讲的都是"一个 Agent 干一件事"。如果任务很复杂，一个 Agent 搞不定，就会想到"多找几个 Agent 分工"。这就是多 Agent。

简单理解两者的区别：

- **单 Agent**：一个大脑，一套指令，共享一份上下文，自己完成整个任务。
- **多 Agent**：多个大脑，各自有指令和上下文，通过消息或共享状态协作。

一个典型的对比：

```text
单 Agent：
  用户 → [ 一个 Agent：理解需求 → 查资料 → 写代码 → 测试 ] → 结果

多 Agent：
  用户 → [ 调度者 ]
            ├──► [ 调研 Agent ] ──┐
            ├──► [ 编码 Agent ] ──┼──► [ 汇总 ] → 结果
            └──► [ 测试 Agent ] ──┘
```

多 Agent 的好处是**分工明确、各自上下文更干净、可以并行**。但代价也很直接：协调复杂、成本翻倍、容易互相甩锅或陷入循环。

一个重要判断：**能用单 Agent 解决的，不要上多 Agent。** 大多数场景，把指令写好、工具给对、上下文管好，单 Agent 就够用了。多 Agent 真正划算的场景，以及它怎么落地，放在《多 Agent 协作》里专门讲。

## 六、Agent 适合解决什么问题

### 1、适合的场景

判断一个需求该不该用 Agent，看这几个特征：

- **目标明确，但路径不固定**：知道要达成什么，但具体分几步、用哪些工具，事先说不准。比如"帮我整理一份竞品分析"。
- **需要调用多种外部能力**：要查库、要调接口、要读文件，靠纯文本生成办不到。
- **需要多步推理和迭代**：一步做不完，要根据中间结果不断调整。比如"排查这个报错的根因"。
- **输入有较大的不确定性**：用户表达方式千变万化，用固定规则很难覆盖。

### 2、不适合的场景

反过来，下面这些情况用 Agent 是"杀鸡用牛刀"，甚至会更糟：

- **路径完全固定**：步骤明确、不需要判断，直接用 Workflow 更快更稳，还便宜。
- **只要一次生成**：翻译、润色、摘要这类，一次模型调用就够，不需要循环。
- **对确定性要求极高**：比如扣款、发券这类操作，容不得模型"自由发挥"，应该把决策权收回到代码里。
- **延迟和成本卡得很死**：Agent 要多轮调用，天然比单次调用慢、贵。

### 3、为什么不是所有 AI 应用都需要 Agent

一句话总结：

> **Agent 用"自主性"换来了"不确定性"。**

模型自主决策带来了灵活性，但也带来了三个代价：

- **不稳定**：同样的输入，可能走出不同的路径，结果有波动。
- **贵**：一轮任务可能调用模型好几次、工具好几次。
- **难调试**：路径是运行时生成的，出了问题不好复现。

所以正确的思路不是"能上 Agent 就上 Agent"，而是**先问这个任务到底需不需要"自主决策"**：

- 不需要判断的，用普通调用或 Workflow。
- 需要一点灵活性的，用"Workflow 骨架 + Agent 环节"。
- 真的路径不定、需要多步自主推进的，才上完整的 Agent。

这也是后面几篇反复会提到的一条原则：**能用确定的方式解决的，就不要交给模型去决定。**

## 七、实践验证：跑通第一个 ReAct Agent

前面讲的都是概念，这一节动手把 ReAct 循环跑起来。用的是 Spring AI Alibaba 1.1 的 `ReactAgent`——它把"模型 + 工具 + 记忆 + 循环"都封装好了，几行代码就能看到 Agent 自己决定"先调工具、再回答"。

### 1、环境准备

- JDK 17+（示例用 17）
- Maven 3.8+
- 一个可用的大模型 API Key（示例用阿里云百炼的 DashScope）

`pom.xml` 里引入两个依赖：

```xml
<properties>
    <spring-ai-alibaba.version>1.1.0.0-RC2</spring-ai-alibaba.version>
</properties>

<dependencyManagement>
    <dependencies>
        <dependency>
            <groupId>com.alibaba.cloud.ai</groupId>
            <artifactId>spring-ai-alibaba-bom</artifactId>
            <version>${spring-ai-alibaba.version}</version>
            <type>pom</type>
            <scope>import</scope>
        </dependency>
    </dependencies>
</dependencyManagement>

<dependencies>
    <dependency>
        <groupId>com.alibaba.cloud.ai</groupId>
        <artifactId>spring-ai-alibaba-agent-framework</artifactId>
    </dependency>
    <dependency>
        <groupId>com.alibaba.cloud.ai</groupId>
        <artifactId>spring-ai-alibaba-starter-dashscope</artifactId>
        <version>${spring-ai-alibaba.version}</version>
    </dependency>
</dependencies>
```

`application.yml` 里填上 Key 和模型名：

```yaml
spring:
  ai:
    dashscope:
      api-key: 你的ApiKey
      chat:
        options:
          model: deepseek-r1
```

![image-20261011101500001](assets/image-20261011101500001.png)

### 2、先给 Agent 一个工具

ReAct 要有"行动"，所以先准备一个工具。这里用最简单的写法——实现 `BiFunction`：

```java
public class WeatherTool implements BiFunction<String, ToolContext, String> {
    @Override
    public String apply(String city, ToolContext toolContext) {
        return "It's always sunny in " + city + "!";
    }
}
```

把它包装成 `ToolCallback`，模型才认识：

```java
ToolCallback weatherTool = FunctionToolCallback.builder("get_weather", new WeatherTool())
        .description("Get weather for a given city")
        .inputType(String.class)
        .build();
```

`description` 是给模型看的，它靠这句话判断"什么时候该调这个工具"。

### 3、创建 Agent

```java
ReactAgent agent = ReactAgent.builder()
        .name("weather_agent")                        // 名字（必填）
        .model(chatModel)                             // 大脑：大模型
        .tools(weatherTool)                           // 手脚：工具
        .systemPrompt("You are a helpful assistant")  // 指令：系统提示词
        // .saver(new MemorySaver())                  // 记忆：多轮对话
        .build();
```

对比前面讲的核心组成，`ReactAgent.builder()` 里的配置正好一一对应：

| 配置项 | 对应要素 |
| --- | --- |
| `.model()` | 模型 |
| `.systemPrompt()` | 指令 |
| `.tools()` | 工具 |
| `.saver()` | 状态 |
| `.build()` 之后的 `stream()` / `call()` | 执行循环 |

**这就是前面那张"模型—指令—工具—状态—循环"结构图在代码里的样子。**

### 4、运行并观察循环

用流式方式调用，方便看清它每一步在做什么：

```java
@GetMapping(value = "/simple/agent", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
public void streamChat() throws GraphRunnerException {
    Flux<NodeOutput> stream = agent.stream("杭州今天天气怎么样？");

    stream.subscribe(output -> {
        if (output instanceof StreamingOutput streamingOutput) {
            OutputType type = streamingOutput.getOutputType();

            if (type == OutputType.AGENT_MODEL_STREAMING) {
                // 模型正在逐字输出
                System.out.print(streamingOutput.message().getText());
            } else if (type == OutputType.AGENT_MODEL_FINISHED) {
                System.out.println("\n模型输出完成");
            }
            if (type == OutputType.AGENT_TOOL_FINISHED) {
                // 工具执行完成
                System.out.println("工具调用完成: " + output.node());
            }
        }
    });
}
```

启动后访问接口：

```bash
curl "http://localhost:8080/simple/agent"
```

控制台大致会看到这样的过程：

```text
工具调用完成: weather_agent
It's always sunny in 杭州!
模型输出完成
```

![image-20261011101500002](assets/image-20261011101500002.png)

![image-20261011101500003](assets/image-20261011101500003.png)

### 5、这一步验证了什么

- **ReAct 循环确实转起来了**：模型先判断"该调 `get_weather`"，拿到结果后再组织语言回答——正是"思考—行动—观察"三步。
- **Agent 的组成不是抽象概念**：`.model()`、`.systemPrompt()`、`.tools()` 分别对应模型、指令、工具。
- **路径是模型自己决定的**：我们只给了目标和工具，**没有写**"先调工具再回答"的流程，是模型自己走出来的。这正是前面讲的"Agent 和 Workflow 的根本区别"。

> 这里的 `WeatherTool` 是写死的假数据，只为演示循环。真实项目里它应该是查数据库或调接口，这会在第三篇《Tool Calling 与工具系统》里展开。

## 小结

这一篇把 Agent 的地基铺好了：

- Agent 是**以大模型为决策核心、能调工具、在循环中推进、完成目标**的程序结构。
- 它和 Chatbot、Workflow 的根本区别，在于**执行路径由谁决定**。
- 核心组成是**模型、指令、工具、状态、执行循环**。
- 运行流程是**感知、决策、行动、观察**四步循环。
- ReAct 是最经典的落地模式，靠"思考—行动—观察"交替推进，但要加护栏。
- 单 Agent 优先，多 Agent 慎用。
- 判断标准是**任务是否需要自主决策**，而不是"是不是 AI"。

下一篇开始动真格的：《大模型调用与上下文工程》。既然模型是 Agent 的大脑，那就先搞清楚怎么把这个大脑接进来——消息结构长什么样、Prompt 怎么写、结构化输出怎么做、上下文窗口满了怎么办。
