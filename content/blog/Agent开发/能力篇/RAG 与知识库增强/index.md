+++
title = "RAG 与知识库增强"
date = 2026-10-11T00:00:00+08:00
weight = 13
tags = ["Agent", "RAG", "向量数据库", "Embedding", "检索"]
summary = "Agent 系列（四）：从整体架构讲起，拆解文档切分、Embedding、向量检索、混合召回、Rerank 与评估，并说明 RAG 与微调的取舍。"

+++

前面三篇，Agent 已经能接模型、能调工具了。但有一类问题它还是答不好：**依赖企业内部知识的问题。**

比如用户问"我们公司的年假政策是怎么规定的"，模型训练数据里根本没有这份制度，工具也查不到——除非我们专门把它接进去。这就是 RAG 要解决的事。

RAG（Retrieval-Augmented Generation，检索增强生成）的思路很直接：**回答之前，先去知识库里把相关资料捞出来，塞进上下文，再让模型基于这些资料回答。** 模型不用"记住"知识，只要"会读"就行。

## 一、RAG 的整体架构与适用场景

### 1、整体架构

RAG 分成两个阶段：**离线建库**和**在线检索**。

```text
【离线：建库】
  文档 ──► 解析 ──► 切分 ──► Embedding ──► 存入向量库

【在线：检索 + 生成】
  用户问题 ──► Embedding ──► 向量检索 ──► Rerank ──► 拼进上下文 ──► 模型生成
                                  │
                             向量数据库
```

建库阶段做的事：把文档处理成一段段"切片"，每片算一个向量，存进向量库。

检索阶段做的事：把用户问题也转成向量，找出最相似的若干切片，作为"参考资料"一起发给模型。

```text
System: 你是一个客服助手。只根据下面提供的资料回答，资料里没有的就说"我不确定"。

【资料】
1. 员工年假规定：入职满 1 年享有 5 天年假，满 3 年 10 天，满 5 年 15 天……
2. 年假申请流程：提前 3 个工作日在系统提交……

User: 我入职两年了，能休几天年假？
```

模型看到资料，就能答"你有 10 天年假"。**它的答案来自资料，而不是它的记忆——这就是 RAG 的核心价值。**

### 2、适用场景

RAG 特别适合：

- **企业私有知识**：制度、手册、产品文档、FAQ。
- **时效性强的信息**：新闻、价格、库存（虽然这类也可以走工具）。
- **需要引用出处的场景**：法律、医疗、金融，答案要能溯源。
- **知识频繁更新**：改文档就能更新知识，不用重训模型。

### 3、RAG 的核心矛盾

RAG 看起来简单，但效果好坏差别极大。核心矛盾在于：

> **模型只能看到"检索回来的那几段"。检索错了，模型再强也答不对。**

所以 RAG 的功夫，一大半花在"怎么把正确的那几段捞出来"上。下面从切分一路讲到 Rerank，都是在解决这个问题。

## 二、文档解析、切分与清洗

### 1、解析

不同格式的文档，要用不同的解析器：

- **PDF**：最麻烦，有扫描版（要 OCR）、有双栏排版（顺序会乱）、有表格。
- **Word / Markdown**：相对规整，保留标题层级很重要。
- **HTML**：要去掉导航、广告等噪声。
- **Excel**：要处理多 sheet、合并单元格。

解析的目标是**把文档变成干净的纯文本，并尽量保留结构**（标题、段落、列表）。

### 2、切分

为什么必须切分？两个原因：

- **模型上下文有限**，不能把整本书塞进去。
- **检索精度**：切片太大，包含很多无关内容；切片太小，又缺少上下文。

常见切分策略：

**（1）固定长度切分**

按固定字符数切，比如每 500 字一段，段间重叠 50 字。

```text
优点：简单、快。
缺点：可能把一句话、一个完整的意思从中间切断。
```

**（2）按结构切分**

按标题、段落、列表这些自然边界切。

```text
优点：切片语义完整。
缺点：依赖文档本身的结构。
```

**（3）递归切分**

