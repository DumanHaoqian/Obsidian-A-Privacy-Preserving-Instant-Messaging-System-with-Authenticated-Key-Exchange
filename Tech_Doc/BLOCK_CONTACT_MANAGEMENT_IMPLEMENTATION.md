# block / unblock / remove-contact 功能实现说明

## 1. 目标

按照 `Project.pdf` 的 `R15` 要求，为当前仓库补上基础可用版的联系人移除与屏蔽管理功能，满足下面几点：

- 用户可以移除联系人
- 用户可以 block / unblock 某个用户
- 被 block 的用户后续好友请求和聊天消息会被系统拒绝

这次实现刻意保持简单，只做当前 CLI 原型够用的一版，不做复杂黑名单策略、批量管理或多设备同步。

## 2. 本次设计

### 2.1 采用的最小策略

本次增加 4 个 CLI 能力：

```text
blocked
block <username>
unblock <username>
remove-contact <username>
```

语义如下：

- `block <username>`
  - 建立“当前用户 -> 目标用户”的单向 block 关系
  - 同时移除双方联系人关系
  - 同时清掉双方之间仍处于 `pending` 的好友请求
  - 同时丢弃“目标用户发给当前用户、但还没送达”的离线消息
- `unblock <username>`
  - 只删除当前用户对目标用户的 block 关系
  - 不自动恢复联系人关系
- `remove-contact <username>`
  - 只移除双方联系人关系
  - 不自动 block
- `blocked`
  - 查看当前用户自己 block 了哪些人

### 2.2 为什么 block 时要顺便移除联系人

`Project.pdf` 对 `R15` 的要求是：

- users can remove friends and block users
- blocked users’ requests/messages are ignored

如果 block 之后仍保留 active contact 关系，联系人状态会和“已经不允许通信”的策略冲突。

所以本次采用最简单直接的策略：

- 一旦 block，就把双方 active contact 关系一起移除

这样 block 之后系统状态更一致：

- 联系人列表里不再出现对方
- 未来聊天发送会因为 block 策略被拒绝
- 即使之后 unblock，也必须重新加好友才能继续聊天

### 2.3 为什么 block 时要清理 pending 请求和未送达消息

如果只新增 `blocks` 行，而不处理旧状态，会留下两个问题：

1. 双方之间可能还挂着旧的 `pending` 好友请求
2. 被 block 用户之前发来的离线消息，可能在之后仍被补发

这不符合“blocked users’ requests/messages are ignored”的目标。

所以本次在 `block <username>` 时额外做两步清理：

- 删除双方之间仍是 `pending` 的好友请求
- 删除“被 block 用户发给当前用户、但尚未 delivered”的消息

这里刻意只删除“流向 blocker 的未送达消息”，不主动删历史消息，也不主动删除已经送达的内容，保持实现简单。

### 2.4 remove-contact 和 block 的区别

两者不是同一个动作：

- `remove-contact`
  - 只取消联系人关系
  - 之后双方不能直接发聊天消息，因为系统默认只允许联系人聊天
  - 但双方仍可重新发好友请求
- `block`
  - 除了取消联系人关系，还会阻止之后的好友请求和聊天消息

一句话区分：

- `remove-contact` 是“先断开联系人”
- `block` 是“断开联系人并拒绝后续接触”

## 3. 实现位置

### 3.1 数据模型

文件：

- [server/db.py](d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/server/db.py)

这次没有新增数据库表。

直接复用现有：

- `contacts`
- `blocks`
- `friend_requests`
- `messages`

### 3.2 请求模型

文件：

- [server/schemas.py](d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/server/schemas.py)

新增模型：

- `UsernameTargetRequest`

用途：

- 统一承载 `target_username`
- 统一做用户名清洗与校验

### 3.3 服务端核心逻辑

文件：

- [server/main.py](d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/server/main.py)

新增 helper：

- `refresh_conversation_summary()`
- `remove_contact_links()`
- `delete_pending_friend_requests_between()`
- `drop_undelivered_incoming_messages()`

新增路由：

- `POST /contacts/remove`
- `GET /blocks`
- `POST /blocks/block`
- `POST /blocks/unblock`

其中 `POST /blocks/block` 的核心行为是：

1. 插入 block 关系
2. 删除双方联系人关系
3. 删除双方之间仍 pending 的好友请求
4. 删除“目标用户 -> 当前用户”且尚未 delivered 的消息

### 3.4 兼容 remove-contact 后重新加好友

文件：

- [server/main.py](d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/server/main.py)

为了让“移除联系人后重新加回”能稳定工作，本次还顺手补了一点历史状态清理：

- 在 `friend_request/respond`
- 在 `friend_request/cancel`

如果数据库里已经有旧的同状态记录，会先删掉旧记录，再更新当前请求状态。

这样可以避免重复 accept / cancel 导致唯一约束冲突。

### 3.5 客户端 API 与 CLI

