+++
title = "Agent 与数据库"
date = 2026-10-11T00:00:00+08:00
weight = 4
tags = ["Agent", "Text-to-SQL", "SQL 安全", "只读执行", "数据问答"]
summary = "进阶专题（四）：讲清 Text-to-SQL 的生成与校验、只读执行、结果解释，以及怎么把数据库问答做安全。"
+++

上一篇讲代码执行，这一篇讲它的一个重要特例：**让 Agent 用自然语言查数据库**。

用户问"上个月销售额是多少"，Agent 要能理解问题、生成 SQL、安全地执行、再把结果讲清楚。这套链路叫 **Text-to-SQL**，是企业里落地最广的 Agent 场景之一——因为几乎每个公司都有数据库，也几乎每个业务方都想要"用嘴查数据"。

但数据库是核心资产，一旦出事就是生产事故。所以这一篇的重点，和代码执行一样：**怎么做得准，更要做得安全。**

## 一、Text-to-SQL 的整体链路

先看全貌：

```text
用户问题
   │
   ▼
① 意图理解 + 检索表结构（RAG）
   │
   ▼
② 生成 SQL
   │
   ▼
③ SQL 校验（表名/字段名/语法/安全）
   │
   ├── 不合格 ──► 回到 ② 重新生成（有限次）
   │
   ▼
④ 只读执行（限行、超时）
   │
   ▼
⑤ 结果解释（把数据翻译成人话）
```

每一步都有坑，我们逐个看。

## 二、意图理解与表结构检索

### 1、模型不知道你的表结构

模型没有你数据库的 schema，所以直接让它写 SQL，它只能**编表名**：

```text
用户：上个月销售额是多少？
模型（凭空）：SELECT SUM(amount) FROM sales WHERE ...
                ↑ sales 这张表可能根本不存在
```

所以第一步必须**把真实的表结构喂给模型**。

### 2、表结构怎么给

数据库的表可能很多，全塞进去会撑爆上下文，也会干扰判断。所以用 **RAG 检索**：把表结构文档向量化，根据用户问题检索出**相关的几张表**。

```text
数据字典文档
├── bb_product   商品表：id, product_name, category, price, ...
├── bb_inventory 库存表：id, product_id, warehouse_id, quantity, ...
├── bb_sales     销售表：id, product_id, sale_date, amount, ...
└── ...（几十张表）
        │
        ▼ 按问题检索
用户问题："上个月各商品销售额" → 命中 bb_product + bb_sales
```

这和前面《RAG 与知识库增强》讲的是同一套思路，只是知识换成了"表结构"。

### 3、RAG 增强的 SQL 生成

把检索和生成串起来，用 `RetrievalAugmentationAdvisor`：

```java
RetrievalAugmentationAdvisor advisor = RetrievalAugmentationAdvisor.builder()
        .documentRetriever(VectorStoreDocumentRetriever.builder()
                .similarityThreshold(0.50)
                .vectorStore(vectorStore)
                .build())
        .queryAugmenter(ContextualQueryAugmenter.builder()
                .allowEmptyContext(true)
                .build())
        .build();

Flux<String> flux = chatClient.prompt()
        .system("""
                # 角色
                你是 DBA SQL 专家，根据企业数据表结构生成 SQL。

                # 核心规则
                1. 表名和字段名必须严格使用 RAG 检索结果中的名称，禁止推测或编造。
                2. 仅生成可执行的 SELECT 语句，禁止 DELETE / DROP / UPDATE / INSERT。
                3. 仅输出纯 SQL，不要 markdown 代码块，不要任何解释。
                4. 每个查询字段用 AS 指定中文别名。
                """)
        .user(userInput)
        .advisors(advisor)
        .stream().content();
```

**System Prompt 里的几条规则，是整个链路安全的第一道闸**：

- "必须用检索到的表名" → 治幻觉。
- "只生成 SELECT" → 治危险操作。
- "只输出纯 SQL" → 保证输出能被程序直接执行。

## 三、SQL 校验：不能只信模型

生成完 SQL，绝对不能直接拿去执行。**校验是必须的，而且要分层。**

### 1、第一层：结构校验

先做**机器能做的硬校验**，不依赖模型。

**（1）只允许 SELECT**

```java
private boolean isSafeSql(String sql) {
    if (StrUtil.isBlank(sql)) return false;
    String upper = sql.trim().toUpperCase();

    // 必须以 SELECT 开头
    if (!upper.startsWith("SELECT")) return false;

    // 出现任何危险关键字就拒绝
    String[] dangerous = {"DROP", "DELETE", "UPDATE", "INSERT",
                          "ALTER", "CREATE", "TRUNCATE", "GRANT", "REVOKE"};
    for (String kw : dangerous) {
        if (upper.contains(kw)) return false;
    }
    return true;
}
```

