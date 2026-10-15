+++
title = "Kafka 的存储与消息写入"
date = 2026-10-09T15:31:52+08:00
weight = 12
tags = ["Kafka", "分区", "副本", "生产者", "运维"]
summary = "Kafka 系列（三）：下探 Topic、Partition 的磁盘结构，讲清副本、ISR 与生产者写入流程。"

+++

本篇承接上一篇搭好的 3 节点集群。上一篇我们看到了 Topic 的 Leader 和 ISR，这一篇打开数据目录，看看消息在磁盘上到底长什么样，再把生产者写入的流程完整走一遍。

## 一、Topic 在磁盘上的样子

上一篇我们创建了一个 `demo` Topic，它有 3 个分区、每个分区 3 份副本。Kafka 会把每个分区都落到磁盘上，我们到数据目录里看看：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ ls data/node1
__cluster_metadata-0  demo-0  demo-1  demo-2
```

除了内部的 `__cluster_metadata-0`，剩下的 `demo-0`、`demo-1`、`demo-2` 正好对应 `demo` 的三个分区。目录名就是 `<topic>-<partition>`。

进入其中一个分区目录：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ ls data/node1/demo-0
00000000000000000000.index
00000000000000000000.log
00000000000000000000.timeindex
partition.metadata
```

每个分区由一组 segment（日志段）组成，这几种文件分工不同：

- `.log`：真正存放消息的文件。
- `.index`：记录 offset 到物理位置的映射，用来快速定位消息。
- `.timeindex`：记录时间戳到 offset 的映射，方便按时间查找。

文件名 `00000000000000000000` 表示这个 segment 里第一条消息的 offset 是 0。当一个 segment 写满（默认 `log.segment.bytes=1GB`）或者超过滚动时间，Kafka 就会创建新的 segment，文件名变成下一个起始 offset。

**为什么要这样设计？** 因为 Kafka 只做顺序追加：新消息永远写在最后一个 segment 的末尾。顺序写磁盘比随机写快得多，这也是 Kafka 高吞吐的底层原因之一。

## 二、实验：直接读 segment

`.log` 是二进制文件，不能直接 `cat`，但 Kafka 提供了 `kafka-dump-log.sh` 来解析它：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-dump-log.sh --files data/node1/demo-0/00000000000000000000.log --print-data-log
```

输出大致如下：

```text
Dumping data/node1/demo-0/00000000000000000000.log
Starting offset: 0
baseOffset: 0 lastOffset: 1 count: 2 ... position: 0 CreateTime: ... size: 74 magic: 2 compresscodec: NONE ...
| offset: 0 CreateTime: ... key: order-1 payload: 创建
| offset: 1 CreateTime: ... key: order-1 payload: 发货
```

这里可以直接看到每条消息的 offset、key 和 value。入门篇里说 Offset 是消息在分区中的位置，在这里就变成了文件里的一个具体偏移。

## 三、副本机制：Leader、Follower 与 ISR

每个分区有多份副本，其中只有一份是 Leader，其余是 Follower：

- 生产者写消息、消费者读消息，都只和 Leader 打交道。
- Follower 不处理客户端请求，只负责从 Leader 拉取数据，保持同步。

这样设计的好处是：读写压力集中在 Leader 上，Follower 专心做备份，一旦 Leader 挂了，可以快速顶上去。

那怎么判断一个 Follower 是否"跟得上"？Kafka 用两个位置来跟踪：

- **LEO（Log End Offset）**：日志末尾的下一条消息位置，也就是"我已经写到哪了"。
- **HW（High Watermark）**：所有 ISR 副本都同步到的位置。

**ISR（In-Sync Replicas）** 就是"和 Leader 保持同步的副本集合"。只有 ISR 里的副本才有资格参与 Leader 选举。消费者能读到的最大位置也是 HW——HW 之后的消息还没被所有副本确认，暂时不对外可见。

用 `--describe` 就能看到 Leader、副本和 ISR：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-topics.sh --describe --topic demo --bootstrap-server localhost:9092
```

```text
        Topic: demo     Partition: 0    Leader: 1       Replicas: 1,2,3 Isr: 1,2,3
        Topic: demo     Partition: 1    Leader: 2       Replicas: 2,3,1 Isr: 2,3,1
        Topic: demo     Partition: 2    Leader: 3       Replicas: 3,1,2 Isr: 3,1,2
```

现在三个副本都在 ISR 里。我们把 node3 停掉，再观察一次：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ ps -ef | grep server-3.properties | grep -v grep
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ kill <PID>
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-topics.sh --describe --topic demo --bootstrap-server localhost:9092
```

等一会儿（默认超过 `replica.lag.time.max.ms=30s`）再看，`Isr` 里就不再有 3 了：

```text
        Topic: demo     Partition: 0    Leader: 1       Replicas: 1,2,3 Isr: 1,2
        Topic: demo     Partition: 1    Leader: 2       Replicas: 2,3,1 Isr: 2,1
        Topic: demo     Partition: 2    Leader: 2       Replicas: 3,1,2 Isr: 1,2