优先按大结构（章节）切，太大再按小结构（段落）切，还太大才按长度切。**这是最常用的策略。**

Spring AI 提供了对应的实现：

```java
DocumentSplitter splitter = new TokenTextSplitter(
        800,   // 每片目标 token 数
        350,   // 最小片大小
        5,     // 最小剩余片大小
        10000, // 最大片数
        true   // 保留分隔符
);

List<Document> chunks = splitter.apply(documents);
```

### 3、重叠（Overlap）

切片之间要留**重叠**，防止关键信息正好被切在边界上。

```text
切片1：[........A B C]
切片2：        [C D E........]
                ↑ 重叠部分
```

如果"年假天数"这句话横跨边界，没有重叠的话，两片都不完整；有重叠，至少有一片是完整的。一般重叠取切片长度的 10% ~ 20%。

### 4、清洗

切分前后要清洗：

- 去掉页眉页脚、页码、水印。
- 合并被换行拆断的句子。
- 去掉重复内容（比如每页都有的免责声明）。
- 处理表格：转成"表头: 值"的文本形式。

**噪声越多，检索越不准。** 清洗是"脏活"，但对效果影响很大。

### 5、保留 Metadata

每片都要带元数据，检索时才能过滤和引用：

```java
Document doc = new Document(content, Map.of(
        "source", "员工手册.pdf",
        "page", "12",
        "section", "年假规定",
        "updatedAt", "2026-09-01"
));
```

元数据后面有用：按来源过滤、按时间过滤、给答案加引用。

## 三、Embedding 与向量表示

### 1、Embedding 是什么

Embedding（嵌入）是把一段文本映射成一个**高维向量**（比如 1536 维的浮点数数组）。

它的神奇之处在于：**语义相近的文本，向量距离也近。**

```text
"怎么请年假"     → [0.12, -0.34, 0.56, ...]
"年假的申请流程" → [0.11, -0.31, 0.58, ...]   ← 距离很近
"公司地址在哪"   → [-0.72, 0.15, -0.23, ...]  ← 距离很远
```

这样，"找相关文档"就变成了"找距离最近的向量"，可以用数学方法高效计算。

### 2、相似度计算

常用的两种：

- **余弦相似度**：看两个向量的夹角，最常用。
- **点积 / 欧氏距离**：某些模型配合特定距离度量。

### 3、Embedding 模型的选择

要点：

- **建库和检索必须用同一个模型**。换了模型，旧向量就失效了，要重建库。
- **维度越高表达能力越强，但存储和计算成本也越高**。
- **多语言**：中文场景要确认模型对中文的支持。
- **是否本地部署**：数据敏感就本地部署，图省事就用云服务。

```java
// Spring AI 里配置 Embedding 模型
@Bean
public EmbeddingModel embeddingModel() {
    return new OpenAiEmbeddingModel(
            OpenAiApi.builder().apiKey(apiKey).build(),
            MetadataMode.EMBED
    );
}
```

## 四、向量数据库与相似度检索

### 1、向量数据库做什么

向量库的核心能力是：**在几百万甚至上亿个向量里，快速找到和查询向量最相近的 Top-K 个。**

它用的不是逐个比对（太慢），而是 **ANN（近似最近邻）** 算法，比如 HNSW、IVF。用一点点精度换极大的速度。

常见选择：

| 类型 | 代表 | 特点 |
| --- | --- | --- |
| 专用向量库 | Milvus、Qdrant、Weaviate | 功能全，适合大规模 |
| 传统库扩展 | pgvector（PostgreSQL） | 复用现有库，运维简单 |
| 内存/轻量 | FAISS、Redis | 快，适合中小规模或缓存 |
| 云服务 | 各家云厂商 | 免运维 |

**中小项目用 pgvector 往往最划算**——不用额外引入一个数据库，运维成本最低。

### 2、检索流程

```java
VectorStore vectorStore = ...;

List<Document> results = vectorStore.similaritySearch(
        SearchRequest.builder()
                .query("入职两年有几天年假")
                .topK(5)                    // 取最相近的 5 片
                .similarityThreshold(0.7)   // 相似度低于 0.7 的不要
                .build()
);
```