**（2）表名和字段名必须真实存在**

这一步很关键。用数据库元数据核对：

```java
// 从 JDBC 元数据取出真实存在的表名
Set<String> realTables = jdbcTemplate.execute(
        (ConnectionCallback<Set<String>>) conn -> {
            Set<String> tables = new HashSet<>();
            try (ResultSet rs = conn.getMetaData()
                    .getTables(null, null, "%", new String[]{"TABLE"})) {
                while (rs.next()) {
                    tables.add(rs.getString("TABLE_NAME").toLowerCase());
                }
            }
            return tables;
        });

// 校验 SQL 里用到的表是否都存在
for (String table : extractTables(sql)) {
    if (!realTables.contains(table.toLowerCase())) {
        return "SQL 使用了不存在的表：" + table;
    }
}
```

**为什么要硬校验？** 因为模型"自评"也会犯错。前面《Agent 评估、可观测性与安全》讲过：**权限和安全必须落在代码里，不能指望 Prompt。** 表名存在性这种能程序判断的事，就别交给模型。

**（3）自动加 LIMIT**

```java
private String addLimit(String sql, int maxRows) {
    String trimmed = sql.trim();
    if (trimmed.endsWith(";")) {
        trimmed = trimmed.substring(0, trimmed.length() - 1);
    }
    if (trimmed.toUpperCase().contains("LIMIT")) return trimmed;
    return trimmed + " LIMIT " + maxRows;
}
```

防止一次 `SELECT * FROM 大表` 把内存和网络打爆。

### 2、第二层：模型校验（自评自纠）

硬校验只能查"格式和存在性"，查不了**"SQL 有没有正确回答用户问题"**。这部分要靠模型。

做法是加一个**评估节点**，用 RAG 的表结构去核对：

```java
Flux<String> flux = chatClient.prompt()
        .system("""
                # 角色
                你是 MySQL SQL 审查专家，评估生成的 SQL 的质量、正确性和安全性。

                # 评估标准（按优先级）:
                1. 表名和字段名校验（最关键）
                   - 必须与 RAG 检索到的表结构完全一致
                   - 出现不存在的表名或字段名，必须判 FAIL
                2. 语法正确性
                3. 语义准确性：是否准确反映用户意图
                4. 执行安全性：出现 DELETE / UPDATE / DROP 必须 FAIL
                5. 性能：是否有笛卡尔积、是否缺少关键过滤

                # 输出要求
                只输出 PASS 或 FAIL，不要输出任何其他内容
                """)
        .user("用户问题：" + userInput + "\n请评估以下 SQL：\n" + genSql)
        .advisors(advisor)
        .stream().content();
```

### 3、校验不通过怎么办：循环重试

评估结果用**条件边**路由：不合格就回到生成节点重来。

```text
        genSqlNode ◄──────────────┐
            │                     │
            ▼                     │ FAIL 重试
        evaluateNode              │
            │                     │
      [EvaluateEdge] ─────────────┘
         │        │
       PASS      空结果/超循环
         │        │
         ▼        ▼
      execNode   END
```

```java
public class EvaluateEdge implements EdgeAction {
    @Override
    public String apply(OverAllState state) throws Exception {
        String result = state.value(KEY_EVALUATE_RESULT, "");
        Integer loop = state.value(KEY_LOOP, 0);

        // 空结果或超过最大循环次数 → 结束（防止死循环）
        if (StrUtil.isBlank(result) || loop >= maxLoop) {
            return StateGraph.END;
        }
        if ("PASS".equals(result)) {
            return NODE_EXEC;      // 通过，去执行
        } else {
            return NODE_GEN_SQL;   // 不通过，重新生成
        }
    }
}
```

**"自评 + 重试"是 Text-to-SQL 提升准确率最有效的手段之一。** 但一定要有 `maxLoop` 上限，否则可能无限重试。

## 四、只读执行

代码生成好、校验过，就到了执行环节。执行的原则是四个字：**只读、受限**。

### 1、用只读账号

**最根本的一道防线**：执行 SQL 的数据库账号，**只有 SELECT 权限**。

```sql
-- 只给查询权限，不给写权限
CREATE USER 'agent_ro'@'%' IDENTIFIED BY '...';
GRANT SELECT ON biz_db.* TO 'agent_ro'@'%';
```

