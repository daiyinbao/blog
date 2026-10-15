+++
title = "几种消息队列的对比"
date = 2026-10-09T15:31:52+08:00
weight = 15
tags = ["Kafka", "RabbitMQ", "RocketMQ", "Pulsar", "消息队列", "运维"]
summary = "Kafka 系列（番外）：横向对比 Kafka、RabbitMQ、RocketMQ、Pulsar 的原理与异同，给出一份选型参考。"

+++

前面五篇都在讲 Kafka。这一篇跳出来，横向看看几种常见的消息队列，讲清它们各自的原理和差异，也顺便回答一个经常被问到的问题：到底该选哪个。

## 一、为什么要有这篇对比

消息队列不止 Kafka 一种。同样是"发消息、收消息"，不同的实现背后是完全不同的设计，适合的场景也不一样。选型时通常要看这几个维度：

- 消息模型：是队列还是日志。
- 投递语义：最多一次、至少一次，还是精确一次。
- 顺序性：全局有序还是分区有序。
- 吞吐与延迟：追求吞吐，还是追求低延迟。
- 事务、幂等、重放等能力。
- 运维成本和生态。

这一篇对比四个最有代表性的：RabbitMQ、RocketMQ、Kafka、Pulsar。

## 二、先分清两种模型：队列与日志

在对比之前，先建立一个最基本的区分。

- **队列模型（Queue）**：生产者把消息投递到队列，消费者从队列里取走，取走后消息就从队列中删除。一条消息通常只会被一个消费者消费。RabbitMQ 是典型代表。
- **日志模型（Log）**：消息被顺序追加到日志里，消费者按 offset 读取，读完之后消息依然保留。不同的消费者组可以各自读同一份数据。Kafka、Pulsar 属于这一类。

这个差异，几乎决定了后面所有的对比结论：

- 能不能重放：日志模型可以，队列模型不行（消费即删除）。
- 能不能让多个业务订阅同一份数据：日志模型天然支持，队列模型要靠交换机转发到多个队列。
- 顺序性和并行的处理方式也不同。

## 三、几种消息队列的原理简述

### 1、RabbitMQ

RabbitMQ 用 Erlang 编写，实现的是 AMQP 协议。它的核心模型是：

```text
Producer → Exchange --(Binding)--> Queue → Consumer
```

生产者不直接把消息发给队列，而是先发给 Exchange（交换机），由 Exchange 根据 Binding（绑定规则）把消息路由到一个或多个队列。Exchange 有 direct、topic、fanout、headers 等类型，路由方式非常灵活。

消息被消费者取走并 ack 之后，就会从队列里删除。它还有几个好用的特性：死信队列、延迟队列（TTL + 死信）、优先级队列。

RabbitMQ 的特点是路由灵活、延迟低，但单机吞吐一般，更适合业务解耦、任务分发这类场景。

### 2、RocketMQ

RocketMQ 是阿里开源的 Java 消息队列。它的存储模型比较特别：所有消息都顺序写进一个 CommitLog，再异步构建出 ConsumeQueue（逻辑队列，记录消息在 CommitLog 里的位置）和 IndexFile（按 key 查询的索引）。

这种设计兼顾了顺序写的性能和按队列消费的便利。RocketMQ 还支持几个 Kafka 早期不太擅长的能力：

- 顺序消息：同一个队列内的消息严格有序。
- 事务消息：通过"半消息 + 事务回查"实现。
- 延迟消息：支持固定级别的延迟。

它的特点是高吞吐、低延迟、支持事务消息，在国内电商、金融场景里用得很多。

### 3、Kafka

Kafka 最初是为日志处理设计的，核心是分区 + 副本 + 消费者组。

消息按分区顺序追加写到磁盘，用 segment 分文件、稀疏索引定位，配合页缓存、批量发送、零拷贝，把吞吐做到了极高。消费者用 offset 记录进度，支持重放；副本 + ISR 保证可靠性。

前面几篇已经把它的原理讲得很细了，这里只强调一点：Kafka 的定位是"分布式事件流平台"，除了消息传递，还有 Connect、Streams 这样的数据集成和流处理生态，适合日志采集、数据管道、事件驱动这些场景。

### 4、Pulsar

Pulsar 的架构和前三者都不一样，它是存算分离的：

- Broker 层：无状态，负责协议处理、消息路由。
- 存储层：用 BookKeeper（Bookie 节点）持久化消息。

计算和存储分开之后，扩缩容会更灵活。Pulsar 同时支持多种订阅类型（Exclusive、Failover、Shared、Key_Shared），既能当队列用，也能当流用。它还支持多租户、跨地域复制和分层存储。

Pulsar 的特点是架构先进、扩展性好，但组件更多，运维也更复杂。

## 四、横向对比

把四个放在一起看：

