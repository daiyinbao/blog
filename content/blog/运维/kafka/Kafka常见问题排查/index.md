+++
title = "Kafka 常见问题排查"
date = 2026-10-09T15:31:52+08:00
weight = 16
tags = ["Kafka", "消息丢失", "消息积压", "消息顺序", "运维"]
summary = "Kafka 系列（六）：排查消息丢失、顺序错乱、消息积压、死信、大消息与消费反压等常见问题。"

+++

前面几篇把 Kafka 的原理和用法讲了一遍。这一篇换个角度，把实际使用中最常遇到的问题拿出来，逐个说清原因和解决方式。

## 一、消息丢失

消息可能在三个环节丢掉：生产端、存储端、消费端。排查时按这三段分别看。

### 1、生产端

生产端丢消息，通常是因为没有等确认就认为发送成功。

- `acks=0`：生产者发出去就不管了，Broker 有没有收到都不知道，最不可靠。
- `acks=1`：只等 Leader 确认。如果 Leader 刚写完就挂了，而 Follower 还没同步，这条消息就丢了。
- `acks=all`：等所有 ISR 副本确认，最可靠。

所以生产端要做的，是把 `acks=all`、`retries>0`、`enable.idempotence=true` 一起打开，并且**处理发送失败的回调**：

```java
kafkaTemplate.send("demo", key, value)
    .whenComplete((result, ex) -> {
        if (ex != null) {
            // 记录失败，交给补偿逻辑
        }
    });
```

如果只调 `send()` 而不看回调，失败的消息就悄悄丢了。

### 2、存储端

存储端丢消息，多半是副本配置不够。

- `replication.factor >= 3`：每个分区至少 3 份副本。
- `min.insync.replicas >= 2`：至少 2 个副本确认才算写入成功。
- `unclean.leader.election.enable=false`（默认）：不允许落后的副本当 Leader，避免丢数据。

这三个配合 `acks=all`，才能保证"只要写成功，数据就在至少 2 个副本上"。

### 3、消费端

消费端丢消息，几乎都是提交 offset 的时机不对。

- 先提交、后处理：处理前就崩了，这条消息再也不会被消费，等于丢了。
- 先处理、后提交：处理完再提交，崩了最多是重复处理，不会丢。

所以消费端要关掉自动提交，改成手动提交：

```yaml
spring:
  kafka:
    consumer:
      enable-auto-commit: false
    listener:
      ack-mode: manual
```

### 4、怎么定位丢在哪一环

- 生产端：看发送回调有没有报错，或者用压测工具确认写入。
- 存储端：检查 Topic 的 `replication-factor`、`min.insync.replicas`，以及有没有开 `unclean.leader.election`。
- 消费端：确认提交方式，以及处理逻辑是不是把异常吞掉了。
- 给消息带上唯一 id，在每一环打日志，就能追踪它到底停在了哪。

### 5、复现：副本不足时写入被拒绝

先给 `demo` 设置 `min.insync.replicas=2`：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-configs.sh --bootstrap-server localhost:9092 --alter --entity-type topics --entity-name demo --add-config min.insync.replicas=2
```

停掉两个节点，让某个分区的 ISR 只剩 1 个，再用 `acks=all` 生产：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-console-producer.sh --topic demo --bootstrap-server localhost:9092 --producer-property acks=all
>这条消息会被拒绝
```

生产者会收到 `NOT_ENOUGH_REPLICAS` 错误，消息不会被认为是发送成功。副本不足时 Kafka 宁可拒绝写入，也不假装成功，从源头上避免丢数据。

### 6、复现：自动提交导致丢消息

用自动提交的消费者读几条消息，然后直接 Ctrl+C，模拟"程序在处理前挂掉"：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-console-consumer.sh --topic demo --group auto-demo --bootstrap-server localhost:9092 --consumer-property enable.auto.commit=true
```

查看这个组提交的位移：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group auto-demo
```

可以看到 `CURRENT-OFFSET` 已经前进了。再用同一个组重新消费，之前那几条不会重新出现——如果业务逻辑没跑完，这几条就等于丢了。换成手动提交（处理完再 `ack`），就不会有这个问题。

## 二、消息顺序

Kafka 只保证**分区内有序**，不保证 Topic 全局有序。

会破坏顺序的因素：

- **生产端重试**：`max.in.flight.requests.per.connection > 1` 时，重试可能让后发的消息先到。开启 `enable.idempotence=true` 后，Kafka 会把 `max.in.flight` 限制在 5 以内并保证顺序。
- **多分区**：不同分区的消息本来就没有先后关系。
- **消费端多线程**：一个分区拉出一批消息交给线程池处理，顺序就乱了。
- **Rebalance**：分区换消费者时，处理顺序可能错乱。

保序的做法：

- 用业务 id 作为 key，保证同一业务的消息进同一个分区。
- 生产端开启幂等，避免重试乱序。
- 消费端对单个分区保持单线程处理；如果要多线程，就按 key 哈希到固定线程，做到"同 key 串行"。
- 如果业务要求全局有序，只能退化成单分区加单消费者，代价是并行度归零，一般不建议。

**复现：同一个 key 进同一个分区**

