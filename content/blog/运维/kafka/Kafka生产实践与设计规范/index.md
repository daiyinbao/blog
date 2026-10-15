+++
title = "Kafka 生产实践与设计规范"
date = 2026-10-09T15:31:52+08:00
weight = 18
tags = ["Kafka", "设计规范", "容量规划", "Schema", "运维"]
summary = "Kafka 系列（八）：Topic 与分区设计、热点处理、保留策略与日志压缩、Schema 管理、容量规划与上线 checklist。"

+++

这是系列的最后一篇，讲设计和规范。前面把原理和问题都过了一遍，这一篇把它们收拢成"项目落地时到底该怎么设计"。

## 一、Topic 与分区设计

Topic 是 Kafka 里最基本的组织单位，设计时要考虑几点：

- **命名规范**：统一前缀和语义，比如 `order-events`、`user-events`，便于管理和授权。
- **Topic 数量**：不是越多越好。每个 Topic、每个分区都有元数据开销，Topic 太多会加重 Controller 和客户端的负担。
- **分区数**：按目标吞吐估算。一个分区在同一时刻只能被组内一个消费者消费，所以分区数决定了消费并行度的上限。

分区数怎么估？大致是：

```text
分区数 ≈ 目标吞吐 / 单个分区可承受的吞吐
```

单分区吞吐和消息大小、磁盘、网络都有关，一般先用压测得到一个经验值，再往上留点余量。

## 二、分区数与热点

分区数不是越多越好，太少又会成为瓶颈。更常见的问题是**热点分区**：某个 key 的消息特别多，全挤在一个分区里，其他分区却很闲。

比如用"城市"作为 key，一线城市的消息量远大于其他城市，对应的分区就会被打满。

处理办法：

- 换一个更均匀的 key（比如订单 ID，而不是城市）。
- 加盐：给 key 拼上一个随机后缀，把消息打散到多个分区（代价是失去"同 key 同分区"的顺序保证）。
- 自定义分区器，按业务规则分配。

监控上要能看出"某个分区特别忙"，否则热点很难被发现。

**复现：用一个 key 把分区打满**

用同一个 key 连续发一批消息：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ for i in $(seq 1 20000); do echo "hot-city:msg-$i"; done | bin/kafka-console-producer.sh --topic demo --bootstrap-server localhost:9092 --property parse.key=true --property key.separator=:
```

再看每个分区的日志大小：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ du -sh data/node1/demo-*
```

会发现消息都挤在同一个分区目录里，其他分区几乎没增长。

## 三、保留策略与日志压缩

消息不会永远保存，保留多久由保留策略决定：

- `retention.ms`：保留时间，默认 7 天。
- `retention.bytes`：保留空间上限。

到期的旧 segment 会被删除。对于"只需要最新状态"的数据，还可以用日志压缩（log compaction）：

```properties
cleanup.policy=compact
```

压缩不会删除消息，而是对**相同的 key 只保留最新的一条**。它适合变更日志、状态同步这类场景，比如把数据库表的每次变更写进 Topic，压缩后每个主键只留最新值。

**复现：到期的消息会被清理**

把 `demo` 的保留时间改短：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-configs.sh --bootstrap-server localhost:9092 --alter --entity-type topics --entity-name demo --add-config retention.ms=60000
```

等一会儿，再看数据目录，旧的 segment 会被清理掉：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ ls -l data/node1/demo-0
```

**复现：日志压缩只保留最新值**

新建一个开启了压缩的 Topic，用同一个 key 发几条消息：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-topics.sh --create --topic demo-compact --config cleanup.policy=compact --bootstrap-server localhost:9092
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-console-producer.sh --topic demo-compact --bootstrap-server localhost:9092 --property parse.key=true --property key.separator=:
>user-1:北京
>user-1:上海
>user-1:广州
```

压缩生效后（要等旧 segment 滚动、log cleaner 跑一轮），每个 key 只会保留最新的一条。用新消费者从头读，可以看到 `user-1` 只剩最后一条：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-console-consumer.sh --topic demo-compact --bootstrap-server localhost:9092 --from-beginning --property print.key=true
```

## 四、生产端参数与 Schema

生产端最关键的几个参数：

- `acks=all`：可靠性优先。
- `enable.idempotence=true`：避免重试产生重复。
- `batch.size` / `linger.ms`：控制批处理，权衡吞吐和延迟。
- `compression.type`：压缩，省带宽和磁盘。

数据格式方面，建议用带 Schema 的序列化方式（Avro、Protobuf），并配合 Schema Registry 管理版本。这样生产者改字段、消费者升级时，能靠兼容性规则避免"读不了"的事故。常用的兼容性策略是**向后兼容**：新增字段可选、不删除已有字段。

## 五、容量规划与压测

容量规划的基本公式：

```text
所需磁盘 ≈ 消息大小 × 每天条数 × 保留天数 × 副本数 × (1 + 余量)
```

除了磁盘，还要看网络带宽和内存（页缓存）。规划前最好用压测工具验证：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-producer-perf-test.sh --topic demo --num-records 1000000 --record-size 1024 --throughput -1 --producer-props bootstrap.servers=localhost:9092
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-consumer-perf-test.sh --topic demo --messages 1000000 --bootstrap-server localhost:9092
```

根据结果调整分区数、Broker 数量和硬件规格。

## 六、消息回溯与数据补算

当消费逻辑写错了、或者需要重算历史数据时，就需要把消息重新读一遍。Kafka 支持重置消费位移：

```bash
# 先把消费者组停掉，再重置到最早
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --group order-service --reset-offsets --to-earliest --topic demo --execute
```

也可以按时间重置（`--to-datetime`）或按位移重置（`--to-offset`）。

重放时要注意两点：

- 消息必须还在保留范围内，超过保留期的就读不到了。
- 重放会再次触发业务逻辑，务必保证处理是幂等的。

重置完可以确认一下位移：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group order-service
```

再启动消费者，就会从最早的消息重新读一遍。

## 七、一份上线 checklist

把前面几篇的要点收拢成一份清单，上线前逐条过一遍：

- 副本数 `replication.factor >= 3`，`min.insync.replicas >= 2`。
- 生产者 `acks=all`、`enable.idempotence=true`，并处理发送失败回调。
- 消费者关闭自动提交，先处理、后提交。
- 关键业务做消费端幂等。
- 失败消息有重试和死信出口。
- 监控 LAG、离线分区、磁盘使用率，并配置告警。
- 分区数按吞吐规划，注意 key 是否倾斜。
- 保留策略和容量匹配，别让磁盘被写满。
- 生产环境开启认证、授权和加密。

## 小结

这一篇偏设计和规范：Topic 与分区怎么规划、怎么避免热点、保留策略和日志压缩怎么选、生产端参数和 Schema 怎么定、容量怎么估、历史数据怎么重放，最后收成一份上线 checklist。

到这里，这个 Kafka 系列（正文加番外）就完整了。从入门跑通，到原理、实战、问题排查和运维规范，希望能帮你把 Kafka 真正用起来、也用得住。
