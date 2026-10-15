+++
title = "Kafka 的消费与可靠性"
date = 2026-10-09T15:31:52+08:00
weight = 13
tags = ["Kafka", "消费者组", "Offset", "Rebalance", "运维"]
summary = "Kafka 系列（四）：讲清消费者组、Offset 提交与 Rebalance，以及 Kafka 保证消息可靠性的关键配置。"

+++

本篇承接上一篇的生产侧。这一篇转到消费侧，讲清消费者组怎么分工、Offset 存在哪、Rebalance 是什么，最后落到 Kafka 保证消息可靠性的几个关键配置。

## 一、消费者组与分区分配

消费消息的单位是消费者组（consumer group），每个消费者通过 `group.id` 声明自己属于哪个组。Kafka 有一条核心规则：

**同一个消费者组内，一个分区在同一时刻只会分配给一个消费者。**

这条规则决定了几件事：

- 一个组里的消费者越多，能并行消费的分区越多。当消费者数量超过分区数时，多出来的消费者会分不到分区，处于空闲状态。
- 因为一个分区只给一个消费者，所以组内的消费是"分工"的，不会重复读同一个分区。
- 不同的消费者组之间互不影响，各自维护自己的进度。这也是入门篇里"一份消息多个业务各读一遍"能成立的原因。

组内怎么分配分区，由 `partition.assignment.strategy` 决定，常用的有：

- `RangeAssignor`：按 Topic 逐个分配，把分区按范围切给消费者。
- `RoundRobinAssignor`：把所有分区轮询着分给消费者。
- `StickyAssignor`：尽量保持上一次的分配结果，减少 rebalance 时的变动。
- `CooperativeStickyAssignor`：在 Sticky 的基础上支持增量 rebalance，进一步减少停顿。

## 二、Offset 存在哪里

入门篇里我们用 `--describe` 看到过 Offset，这一篇说说它到底存在哪。

消费者提交的进度，Kafka 会写进一个内部主题 `__consumer_offsets`。它的 key 是"消费者组 + Topic + 分区"，value 就是对应的 offset。也就是说，消费进度本身也是 Kafka 里的一条消息，同样有副本、同样会被保存。

提交方式有两种：

- **自动提交**：`enable.auto.commit=true`（默认），消费者在 `poll()` 时按 `auto.commit.interval.ms`（默认 5 秒）自动提交。
- **手动提交**：`enable.auto.commit=false`，由代码在合适的时候调用 `commitSync()` 或 `commitAsync()`。

提交的时机，直接决定了消息会被"重复"还是"丢失"：

- 先处理、后提交：处理完再提交，如果提交前挂了，下次会重新处理这条消息 → **至少一次（at-least-once）**。
- 先提交、后处理：提交完再处理，如果处理前挂了，这条消息就再也不会被处理 → **最多一次（at-most-once）**。

实际业务里几乎都用"先处理、后提交"的至少一次语义，再配合业务幂等来消化重复，这部分放到下一篇讲。

另外还有一个容易踩坑的参数 `auto.offset.reset`：当消费者组找不到已提交的 offset（比如第一次消费）时，决定从哪开始读。`earliest` 从头读，`latest` 从最新开始（默认），`none` 直接报错。

## 三、实验：查看消费进度

我们启动一个消费者，指定组名：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-console-consumer.sh --topic demo --group my-group --bootstrap-server localhost:9092
```

在另一个终端查看这个组的状态：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group my-group
```

输出大致如下：

```text
GROUP      TOPIC  PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG  CONSUMER-ID     HOST        CLIENT-ID
my-group   demo   0          5               5               0    consumer-1-...  /127.0.0.1  consumer-1
my-group   demo   1          3               3               0    consumer-1-...  /127.0.0.1  consumer-1
my-group   demo   2          4               4               0    consumer-1-...  /127.0.0.1  consumer-1
```

三个分区都被同一个消费者拿走了。`CURRENT-OFFSET` 是当前读到哪，`LOG-END-OFFSET` 是最新消息在哪，`LAG` 是两者之差。LAG 一直增长，就说明消费跟不上了。