`topK` 和 `similarityThreshold` 是两个关键参数：

- `topK` 太大，会混进无关内容；太小，可能漏掉正确的。
- 阈值太低，噪声多；太高，可能什么都检索不到。

**这两个值要靠评估集调，不能拍脑袋。**

## 五、Metadata 过滤与混合检索

### 1、Metadata 过滤

光靠向量相似度不够。比如用户问"2026 年的年假政策"，如果库里同时有 2024 和 2026 两版，纯向量检索可能把旧版也捞出来。

这时用元数据做过滤：

```java
SearchRequest.builder()
        .query("年假政策")
        .topK(5)
        .filterExpression("year == 2026 AND dept == 'HR'")  // 先过滤再检索
        .build();
```

**过滤 + 向量检索**的组合，比纯向量检索准得多。尤其是多租户场景，必须先按 `tenantId` 过滤，否则会串数据。

### 2、纯向量检索的短板

向量检索擅长"语义相近"，但对**精确匹配**不敏感：

- 用户搜"订单号 20261011001"，向量检索可能返回一堆"关于订单号"的文档，而不是这个具体订单号。
- 用户搜一个专有名词、错误码、产品型号，向量检索往往不如关键词匹配。

### 3、混合检索

解决办法是**向量检索 + 关键词检索**一起上，再合并结果。

```text
               ┌──► 向量检索（语义）──┐
用户问题 ──────┤                      ├──► 融合排序 ──► Top-K
               └──► 关键词检索（BM25）─┘
```

融合的常用方法是 **RRF（Reciprocal Rank Fusion）**：不看绝对分数，只看排名，把多个来源的排名综合起来。

```text
RRF 分数 = Σ 1 / (k + rank_i)
```

这样，一个文档如果在两路检索里都排前面，综合分数就高。**混合检索是提升召回率最有效的手段之一**，尤其是既有语义查询又有精确查询的场景。

## 六、Rerank 重排序

### 1、为什么要 Rerank

向量检索有个特点：**快，但不够准。** 它用 ANN 近似，加上向量本身的表达能力有限，Top-K 里常常混着一些不太相关的。

Rerank 的思路是：**先用向量检索快速召回一批候选（比如 50 条），再用一个更精细的模型对这批候选重新打分排序，取最相关的几条（比如 5 条）。**

```text
向量检索 Top-50  ──► Rerank 模型精排 ──► Top-5 给模型
   （快、粗）           （慢、准）          （少而精）
```

### 2、Rerank 模型

Rerank 模型（Cross-Encoder）和 Embedding 模型（Bi-Encoder）的区别：

- **Embedding**：问题和文档**分别**编码成向量，算距离。快，但精度有限。
- **Rerank**：问题和文档**一起**输入模型，直接输出相关性分数。慢，但准得多。

因为慢，所以只对少量候选做；因为准，所以能大幅提升最终上下文的质量。

```java
// Spring AI 里的 Rerank 用法（示意）
List<Document> candidates = vectorStore.similaritySearch(
        SearchRequest.builder().query(q).topK(50).build());

List<Document> reranked = rerankModel.rerank(q, candidates, 5);
```

**Rerank 通常是"性价比最高的一步优化"**：改动小，效果提升明显。检索效果不好时，除了调切分，最该试的就是加 Rerank。

## 七、Query Rewrite 与多路召回

用户的问题往往不适合直接检索。

### 1、Query Rewrite

多轮对话里，用户的提问常常有省略和指代：

```text
用户：年假有几天？
用户：那病假呢？
```

第二句"那病假呢"，单独拿去检索，什么都检索不到。需要**改写成完整的问题**：

```text
改写后：病假有几天？
```

再比如口语化的问题，改写成更适合检索的形式：

```text
原始：我入职两年了能休几天假啊
改写：入职两年的年假天数
```

用模型做改写：