文件：

- [client/api_client.py](d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/client/api_client.py)
- [client/cli.py](d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/client/cli.py)

新增 API 封装：

- `blocked_users()`
- `block_user()`
- `unblock_user()`
- `remove_contact()`

新增 CLI 命令：

```text
blocked
block <username>
unblock <username>
remove-contact <username>
```

## 4. 使用方式

### 4.1 查看已 block 用户

```text
blocked
```

### 4.2 block 用户

```text
block bob
```

典型结果：

- `bob` 被加入 block 列表
- `contacts` 中不再出现 `bob`
- 之后 `bob` 不能再发好友请求或聊天消息

### 4.3 unblock 用户

```text
unblock bob
```

说明：

- 这只会解除 block
- 不会自动恢复联系人关系

### 4.4 remove-contact

```text
remove-contact bob
```

说明：

- 双方联系人关系会被移除
- 之后双方不能直接发聊天消息
- 但可以重新走好友请求流程

## 5. 如何人工检验

下面给一套最直接的人工验收步骤。

### 5.1 检验 block 会移除联系人

1. Alice 和 Bob 先加成联系人
2. Alice 执行：

```text
block bob
contacts
blocked
```

预期：

- `contacts` 里不再有 `bob`
- `blocked` 里出现 `bob`

### 5.2 检验 block 后请求和消息被拒绝

1. 保持 Alice 已 block Bob
2. 让 Bob 尝试：

```text
send-request alice
send alice hello
```

预期：

- 好友请求被拒绝
- 聊天消息也被拒绝

### 5.3 检验 unblock 不会恢复联系人

1. Alice 执行：

```text
unblock bob
```

2. Bob 直接再发聊天消息

预期：

- block 已解除
- 但因为双方已不是联系人，直接聊天仍被拒绝

### 5.4 检验 remove-contact 后还能重新加回

1. Alice 和 Bob 重新加为联系人
2. Alice 执行：

```text
remove-contact bob
```

3. 然后再次走好友请求流程

预期：

- 移除后 `contacts` 为空
- 重新发起好友请求并 accept 后，双方可再次成为联系人

## 6. 沙箱内实际验证结果

我在沙箱里用临时数据库手动跑过一轮流程，结果如下：

```text
CHECK 1: initial contacts -> {'contacts': [{'id': 2, 'username': 'bob', 'created_at': '2026-04-02T12:31:17.142587+00:00'}]}
CHECK 2: block result -> {'ok': True, 'message': 'blocked user bob; removed contact relationship; ignored 1 undelivered incoming message(s)'}
CHECK 3: contacts after block -> {'contacts': []}
CHECK 4: blocked list after block -> {'blocked_users': [{'id': 2, 'username': 'bob', 'created_at': '2026-04-02T12:31:17.162092+00:00'}]}
CHECK 5: pulled history after block -> {'messages': [], 'next_before_id': None}
CHECK 6: blocked send -> {'detail': 'message blocked by user policy'}
CHECK 7: blocked friend request -> {'detail': 'friend request blocked by user policy'}
CHECK 8: unblock result -> {'ok': True, 'message': 'unblocked user bob'}
CHECK 9: blocked list after unblock -> {'blocked_users': []}
CHECK 10: send after unblock without contact -> {'detail': 'you can only send chat messages to contacts'}
CHECK 11: remove-contact result -> {'ok': True, 'message': 'removed contact relationship with bob'}
CHECK 12: contacts after remove -> {'contacts': []}
CHECK 13: send after remove -> {'detail': 'you can only send chat messages to contacts'}
CHECK 14: final contacts after re-add -> {'contacts': [{'id': 2, 'username': 'bob', 'created_at': '2026-04-02T12:31:17.229439+00:00'}]}
```

这些结果说明：

- `block` 会移除联系人关系
- `block` 后会阻止新的好友请求和聊天消息
- `block` 时未送达来信会被忽略
- `unblock` 不会自动恢复联系人
- `remove-contact` 后仍然可以重新加回

另外，原有自动化测试也重新跑过，没有被这次改动破坏：

```text
.\.venv\Scripts\python.exe -m unittest -q
----------------------------------------------------------------------
Ran 3 tests in 0.754s

OK
```

## 7. 当前边界

这次实现是最小可用版，边界如下：

- block 是单向关系，不是自动双向 block
- unblock 只解除 block，不恢复联系人
- block 时只清理“流向 blocker 的未送达消息”，不删除历史消息
- 没有做复杂的 block 通知、备注、批量管理、跨设备同步

## 8. 结论

本次已经完成了一个满足 `Project.pdf R15` 基本要求的 block / unblock / remove-contact 版本：

- 可以移除联系人
- 可以 block / unblock 用户
- 被 block 的用户后续请求和消息会被系统拒绝

对于当前课程项目阶段，这一版已经满足“基础简单，能用就好”的目标。