```

注意 Partition 2：原来的 Leader 是 3，node3 停掉后，Leader 变成了 2。这就是下面要说的 Leader 选举。

把 node3 重新启动，过一会儿它就会追上进度，重新回到 ISR。

## 四、Leader 选举

Leader 故障后，谁来指定新的 Leader？答案是 Controller（就是上一篇讲的 active controller）。Controller 会从该分区的 ISR 里挑一个副本作为新 Leader，然后通知所有节点。

这里有一个重要的取舍：如果一个分区的 ISR 里一个副本都没有了（比如所有副本都挂了，或者都落后太多），怎么办？

- `unclean.leader.election.enable=false`（默认）：宁可这个分区暂时不可用，也不让落后的副本当 Leader，避免数据丢失。
- `unclean.leader.election.enable=true`：允许非 ISR 副本当 Leader，分区能更快恢复，但会丢失一部分没同步完的消息。

大多数业务场景下，我们更在意数据不丢，所以保持默认即可。

## 五、生产者发送消息的流程

理解了存储和副本，再来看生产者是怎么把消息写进来的。一条消息从 `send()` 到落盘，大致经过这几步：

1. **拦截器（Interceptor）**：可以在发送前对消息做统一处理，比如加埋点、改内容。
2. **序列化（Serializer）**：把 key 和 value 转成字节数组。
3. **分区器（Partitioner）**：决定这条消息进哪个分区。带 key 时按 key 的哈希取模，不带 key 时按粘性策略轮询。
4. **RecordAccumulator**：把消息按分区放进对应的批次里缓冲，攒够了再发。
5. **Sender 线程**：把各个批次按目标 Broker 分组，通过网络发送出去。
6. **Broker 端**：Leader 把消息追加到自己的日志末尾，Follower 再拉取同步，最后根据 `acks` 决定何时给生产者回执。

这里有两个参数决定了批处理的效果：

- `batch.size`：一个批次最多缓存多少字节（默认 16KB）。
- `linger.ms`：为了凑更大的批次，最多等待多久（默认 0，也就是不等待）。

`linger.ms` 调大一点，能攒出更大的批次，减少网络请求，吞吐上去了，但单条消息的延迟也会增加。这是一组典型的吞吐与延迟权衡。

而 `acks` 决定了可靠性：

- `acks=0`：生产者发出去就不管了，不等待任何回执。吞吐最高，但可能丢消息。
- `acks=1`：只等 Leader 确认。Leader 挂了、Follower 还没同步，就可能丢。
- `acks=all`（或 `-1`）：等所有 ISR 副本确认。最可靠，但延迟也最高。

## 六、实验：参数对吞吐与可靠性的影响

### 1、带 key 生产，观察分区落点

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-console-producer.sh --topic demo --bootstrap-server localhost:9092 --property parse.key=true --property key.separator=:
>order-1:创建
>order-2:支付
>order-1:发货
```

再用消费者把分区一起打出来：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-console-consumer.sh --topic demo --bootstrap-server localhost:9092 --from-beginning --property print.partition=true --property print.key=true
```

输出大致如下：

```text
Partition:1     order-1 创建
Partition:0     order-2 支付
Partition:1     order-1 发货
```

可以看到，`order-1` 的两条消息都进了 Partition 1。这就是"同一个 key 进同一个分区"，同一个订单的消息因此能保证处理顺序。

### 2、对比批处理参数对吞吐的影响

Kafka 自带了一个压测工具，可以直接观察吞吐：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-producer-perf-test.sh --topic demo --num-records 200000 --record-size 1000 --throughput -1 --producer-props bootstrap.servers=localhost:9092 acks=all linger.ms=0
```

再把 `linger.ms` 调大，重复一次：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-producer-perf-test.sh --topic demo --num-records 200000 --record-size 1000 --throughput -1 --producer-props bootstrap.servers=localhost:9092 acks=all linger.ms=50
```

对比两次输出的 `records/sec` 和 `MB/sec`，通常能看到 `linger.ms=50` 的吞吐更高——因为它把更多消息合进了同一个批次。

同样地，把 `acks` 从 `all` 改成 `1` 再压一次，吞吐会进一步上升，代价就是可靠性下降。

## 小结

这一篇我们从磁盘目录出发，看清了 Topic 和分区在磁盘上的结构（segment 文件），理解了副本、ISR、LEO、HW 这些概念，并走了一遍生产者从 `send()` 到落盘的流程。

下一篇，我们会转到消费侧，讲清消费者组、Offset 提交和 Rebalance，再看看 Kafka 是靠哪些配置保证消息可靠性的。