这样即使前面所有校验都失效，数据库层面也写不进去。**纵深防御**：不指望单点防护，而是每层都挡一下。

### 2、执行超时

```java
// 给查询设超时，防止慢查询拖垮数据库
jdbcTemplate.setQueryTimeout(30);
```

一个没走索引的 `SELECT * FROM 亿级表` 能跑几分钟，拖垮数据库连接池。

### 3、限行

前面校验阶段已经加了 `LIMIT`，执行阶段再兜一次：

```java
if (!limitedSql.toUpperCase().contains("LIMIT")) {
    limitedSql += " LIMIT " + maxRows;
}
```

### 4、结果也要受限

查回来的结果不能原样返回：

```text
✅ 总数 + 前 N 条：
   {"total": 5321, "showing": 100, "rows": [...]}

❌ 五万行原始数据全塞给模型
```

**"总数 + 样本"是标准做法**：既告诉模型数据规模，又不撑爆上下文。

## 五、结果解释

SQL 执行完，拿到的是**表格数据**，但用户要的是**答案**。这一步是"把数据翻译成人话"。

### 1、为什么要单独解释

直接返回表格，用户（尤其是不会 SQL 的业务方）看不懂：

```text
❌ 直接返回：
   product_name | sales_amount
   手机         | 1250000
   电脑         | 980000
   ...

✅ 解释后：
   上个月销售额最高的商品是手机，约 125 万元；
   其次是电脑，约 98 万元。前两名合计占总销售额的 63%。
```

### 2、解释时要带约束

解释也不能随便编，要把数据和问题一起给模型，并要求**只依据数据说话**：

```text
system:
你是一个数据分析助手。根据下面的查询结果回答用户的问题。
要求：
1. 只依据数据回答，不要编造数据中没有的信息。
2. 给出结论时附上关键数字。
3. 数据不足以回答时，明确说"数据不足"。

用户问题：{question}
查询结果：{resultJson}
```

### 3、给结果加"可信度信息"

一个实用的做法是**把执行元信息也告诉用户**：

```text
【查询结果】
上个月销售额最高的是手机，约 125 万元。

（数据来源：bb_sales 表，查询时间 2026-10-11，命中 5321 行取前 100 行）
```

这样用户知道数据是怎么来的、有没有被截断，**比"黑盒给个答案"可信得多**。

## 六、常见坑

### 1、时间范围的歧义

"上个月"到底指自然月还是滚动 30 天？"最近"是几天？

对策：**明确时间口径**，在 Prompt 里定义清楚，或者干脆追问用户。

```text
"上个月" → 上一个自然月（1 号到月末）
"本月至今" → 当月 1 号到今天
```

### 2、聚合口径的歧义

"销售额"是含税还是不含税？"订单数"是订单条数还是去重用户数？

对策：把这些业务口径**写进数据字典**，让 RAG 检索到。

### 3、多表连接的幻觉

模型可能把两个不相关的表连起来，或者连错字段。

对策：**在数据字典里明确表之间的关系**（外键、常用连接方式），并靠"表名/字段名硬校验"兜底。

### 4、模型自己发明字段

```sql
-- 模型凭空写了个 stock_quantity，实际字段叫 quantity
SELECT stock_quantity FROM bb_inventory
```

对策：硬校验字段名是否存在（用 JDBC 元数据取列信息），不存在就返回错误让模型改。

## 七、实践验证：一条完整的 Text-to-SQL 链路

这一节看 `double-ai-agent` 项目里完整的 BI 查询链路。

### 1、整体图结构

```java
StateGraph graph = new StateGraph("biGraph", () -> Map.of(
        KEY_USER_INPUT, new ReplaceStrategy(),
        KEY_GEN_SQL_RESULT, new ReplaceStrategy(),
        KEY_EXCEL_BYTES, new ReplaceStrategy()
));

// 节点
graph.addNode(NODE_GEN_SQL,  AsyncNodeAction.node_async(new GenSqlNode(builder, vectorStore)));
graph.addNode(NODE_EVALUATE, AsyncNodeAction.node_async(new EvaluateNode(builder, vectorStore)));
graph.addNode(NODE_EXEC,     AsyncNodeAction.node_async(new ExecSqlAndConvertExcelNode(jdbcTemplate, limit)));
graph.addNode(NODE_SEND_EMAIL, AsyncNodeAction.node_async(new SendEmailNode(emailSendService)));

// 边：START → 生成 → 评估
graph.addEdge(StateGraph.START, NODE_GEN_SQL);
graph.addEdge(NODE_GEN_SQL, NODE_EVALUATE);

// 条件边：评估结果决定走向（PASS→执行，FAIL→重新生成，超循环→结束）
graph.addConditionalEdges(NODE_EVALUATE,
        AsyncEdgeAction.edge_async(new EvaluateEdge(loop)),
        Map.of(NODE_EXEC, NODE_EXEC,
               NODE_GEN_SQL, NODE_GEN_SQL,
               StateGraph.END, StateGraph.END));

graph.addEdge(NODE_EXEC, NODE_SEND_EMAIL);
graph.addEdge(NODE_SEND_EMAIL, StateGraph.END);
```