```java
String rewritten = chatClient.prompt()
        .system("把用户问题改写成适合检索的独立完整问题，只输出改写结果。")
        .user(history + "\n当前问题：" + question)
        .call()
        .content();
```

### 2、多查询扩展

一个问题可以从多个角度问，生成多个查询，分别检索，再合并：

```text
原始问题：年假怎么算

扩展查询：
  - 年假天数计算规则
  - 年假申请条件
  - 工龄与年假天数对照
```

每个查询检索一批，合并去重后再 Rerank。**多路召回能显著提升召回率**，代价是检索次数变多，延迟和成本上升。

### 3、HyDE

还有一种技巧叫 HyDE（Hypothetical Document Embeddings）：**先让模型"假装"写一个答案，再用这个答案去检索。**

原理是：答案和文档的表述风格更接近，用答案去检索比用问题检索更准。

```text
问题：入职两年有几天年假？
假想答案：根据公司规定，入职满一年享 5 天年假，满三年享 10 天……
→ 用这段假想答案去检索，更容易命中真正的制度文档
```

## 八、检索结果如何注入上下文

检索回来的是几段文本，怎么放进 Prompt 也有讲究。

### 1、基本结构

```java
String context = documents.stream()
        .map(d -> "【资料 " + d.getId() + "】" + d.getContent())
        .collect(Collectors.joining("\n\n"));

String prompt = """
        你是客服助手。只根据下面提供的资料回答问题。
        如果资料中没有相关信息，请明确说"资料中没有提到"。
        回答时请标注引用的资料编号。

        %s

        用户问题：%s
        """.formatted(context, question);
```

### 2、几个要点

- **明确要求"只依据资料回答"**：否则模型可能混入自己的知识，编造答案。
- **要求"没有就说没有"**：降低幻觉。
- **编号并要求引用**：方便溯源，用户能核对。
- **控制资料总量**：不是越多越好，无关资料反而干扰。一般 3~5 片合适。

### 3、Spring AI 的 Advisor

Spring AI 把"检索 + 注入"封装成了 Advisor，用起来很省事：

```java
ChatClient chatClient = ChatClient.builder(chatModel)
        .defaultAdvisors(
            QuestionAnswerAdvisor.builder(vectorStore).build()
        )
        .build();
```

进阶的检索增强（多路召回、Rerank、Query Rewrite）用 `RetrievalAugmentationAdvisor` 组合：

```java
Advisor ragAdvisor = RetrievalAugmentationAdvisor.builder()
        .queryTransformers(RewriteQueryTransformer.builder()
                .chatClientBuilder(chatClientBuilder).build())
        .documentRetriever(VectorStoreDocumentRetriever.builder()
                .vectorStore(vectorStore)
                .similarityThreshold(0.5)
                .topK(50)
                .build())
        .build();
```

## 九、RAG 评估：召回率、准确性与引用质量

RAG 最怕"感觉能用，但不知道好不好"。必须有一套评估方法。

### 1、拆开评估

RAG 由"检索"和"生成"两部分组成，要分开评。

**检索质量：**

- **召回率（Recall@K）**：正确的文档，有多少比例被检索到了。这是最关键的一项——**没召回来，后面全白搭。**
- **精确率（Precision@K）**：检索回来的，有多少是真正相关的。
- **MRR / NDCG**：考虑排序位置的指标，排得越靠前越好。

**生成质量：**

- **忠实度（Faithfulness）**：答案是不是完全基于检索到的资料，有没有编造。
- **答案相关性**：答案有没有回答用户的问题。
- **引用准确性**：标注的引用编号，是不是真的支持这句话。

### 2、怎么建评估集

准备一批"问题 + 标准答案 + 相关文档"的样本：

```text
问题：入职两年有几天年假？
标准答案：10 天。
相关文档：员工手册.pdf 第 12 页
```

然后跑一遍，看：

- 相关文档有没有被检索到（召回率）。
- 答案和标准答案是否一致（准确性）。
- 引用对不对（引用质量）。

评估集不用很大，**几十到上百条就能看出明显问题**。关键是覆盖典型场景和边界情况。

