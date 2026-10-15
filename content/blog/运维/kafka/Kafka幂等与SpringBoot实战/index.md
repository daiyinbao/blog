+++
title = "Kafka 幂等与 Spring Boot 实战"
date = 2026-10-09T15:31:52+08:00
weight = 14
tags = ["Kafka", "幂等", "事务", "Spring Boot", "运维"]
summary = "Kafka 系列（五）：讲清重复消费的来源与幂等方案，并用 Spring Boot 落地生产与消费。"

+++

本篇是系列的最后一篇。前面几篇反复提到"至少一次"，也说过 Kafka 不保证只处理一次。这一篇就把"重复"这件事讲透：重复从哪来、怎么在生产端和消费端分别解决，最后用 Spring Boot 写一套能落地的代码。

## 一、重复消费从哪来

Kafka 默认的投递语义是**至少一次（at-least-once）**：一条消息可能被处理多次，但不会丢。重复通常来自三个地方：

- **生产者重试**：生产者发出消息后，如果没收到确认（比如网络抖动、Broker 写完就宕机），就会重发。如果上一次其实已经写入成功，只是确认丢了，Broker 里就会出现两条一样的消息。
- **消费者提交前故障**：消费者处理完消息、还没来得及提交 offset 就崩了，重启后从上一次提交的位置继续读，这条消息会被再处理一遍。
- **Rebalance**：分区被重新分配时，如果某些消息已经消费但还没提交 offset，新的消费者会从旧的提交位置重新读。

所以，重复不是 bug，而是这套设计的固有代价。我们要做的不是"消灭重复"，而是"让重复不影响业务"。

## 二、生产者幂等

最直接的一层防护，是让生产者自己不要发出重复消息，也就是生产者幂等。打开它很简单：

```properties
enable.idempotence=true
```

Kafka 3.0 之后，这个开关默认就是开的。

它的原理是：生产者启动时会从 Broker 拿到一个 Producer ID（PID），然后给每个分区维护一个单调递增的序列号（sequence number）。Broker 端会记录每个 `(PID, 分区)` 已经收到的最大序列号，如果收到重复的序列号，就直接丢弃，不再写入。

这样就解决了"重试导致重复"的问题。不过它有两个边界：

- 幂等是**按分区**生效的，只保证单个分区内不重复。
- 幂等是**按生产者会话**生效的，生产者重启后会拿到新的 PID，跨会话不保证。

要让它生效，还需要 `acks=all`、`retries>0`，并且 `max.in.flight.requests.per.connection<=5`，这几个 Kafka 会帮你自动校验。

## 三、事务与 Exactly-Once

如果一次业务要往多个分区写消息，光靠幂等还不够，这时就要用到事务。

事务通过 `transactional.id` 给生产者一个稳定的身份，即使重启也能续上之前的事务。核心 API 是：

```java
producer.initTransactions();
try {
    producer.beginTransaction();
    producer.send(record1);
    producer.send(record2);
    producer.commitTransaction();
} catch (Exception e) {
    producer.abortTransaction();
}
```

一次事务里的多条消息，要么全部提交，要么全部回滚，不会出现"写了一半"的情况。

在消费端，事务消息默认是不可见的，只有把 `isolation.level` 设成 `read_committed`，消费者才能读到已提交的消息（未提交的会被跳过）。

更进一步，还有端到端的 Exactly-Once：在"消费—处理—生产"的场景里，把消费 offset 的提交也放进同一个事务：

```java
producer.sendOffsetsToTransaction(offsets, groupId);
```

这样"处理结果"和"消费进度"要么一起生效，要么一起回滚。

不过要注意，Exactly-Once 只在 Kafka 内部成立。如果处理过程中还写了数据库、调了外部接口，这些副作用不在事务范围内，仍然需要靠业务幂等来兜底。

## 四、消费端幂等

不管前面做了多少，只要存在外部副作用，最终都要在消费端做一层幂等。常见做法有三种：

- **唯一键约束**：给业务表加唯一索引，重复写入直接报冲突，当作已处理。
- **去重表**：单独建一张"已处理消息"表，处理前先插入，插入失败就说明处理过。
- **Redis 去重**：用 `SETNX` 记录消息 ID，设置一个合理的过期时间。

核心思路都是一样的：**把"判断是否处理过"和"执行业务"放在同一个事务里**，保证两者要么一起成功，要么一起失败。

到这里，我们可以得到一个结论：