### 2、执行节点的双重安全检查

```java
@Override
public Map<String, Object> apply(OverAllState state) throws Exception {
    String genSql = state.value(KEY_GEN_SQL_RESULT, "");
    if (StrUtil.isBlank(genSql)) return Map.of();

    // ① 安全校验：只允许 SELECT
    if (!isSafeSql(genSql)) {
        log.error("检测到不安全的 SQL 语句: {}", genSql);
        throw new IllegalArgumentException("不允许执行此 SQL 语句，仅支持 SELECT 查询");
    }

    // ② 自动加 LIMIT，防结果过大
    String limitedSql = addLimitToQuery(genSql, limit);

    // ③ 执行查询
    List<Map<String, Object>> res = jdbcTemplate.queryForList(limitedSql);

    // ④ 结果转 Excel
    byte[] excelBytes = ExcelUtil.convertToExcel(res, "查询结果");
    return Map.of(KEY_EXCEL_BYTES, excelBytes);
}
```

**注意第 ① 步的双保险**：

```java
private boolean isSafeSql(String sql) {
    String upper = sql.trim().toUpperCase();
    if (!upper.startsWith("SELECT")) return false;              // 必须 SELECT 开头
    String[] dangerous = {"DROP","DELETE","UPDATE","INSERT",
                          "ALTER","CREATE","TRUNCATE","GRANT","REVOKE"};
    for (String kw : dangerous) {
        if (upper.contains(kw)) return false;                    // 含危险词就拒
    }
    return true;
}
```

### 3、生成的 SQL 示例

```sql
SELECT p.product_name AS '商品名称',
       SUM(s.amount)  AS '销售额'
FROM bb_sales s
JOIN bb_product p ON s.product_id = p.id
WHERE s.sale_date >= '2026-09-01' AND s.sale_date < '2026-10-01'
GROUP BY p.product_name
ORDER BY SUM(s.amount) DESC
LIMIT 100
```

对照前面讲的规则：**表名来自检索（`bb_product`/`bb_sales`）、字段名真实、只有 SELECT、有中文别名、带了 LIMIT。**

![image-20261011114000001](assets/image-20261011114000001.png)

![image-20261011114000002](assets/image-20261011114000002.png)

### 4、这一步验证了什么

- **RAG 检索表结构是准确率的前提**：不检索，模型就编表名。
- **校验要分层**：硬校验（SELECT、危险词、表名存在）+ 模型评估（语义是否正确）双管齐下。
- **自评自纠要闭环**：评估 + 条件边 + 重试，但必须有 `maxLoop` 上限。
- **只读执行**：只读账号 + 超时 + LIMIT，纵深防御。
- **结果要解释**：返回"总数 + 样本"，并附上数据来源。

> 这条链路里，**硬校验是不能省的**。模型评估能提升准确率，但"是否含 DROP""表名是否存在"这类判断，必须由代码来做——因为模型是可能被诱导的。这也是前面安全篇反复强调的原则：安全逻辑写在代码里，不写在 Prompt 里。

## 小结

这一篇把 Agent 查数据库讲透了：

- **Text-to-SQL 的链路**：意图理解 + 表结构检索 → 生成 → 校验 → 只读执行 → 结果解释。
- **表结构要靠 RAG 给**，否则模型只能编表名。
- **校验要分层**：结构硬校验（SELECT / 危险词 / 表名存在 / 加 LIMIT）+ 模型语义评估。
- **校验不通过要循环重试**，但必须有上限。
- **只读执行**是根本：只读账号 + 查询超时 + 限行，做纵深防御。
- **结果要解释**：把表格翻译成人话，带上"总数 + 样本"和数据来源。
- **常见坑**：时间口径、聚合口径、多表连接、凭空造字段——靠数据字典和硬校验解决。

下一篇：《Agent 长任务管理》——讲 Agent 跑几十分钟甚至几小时的任务时，怎么用检查点保存进度、怎么暂停恢复、怎么处理审批和补偿。