### 3、常见问题与对策

| 现象 | 可能原因 | 对策 |
| --- | --- | --- |
| 检索不到 | 切分太碎 / 缺关键词 | 调切分、加混合检索 |
| 检索到无关的 | 切片太大 / 缺 Rerank | 加 Rerank、调阈值 |
| 答案编造 | 没强调"只依据资料" | 改 Prompt、加引用要求 |
| 答非所问 | Query 没改写 | 加 Query Rewrite |
| 答案不全 | Top-K 太小 | 增大 Top-K |

## 十、RAG 与模型微调的区别

经常有人问："我是该做 RAG 还是微调？"先看两者的本质区别。

| 维度 | RAG | 微调（Fine-tuning） |
| --- | --- | --- |
| 解决什么 | 让模型"知道"新知识 | 让模型"学会"新能力/风格 |
| 知识更新 | 改文档即可，即时生效 | 要重新训练 |
| 成本 | 低，主要是检索成本 | 高，要数据、算力、时间 |
| 可溯源 | 能给出引用 | 不能 |
| 幻觉 | 相对可控（有资料约束） | 仍可能编造 |
| 适合 | 事实性知识问答 | 固定格式、特定风格、专有任务 |

一句话总结：

> **要"知识"，用 RAG；要"能力/风格"，用微调。**

而且这两者不冲突，可以组合：**先用微调让模型学会某个领域的表达方式和任务模式，再用 RAG 补上实时和私有的知识。**

大多数企业场景，**先上 RAG** 是更稳妥的选择：见效快、成本低、能溯源、易维护。只有当你发现"模型理解了资料，但输出格式总是不对"或者"需要模型掌握一种新的任务能力"时，才考虑微调。

## 十一、实践验证：搭一条完整的 RAG 链路

前面把 RAG 的每个环节拆开讲了，这一节把它们串成一条能跑的链路：**解析 → 切分 → 向量化入库 → 检索 → 注入生成**。代码来自一个基于 Milvus 的 BI 查询项目。

### 1、技术选型

- **解析**：Apache Tika（`TikaDocumentReader`），支持 PDF、Word、Excel、Markdown。
- **向量化**：阿里云百炼的 `text-embedding-v3`（768 维）。
- **向量库**：Milvus 2.x。
- **检索增强**：Spring AI 的 `RetrievalAugmentationAdvisor`。

配置如下：

```yaml
spring:
  ai:
    dashscope:
      embedding:
        options:
          model: text-embedding-v3
          dimensions: 768
    vectorstore:
      milvus:
        client:
          host: "localhost"
          port: 19530
        collectionName: "vector_store"
        embeddingDimension: 768
        initialize-schema: true
```

### 2、解析与切分

用 Tika 读取上传的文件，再交给自定义的切分器：

```java
@Override
public void saveInVector(MultipartFile file) {
    // 1. 用 Tika 解析文件内容
    TikaDocumentReader reader = new TikaDocumentReader(file.getResource());
    List<Document> documents = reader.get();

    // 2. 按标题层级切分（前置标题路径，最小块 50 字符）
    TextSplitter splitter = new HeadingBasedSplitter(true, 50);
    documents = splitter.apply(documents);

    // 3. 存入 Milvus（Milvus 单次最多 10 个向量，分批写入）
    for (List<Document> batch : Lists.partition(documents, 8)) {
        vectorStore.add(batch);
    }
}
```

这里用的 `HeadingBasedSplitter` 是**按结构切分**的思路：识别 `1.`、`1.1`、`2.3.1` 这类数字标题，按标题层级切块，并把**完整标题路径前置**到每块开头：

```text
1. 概述 > 1.1 背景
（这一节的正文……）
```

这样切出来的块，检索时能带上上下文，语义更完整——正是前面讲的"按结构切分"。

### 3、检索与注入

检索不用手写，直接用 `RetrievalAugmentationAdvisor` 把三个环节串起来：