| 维度 | Kafka | RabbitMQ | RocketMQ | Pulsar |
| --- | --- | --- | --- | --- |
| 消息模型 | 日志（分区） | 队列 | 队列 + 日志式存储 | 日志（分区） |
| 开发语言 | Scala / Java | Erlang | Java | Java |
| 协议 | 自定义 | AMQP、MQTT、STOMP | 自定义 | 自定义（兼容 Kafka 协议） |
| 投递语义 | 至少一次、EOS | 最多一次、至少一次 | 至少一次 | 至少一次、EOS |
| 顺序性 | 分区内有序 | 队列内有序 | 队列内有序 | 分区内有序 |
| 吞吐 | 极高 | 中等 | 高 | 高 |
| 延迟 | 毫秒级 | 微秒 ~ 毫秒 | 毫秒级 | 毫秒级 |
| 消息重放 | 支持 | 不支持（消费即删） | 有限支持 | 支持 |
| 事务消息 | 支持 | 不支持 | 支持 | 支持 |
| 扩展性 | 好 | 一般 | 好 | 很好（存算分离） |
| 典型场景 | 日志、流处理、数据管道 | 业务解耦、任务分发 | 电商、金融 | 多租户、大规模流 |

几个值得展开的差异：

- **消息模型**：这是最根本的区别。Kafka、Pulsar 是日志，消费不影响消息本身，所以能重放、能多组订阅；RabbitMQ 是队列，消费即删除。
- **投递语义**：RabbitMQ 主要提供最多一次和至少一次；Kafka、Pulsar 还支持事务和端到端 EOS；RocketMQ 提供至少一次加事务消息。
- **顺序性**：四者都不提供真正的全局顺序，而是"局部有序"——Kafka、Pulsar 是分区内有序，RabbitMQ、RocketMQ 是队列内有序。要全局有序，通常只能单分区、单队列，牺牲并行能力。
- **吞吐与延迟**：Kafka、RocketMQ、Pulsar 都在吞吐上做了大量优化（顺序写、批量、零拷贝）；RabbitMQ 更偏重低延迟和灵活路由。
- **事务**：Kafka 和 Pulsar 支持端到端事务；RocketMQ 有事务消息（半消息 + 回查）；RabbitMQ 只有确认机制和 AMQP 本地事务，不解决跨系统一致性。

## 五、动手感受两种模型的差异

我们用 Kafka 和 RabbitMQ 各做一个最小实验，感受"日志模型"和"队列模型"的区别。

### 1、Kafka：消息读完之后还在

用前面系列里的命令，先用 `group-a` 读走一条消息，再换一个消费者组 `group-b`，加上 `--from-beginning`，还能把同一条消息读出来：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-console-consumer.sh --topic test --group group-b --from-beginning --bootstrap-server localhost:9092
```

### 2、RabbitMQ：消息读走就没了

先用 Docker 起一个带管理插件的 RabbitMQ：

```bash
daiyinbao@debian13:~$ docker run -d --name rabbitmq -p 5672:5672 -p 15672:15672 rabbitmq:3-management
```

声明一个队列，然后发一条消息：

```bash
daiyinbao@debian13:~$ curl -u guest:guest -X PUT "http://localhost:15672/api/queues/%2F/hello" -H "Content-Type: application/json" -d '{"durable":true}'
daiyinbao@debian13:~$ curl -u guest:guest -X POST "http://localhost:15672/api/exchanges/%2F/amq.default/publish" -H "Content-Type: application/json" -d '{"properties":{},"routing_key":"hello","payload":"hello rabbitmq","payload_encoding":"string"}'
```

取走这条消息：

```bash
daiyinbao@debian13:~$ curl -u guest:guest -X POST "http://localhost:15672/api/queues/%2F/hello/get" -H "Content-Type: application/json" -d '{"count":1,"ackmode":"ack_requeue_false","encoding":"auto"}'
```

会返回刚发的那条消息。再取一次：

```bash
daiyinbao@debian13:~$ curl -u guest:guest -X POST "http://localhost:15672/api/queues/%2F/hello/get" -H "Content-Type: application/json" -d '{"count":1,"ackmode":"ack_requeue_false","encoding":"auto"}'
```

返回的是空数组 `[]`。同一条消息，取走之后就真的没了——这就是队列模型和日志模型最直观的差别。

## 六、怎么选

- 海量日志、数据管道、事件流，需要高吞吐和回放 → Kafka
- 复杂路由、延迟队列、逐条确认、低延迟 → RabbitMQ
- 事务消息、顺序消息、国内电商 / 金融生态 → RocketMQ
- 多租户、大规模、想要存算分离和跨地域复制 → Pulsar

当然，实际选型还要看团队的技术栈、运维能力和已有的基础设施。比如已经在用 Spring 生态，RabbitMQ 和 Kafka 都有成熟的集成；已经有大数据平台，Kafka 往往更顺手。

## 七、小结

这一篇对比了 RabbitMQ、RocketMQ、Kafka、Pulsar 四种消息队列。它们的差异，归根到底来自两个最基础的选择：**消息模型是队列还是日志**，以及**在吞吐、延迟、可靠性之间怎么取舍**。

没有最好的消息队列，只有最合适的。理解它们各自的原理，才能在选型时说得清"为什么是它"。