用 `order-1` 作为 key 连续发三条，再用消费者把分区打出来：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-console-producer.sh --topic demo --bootstrap-server localhost:9092 --property parse.key=true --property key.separator=:
>order-1:创建
>order-1:支付
>order-1:发货
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-console-consumer.sh --topic demo --bootstrap-server localhost:9092 --from-beginning --property print.partition=true --property print.key=true
```

三条消息会落在同一个分区，消费顺序和发送顺序一致。把 key 换成 `order-2`，它就会落到另一个分区，这也说明不同 key 之间没有全局顺序。

## 三、消息积压

积压的表现是 `LAG` 持续增长。先找原因，再决定怎么处理。

常见原因：

- 消费逻辑太重（同步调用外部接口、频繁查库）。
- 消费者数量少于分区数，并行度不够。
- 消费者频繁 Rebalance 或者宕机。
- 热点分区：某个 key 的消息特别多，都挤在一个分区里。
- 生产端流量突增。

应急处理，按顺序考虑：

1. 先扩容消费者，把并行度提到分区数上限。
2. 分区数不够时，临时增加分区并重新分配（注意：加分区会打乱 key 到分区的映射）。
3. 简化消费逻辑：先把消息快速落库，业务处理改成异步。
4. 极端情况：写一个临时程序，把积压消息快速转发到一个新的多分区 Topic，再用大量消费者并行处理。
5. 非核心消息可以临时跳过或转入死信，优先保住核心链路。

长期方案：

- 优化消费逻辑，减少同步阻塞。
- 合理规划分区数，别让并行度卡在分区上。
- 监控 LAG 并设置告警，别等积压爆了才发现。
- 生产端做限流，避免流量突增压垮下游。

**复现：制造一次积压**

用压测工具快速写入一批消息，先不启动消费者：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-producer-perf-test.sh --topic demo --num-records 200000 --record-size 200 --throughput -1 --producer-props bootstrap.servers=localhost:9092
```

再查看消费者组的 LAG：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group my-group
```

这时 `LAG` 就是积压的消息数。启动消费者后，再观察它逐步下降直到归零。

## 四、死信队列与毒消息

有些消息无论怎么处理都会失败（比如格式错误、引用了不存在的数据）。如果一直重试，就会卡住整个分区。

Kafka 没有原生的死信队列，需要自己搭一套：

- 失败的消息先投递到一个**重试 Topic**，带上重试次数。
- 超过重试上限后，转入**死信 Topic（DLQ）**，保留原始消息和失败原因。
- 再由人工或定时任务处理 DLQ 里的消息。

用 Spring Kafka 的话，可以直接用 `DefaultErrorHandler` 加 `DeadLetterPublishingRecoverer`：

```java
@Bean
public DefaultErrorHandler errorHandler(KafkaTemplate<String, String> template) {
    DeadLetterPublishingRecoverer recoverer = new DeadLetterPublishingRecoverer(template);
    // 最多重试 3 次，之后投递到死信 Topic
    return new DefaultErrorHandler(recoverer, new FixedBackOff(1000L, 3));
}
```

关键点是：**重试要有上限，失败要有出口**，不能让一条毒消息把分区堵死。

**复现：准备重试和死信 Topic**

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-topics.sh --create --topic demo-retry --bootstrap-server localhost:9092
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-topics.sh --create --topic demo-dlq --bootstrap-server localhost:9092
```

消费失败时先投递到 `demo-retry`，超过重试次数再转入 `demo-dlq`。可以直接查 DLQ，确认失败原因：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-console-consumer.sh --topic demo-dlq --bootstrap-server localhost:9092 --from-beginning --property print.headers=true
```

## 五、大消息

Kafka 默认单条消息上限是 1MB（`max.message.bytes`）。消息太大，会拖慢批处理，占用更多内存和网络。

处理大消息的几种方式：

- **压缩**：设置 `compression.type=gzip/snappy/lz4/zstd`，文本类内容压缩比很高。
- **拆分**：把大消息拆成多条，消费端再拼装。
- **claim-check（推荐）**：大内容（文件、图片、大 JSON）放到对象存储，Kafka 消息里只放一个引用地址。

原则上不要把 Kafka 当成大文件传输通道，能放对象存储的就别塞进消息里。

**复现：发送一条超过 1MB 的消息**

先生成一个 2MB 的文件：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ head -c 2097152 /dev/zero | tr '\0' 'a' > big.txt
```

再把它当作一条消息发出去：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-console-producer.sh --topic demo --bootstrap-server localhost:9092 < big.txt
```

会看到 `RecordTooLargeException`，消息被拒绝。所以大消息要靠压缩、拆分或者 claim-check 解决，而不是简单调大 `max.message.bytes`。

## 六、消费端反压

当消费速度跟不上生产速度时，消费者会不断拉取消息堆在内存里，处理稍慢就可能超过 `max.poll.interval.ms` 被踢出组，甚至 OOM。

控制手段：

- 调小 `max.poll.records`，一次少拉一点。
- 让 `max.poll.interval.ms` 与单批处理时间匹配。
- 处理不过来时，用 `pause()` / `resume()` 主动暂停和恢复分区。
- 用有界队列做异步处理，队列满了就暂停拉取，而不是无限堆积。

**复现：处理太慢被踢出消费者组**

把 `max.poll.interval.ms` 调小，观察消费者因为处理不及时被踢出组：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-console-consumer.sh --topic demo --group slow-demo --bootstrap-server localhost:9092 --consumer-property max.poll.interval.ms=5000
```

如果两次 `poll()` 之间超过 5 秒没有继续拉取，消费者会被判定为掉线，触发 Rebalance。查看成员可以看到它被踢出、分区被重新分配：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group slow-demo --members
```

控制台消费者本身拉取很快，一般不会触发；但换成真实业务里"拉一批、处理很久"的消费者，就很容易踩到这个坑。

## 小结

这一篇把 Kafka 最常见的几类问题过了一遍：消息丢失（生产、存储、消费三段分别排查）、消息顺序（分区内有序加同 key 同分区）、消息积压（先扩容再优化）、死信队列、大消息和消费端反压。

核心还是一句话：**生产端保证写进去，存储端保证不丢，消费端保证处理完再提交，再配合业务幂等，就能覆盖绝大多数场景。**