```java
RetrievalAugmentationAdvisor advisor = RetrievalAugmentationAdvisor.builder()
        // ① 查询改写：把用户的话改写成更适合检索的形式
        .queryTransformers(RewriteQueryTransformer.builder()
                .chatClientBuilder(builder)
                .build())
        // ② 向量检索：从 Milvus 检索相关文档，相似度阈值 0.50
        .documentRetriever(VectorStoreDocumentRetriever.builder()
                .similarityThreshold(0.50)
                .vectorStore(vectorStore)
                .build())
        // ③ 上下文增强：把检索到的内容拼进 Prompt
        .queryAugmenter(ContextualQueryAugmenter.builder()
                .allowEmptyContext(true)
                .build())
        .build();

Flux<String> flux = builder.build().prompt()
        .system("""
                你是一名 DBA SQL 专家，根据企业数据表结构生成 SQL。
                表名和字段名必须严格使用 RAG 检索结果中的名称，禁止推测或编造。
                仅生成 SELECT 语句。
                """)
        .user(userInput)
        .advisors(advisor)      // 挂上 RAG 顾问
        .stream().content();
```

对照前面的 RAG 架构图，这里的三个组件一一对应：

| 前面讲的环节 | 代码 |
| --- | --- |
| Query Rewrite | `RewriteQueryTransformer` |
| 向量检索 | `VectorStoreDocumentRetriever` |
| 注入上下文 | `ContextualQueryAugmenter` |

### 4、运行

先上传一份数据字典文档：

```bash
curl -F "file=@db-schema.md" http://localhost:8092/document/upload
```

再用自然语言提问：

```bash
curl "http://localhost:8092/genSql/test?userInput=查询库存数量大于100的商品"
```

日志里能看到检索和生成的过程：

```text
genSqlNode res=>SELECT p.product_name AS '商品名称', i.quantity AS '库存数量'
                FROM bb_product p JOIN bb_inventory i ON p.id = i.product_id
                WHERE i.quantity > 100
```

![image-20261011104000001](assets/image-20261011104000001.png)

![image-20261011104000002](assets/image-20261011104000002.png)

### 5、这一步验证了什么

- **RAG 链路是完整的**：Tika 解析 → 按标题切分 → Embedding 入库 → 检索 → 注入，五步都落到了代码。
- **切分策略直接影响效果**：`HeadingBasedSplitter` 把标题路径前置，让每块自带上下文——这印证了"切分决定检索上限"。
- **检索不只是向量检索**：`RetrievalAugmentationAdvisor` 把 Query Rewrite 和检索组合在一起，对应"Query Rewrite 与多路召回"一节。
- **注入上下文要下约束**：System Prompt 里明确"表名必须来自检索结果，禁止编造"，这正是"检索结果如何注入上下文"一节强调的——**用 Prompt 把模型的发挥空间收窄到检索结果之内**。

> 这里的文档是数据字典，模型检索到表结构后生成 SQL。`similarityThreshold` 和切分粒度都要靠评估集调，不是拍脑袋定的——对应前面"RAG 评估"一节。

## 小结

这一篇把 RAG 从头到尾过了一遍：

- RAG 的思路是**先检索、再生成**，让模型"会读"而不是"记住"。
- **切分决定检索上限**：按结构递归切、留重叠、做好清洗、带上元数据。
- **Embedding** 把语义变成向量，建库和检索必须用同一个模型。
- **向量库**用 ANN 做近似检索，中小项目 pgvector 很划算。
- **Metadata 过滤 + 混合检索（向量 + 关键词）**能大幅提升召回。
- **Rerank** 是性价比最高的一步优化：先粗召回，再精排。
- **Query Rewrite、多路召回、HyDE** 解决"问题不适合直接检索"。
- 注入上下文时，要**要求只依据资料、要求引用、控制数量**。
- 评估要**拆开看检索和生成**，重点是召回率和忠实度。
- **要知识用 RAG，要能力用微调**，两者可以组合。

RAG 解决了"知识"的问题，但 Agent 在多轮对话和长任务里，还有另一个问题要解决：**它得记住之前发生了什么。** 下一篇：《Agent 状态与记忆机制》。