还可以看成员和状态：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group my-group --members
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group my-group --state
```

## 四、Rebalance

当消费者组的成员发生变化时，分区会重新分配，这个过程就叫 Rebalance（再平衡）。

触发 Rebalance 的常见情况：

- 有新的消费者加入组。
- 有消费者退出（主动关闭，或者心跳超时被踢出）。
- 订阅的 Topic 或分区数发生变化。

Rebalance 的过程大致是：所有消费者先放弃手头的分区，重新加入组，由组协调者重新分配，再各自拿到新的分区。在旧的 eager 模式下，整个过程会暂停消费，也就是常说的"Stop The World"。

我们用实验看一下。上面已经有一个消费者在跑，现在再开一个同组的消费者：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-console-consumer.sh --topic demo --group my-group --bootstrap-server localhost:9092
```

等几秒，再查看成员：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group my-group --members
```

这时应该能看到两个成员，3 个分区被分给了 2 个消费者（比如一个拿 2 个、另一个拿 1 个）。把第二个消费者关掉，又会触发一次 Rebalance，分区重新回到剩下的那个消费者手里。

Rebalance 期间消费会短暂停顿，所以频繁的 Rebalance 会明显影响消费。常见的优化手段有：

- 合理设置 `session.timeout.ms` 和 `heartbeat.interval.ms`，避免因为短暂卡顿就被判定为掉线。
- 保证单次 `poll()` 的处理时间小于 `max.poll.interval.ms`，否则消费者会被踢出组。
- 使用静态成员（`group.instance.id`），让消费者重启后仍然算作同一个成员，避免一重启就触发 Rebalance。

## 五、消息可靠性三件套

说完消费，我们回到一个绕不开的问题：怎么保证消息不丢？Kafka 给了三个配合使用的配置：

- `replication.factor >= 3`：每个分区至少 3 份副本，容忍机器故障。
- `min.insync.replicas >= 2`：至少 2 个副本确认，才认为写入成功。
- `acks=all`：生产者等待所有 ISR 副本确认。

这三个要一起用才有效。以 3 副本、`min.insync.replicas=2`、`acks=all` 为例：

- 正常时 ISR 有 3 个，写入需要副本都确认。
- 挂掉 1 台，ISR 还剩 2 个，仍然满足 `min.insync.replicas=2`，写入继续。
- 再挂 1 台，ISR 只剩 1 个，小于 2，Broker 就会拒绝写入，返回 `NotEnoughReplicas`。

可以看到，这套组合保证的是：**只要写入成功，数据就一定在至少 2 个副本上**。反过来，当副本不足时，Kafka 宁可拒绝写入，也不假装成功。

## 六、实验：验证可靠性配置

先给 `demo` 设置 `min.insync.replicas=2`：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-configs.sh --bootstrap-server localhost:9092 --alter --entity-type topics --entity-name demo --add-config min.insync.replicas=2
```

确认一下：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-configs.sh --bootstrap-server localhost:9092 --describe --entity-type topics --entity-name demo
```

### 1、挂掉一台，写入仍然正常

停掉 node3，等 ISR 收缩到 2 个后，用 `acks=all` 生产：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-console-producer.sh --topic demo --bootstrap-server localhost:9092 --producer-property acks=all
>ISR 还有两个，可以写
```

这时 ISR 正好等于 `min.insync.replicas`，消息能正常写入。

### 2、再挂一台，写入被拒绝

再把 node2 停掉，只剩一个副本。这时 ISR 小于 2，用 `acks=all` 生产就会失败：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-console-producer.sh --topic demo --bootstrap-server localhost:9092 --producer-property acks=all
>这条会失败
```

生产者会收到 `NotEnoughReplicas`（或者重试后超时），消息不会被认为是发送成功。这就是可靠性配置在起作用：副本不足时，宁可不写。

有意思的是，如果换成 `acks=1`，同样的消息却能"发送成功"——因为它只等 Leader 确认，根本不检查 `min.insync.replicas`。但这份数据此刻只在一个副本上，一旦 Leader 再挂，就丢了。

最后把 node2、node3 重新启动，集群会恢复正常。

## 小结

这一篇我们讲了消费者组的分区分配、Offset 的存储与提交时机、Rebalance 的触发与优化，以及保证消息可靠性的三件套（`replication.factor`、`min.insync.replicas`、`acks=all`），并用实验验证了副本不足时写入会被拒绝。

下一篇，我们会接着"至少一次"这个前提，讲清消息为什么会重复、幂等性怎么分层解决，并用 Spring Boot 把生产和消费真正写出来。
