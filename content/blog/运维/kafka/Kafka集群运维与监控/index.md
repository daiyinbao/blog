+++
title = "Kafka 集群运维与监控"
date = 2026-10-09T15:31:52+08:00
weight = 17
tags = ["Kafka", "集群运维", "监控", "安全", "容灾"]
summary = "Kafka 系列（七）：讲清集群扩容与分区迁移、故障恢复、监控告警、认证授权、限流、升级与跨机房容灾。"

+++

前面几篇关心的是"消息能不能正确流转"，这一篇关心的是"集群能不能稳定地跑下去"。内容偏运维，命令会多一些。

## 一、扩容与分区重分配

增加 Broker 之后，Kafka 不会自动把已有分区的数据搬过去，需要手动做分区重分配。

先准备一个 `topics.json`，写明要迁移哪些 Topic：

```json
{ "topics": [ { "topic": "demo" } ], "version": 1 }
```

生成迁移计划：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-reassign-partitions.sh --bootstrap-server localhost:9092 --topics-to-move-json-file topics.json --broker-list "1,2,3,4" --generate
```

把生成的计划保存成 `plan.json`，然后执行：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-reassign-partitions.sh --bootstrap-server localhost:9092 --reassignment-json-file plan.json --execute --throttle 50000000
```

`--throttle` 限制迁移带宽，避免把集群网络打满。执行过程中可以验证进度：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-reassign-partitions.sh --bootstrap-server localhost:9092 --reassignment-json-file plan.json --verify
```

另外要注意：**分区数只能增加，不能减少**。增加分区会改变 key 到分区的映射，历史消息的"同 key 同分区"约定可能被打破，所以要谨慎。

## 二、故障恢复

Kafka 的高可用，靠的是副本和 Leader 选举。

- Broker 宕机后，Controller 会从 ISR 里选出新的 Leader，分区继续对外服务。
- 如果某个分区的 ISR 空了，又开了 `unclean.leader.election`，就可能丢数据。
- 常见的异常状态：
  - **Under-replicated partitions**：有副本没跟上，说明有 Broker 落后或宕机。
  - **Offline partitions**：分区没有 Leader，无法读写，需要重点告警。

查看命令：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-topics.sh --describe --under-replicated-partitions --bootstrap-server localhost:9092
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-topics.sh --describe --unavailable-partitions --bootstrap-server localhost:9092
```

Broker 恢复后，落后的副本会重新追上，回到 ISR。

**复现：停掉一个节点，观察副本不足**

停掉 node3：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ ps -ef | grep server-3.properties | grep -v grep
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ kill <PID>
```

等 `replica.lag.time.max.ms`（默认 30s）之后，再查一次：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-topics.sh --describe --under-replicated-partitions --bootstrap-server localhost:9092
```

这时 node3 上的副本已经从 ISR 退出，会出现在副本不足列表里。重启 node3，等它追上进度后，这个列表又会变空。

## 三、监控与告警

Kafka 运维最重要的几类指标：

- **Consumer LAG**：消费积压，最直接的业务指标。
- **UnderReplicatedPartitions**：副本不足。
- **OfflinePartitionsCount**：离线分区，必须告警。
- **ActiveControllerCount**：每个集群应该只有 1 个 active controller。
- **磁盘使用率**：磁盘打满会导致写入失败。
- **请求延迟、网络流量**：用来判断性能瓶颈。

做法上，一般用 `kafka-exporter` 把指标暴露给 Prometheus，再用 Grafana 展示和告警。告警阈值可以设成：LAG 持续增长、离线分区大于 0、磁盘超过 80%、ISR 频繁收缩。

**验证几个关键指标**

没有接 Prometheus 时，也可以直接用命令行看：

```bash
# 消费积压
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group my-group

# 副本不足 / 离线分区
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-topics.sh --describe --under-replicated-partitions --bootstrap-server localhost:9092
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-topics.sh --describe --unavailable-partitions --bootstrap-server localhost:9092

# active controller
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-metadata-quorum.sh --bootstrap-server localhost:9092 --describe --status
```

## 四、安全

生产环境的 Kafka 一般要开启认证、授权和加密。

- **认证**：确认"你是谁"。常用 SASL/SCRAM、SASL/PLAIN，企业内也常用 SASL/GSSAPI（Kerberos）。
- **授权**：确认"你能做什么"。用 ACL 控制某个用户对某个 Topic 的读写权限：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-acls.sh --bootstrap-server localhost:9092 --add --allow-principal User:order-service --operation Read --operation Write --topic demo
```

- **加密**：用 TLS/SSL 加密客户端与 Broker 之间的传输。

这几项都通过 `listeners` 和 `listener.security.protocol.map` 来配置。

**验证：查看 Topic 上的 ACL**

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-acls.sh --bootstrap-server localhost:9092 --list --topic demo
```

可以看到刚才添加的 `User:order-service` 只读规则。ACL 要真正生效，前提是开启了认证（SASL），否则所有客户端都以匿名身份访问，授权规则也就无从判断。

## 五、多租户与配额

一个集群给多个业务用时，要防止某个业务把带宽占满。Kafka 支持按 client 限流：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-configs.sh --bootstrap-server localhost:9092 --alter --add-config 'producer_byte_rate=1048576,consumer_byte_rate=2097152' --entity-type clients --entity-name order-service
```

再加上 Topic 级别的隔离和权限控制，就能做到"一个集群、多租户共用"。

## 六、版本升级与兼容

升级 Kafka 一般采用滚动升级：一次停一个 Broker，升级完再升下一个，期间集群始终有足够的副本对外服务。

需要注意的是：

- Broker 之间的协议版本（`inter.broker.protocol.version`）要逐步推进，不能一次跳太多。
- 客户端版本尽量与 Broker 兼容，升级前先确认官方的兼容矩阵。

## 七、跨机房容灾

单集群放在一个机房，机房整体故障就全挂了。常见做法有两种：

- **MirrorMaker 2**：Kafka 自带的跨集群复制工具，把消息从一个集群同步到另一个。
- **Cluster Linking**：更现代的方案，复制的是分区数据本身，切换更快。

容灾架构上分主备和双活。主备简单、成本低，但切换有数据延迟；双活复杂，要考虑消息冲突和顺序问题。选哪种，取决于业务对 RPO（能丢多少数据）和 RTO（多久恢复）的要求。

## 小结

这一篇讲的是集群层面的运维：怎么扩容和迁移分区、怎么判断故障、要看哪些监控指标、怎么做认证授权、怎么限流、怎么升级和容灾。

如果说前面几篇关心的是"消息能不能正确流转"，这一篇关心的是"集群能不能稳定地跑下去"。