> 至少一次投递 + 消费端幂等 = 效果上的只处理一次。

这也是实际项目里最常用的组合。

## 五、实战：Spring Boot 集成 Kafka

下面用一个订单场景，把生产、消费和幂等串起来。

### 1、引入依赖

```xml
<dependency>
    <groupId>org.springframework.kafka</groupId>
    <artifactId>spring-kafka</artifactId>
</dependency>
```

### 2、配置

```yaml
spring:
  kafka:
    bootstrap-servers: localhost:9092
    producer:
      key-serializer: org.apache.kafka.common.serialization.StringSerializer
      value-serializer: org.apache.kafka.common.serialization.StringSerializer
      acks: all
      properties:
        enable.idempotence: true
    consumer:
      group-id: order-service
      auto-offset-reset: earliest
      key-deserializer: org.apache.kafka.common.serialization.StringDeserializer
      value-deserializer: org.apache.kafka.common.serialization.StringDeserializer
      enable-auto-commit: false
    listener:
      ack-mode: manual
```

关键点：生产者开了幂等、`acks=all`；消费者关掉自动提交，改成手动提交。

### 3、生产者

```java
@Service
public class OrderProducer {

    private final KafkaTemplate<String, String> kafkaTemplate;

    public OrderProducer(KafkaTemplate<String, String> kafkaTemplate) {
        this.kafkaTemplate = kafkaTemplate;
    }

    public void sendOrderCreated(String orderId) {
        // 用订单 ID 作为 key，保证同一订单的消息进同一个分区
        kafkaTemplate.send("demo", orderId, "订单创建:" + orderId);
    }
}
```

### 4、消费者（手动提交）

```java
@Component
public class OrderConsumer {

    @KafkaListener(topics = "demo")
    public void onMessage(ConsumerRecord<String, String> record, Acknowledgment ack) {
        System.out.println("收到：" + record.key() + " -> " + record.value());

        // 业务处理成功后，再手动提交 offset
        ack.acknowledge();
    }
}
```

先处理、后提交，对应的就是"至少一次"。

### 5、幂等消费

```java
@Component
public class IdempotentOrderConsumer {

    private final JdbcTemplate jdbcTemplate;

    public IdempotentOrderConsumer(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    @KafkaListener(topics = "demo")
    public void onMessage(ConsumerRecord<String, String> record, Acknowledgment ack) {
        String businessKey = record.key() + ":" + record.value();

        if (!markProcessed(businessKey)) {
            // 插入失败，说明这条消息已经处理过
            ack.acknowledge();
            return;
        }

        // 执行真正的业务逻辑
        handleBusiness(record);

        ack.acknowledge();
    }

    private boolean markProcessed(String businessKey) {
        try {
            jdbcTemplate.update("insert into processed_message(msg_id) values (?)", businessKey);
            return true;
        } catch (DuplicateKeyException e) {
            return false;
        }
    }
}
```

去重表 `processed_message` 的 `msg_id` 上加唯一索引，重复消息就会命中唯一约束，从而被跳过。

> 真正上线时，去重记录的插入要和业务写入放在同一个事务里，保证两者一起成功或失败。

## 六、验证

### 1、重复投递，验证幂等

用控制台生产两条内容相同的消息：

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-console-producer.sh --topic demo --bootstrap-server localhost:9092 --property parse.key=true --property key.separator=:
>order-1:订单创建:order-1
>order-1:订单创建:order-1
```

观察应用日志：第一次会正常处理，第二次会打印"已经处理过"。再去查数据库：

```sql
select * from processed_message;
```

只会有一条 `order-1:订单创建:order-1` 的记录，说明业务只生效了一次。

### 2、查看消费者组进度

```bash
daiyinbao@debian13:~/app/kafka/kafka_2.13-4.3.1$ bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group order-service
```

可以看到 `order-service` 这个组已经提交了 offset，LAG 为 0。

## 小结

这一篇讲清了重复消费的三个来源，梳理了幂等的三个层次：生产者幂等（单分区、单会话）、事务（跨分区原子写、端到端 EOS），以及消费端业务去重，并给出了一条最实用的落地路线：**至少一次投递 + 消费端幂等**。

到这里，这个 Kafka 系列就告一段落了。从快速入门跑通单机，到架构与 KRaft、存储与写入、消费与可靠性，再到幂等与 Spring Boot 实战，希望能帮你把 Kafka 从"会用"推进到"讲得清、敢上生产"。
