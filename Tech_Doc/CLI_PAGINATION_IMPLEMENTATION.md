# CLI 翻页功能实现说明

## 1. 目标

按照 `Project.pdf` 的 `R25` 要求，为当前仓库补上基础可用版的 CLI 翻页 / incremental loading 功能，满足下面几点：

- `open` 只加载一页消息，而不是假设一次看完整段历史
- 用户可以继续加载更早的消息
- 不需要用户手动输入底层 `before_id`

这次实现刻意保持简单，只做当前 CLI 原型够用的一版，不做复杂的历史缓存、跨会话恢复或 TUI 式分页界面。

## 2. 本次设计

### 2.1 采用的最小策略

当前后端 `/messages/pull` 本来就已经支持：

- `conversation_id`
- `limit`
- `before_id`

缺口只在 CLI 层。

所以这次不改后端协议，只在 CLI 上补两个行为：

1. `open <conversation_id> [limit]`
   - 拉取最新一页消息
   - 把返回的 `next_before_id` 存到当前 CLI 进程内存
2. `more <conversation_id> [limit]`
   - 读取刚才保存的游标
   - 继续拉取更早一页消息

这样用户不需要自己手抄 `before_id`，也不需要理解底层 API 参数。

### 2.2 为什么不把分页游标持久化到本地状态文件

这次没有把分页游标写进 `client_state.json`，原因很简单：

- 这个功能只需要在当前 CLI 会话里继续翻页
- 没必要把临时 UI 状态做成长期持久化数据
- 这样可以避免对现有本地状态文件再增加额外复杂度

所以当前设计是：

- 分页游标只存在当前 CLI 进程内存里

### 2.3 `open` 和 `more` 的关系

一句话概括：

- `open` 负责打开最新一页
- `more` 负责继续向前翻更老的页

如果用户还没有先执行过 `open`，直接 `more`，CLI 会明确报错：

```text
error: no saved paging cursor for conversation 1; run: open 1 [limit] first
```

### 2.4 为什么 `more` 仍然沿用 `mark_read=True`

当前 CLI 的 `open` 一直是边拉取边标记已读。

这次为了保持行为一致，`more` 也继续沿用：

- `mark_read=True`

原因是：

- 用户正在主动查看该会话历史
- 没必要在翻页时引入另一套不同的已读语义
- 课程项目原型里，保持简单一致比做复杂阅读状态更重要

## 3. 实现位置

### 3.1 客户端 API 层

文件：

- [client/api_client.py](d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/client/api_client.py)

说明：

- 这次没有新增 API
- 直接复用已有的 `pull_messages(..., before_id=...)`

也就是说，分页能力原本就在 HTTP API 层，只是 CLI 之前没接上。

### 3.2 CLI

文件：

- [client/cli.py](d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/client/cli.py)

新增内容：

- 新命令：

```text
more <conversation_id> [limit]
```

- 新增进程内状态：

```text
self._history_paging
```

用途：

- 按 `conversation_id` 记录当前 CLI 会话里最近一次可继续翻页的游标

新增辅助逻辑：

- `_pull_conversation_page()`

作用：

- 统一处理 `open` / `more`
- 调用 API 拉消息
- 本地解密显示
- 保存下一页游标
- 打印继续翻页提示或“没有更多消息”的提示

### 3.3 用户可见行为

当前行为如下：

- `open 1 20`
  - 拉最新 20 条
  - 若可能还有更早消息，会提示：

```text
Use: more 1 20  # load older messages
```

- `more 1 20`
  - 继续拉更早 20 条

- 如果没有更老消息：

```text
No older messages remain for conversation 1.
```

## 4. 使用方式

### 4.1 打开最新一页

```text
open 1
```

或：

```text
open 1 20
```

### 4.2 继续翻更老消息

```text
more 1
```

或：

```text
more 1 20
```

### 4.3 典型使用顺序

```text
conversations
open 1 20
more 1 20
more 1 20
```

## 5. 如何人工检验

下面给一套最直接的人工验收步骤。

### 5.1 准备多条历史消息

1. Alice 和 Bob 建立联系人
2. Alice 连续发 5 条以上消息给 Bob

例如：

```text
send bob m1
send bob m2
send bob m3
send bob m4
send bob m5
send bob m6
```

### 5.2 先打开最新一页

Bob 执行：

```text
open 1 2
```

预期：

- 只看到最新两条
- CLI 会提示可继续执行：

```text
more 1 2
```

### 5.3 再向前翻页

Bob 继续执行：

```text
more 1 2
more 1 2
```

预期：

- 第二页显示更早两条
- 第三页再显示更早两条

### 5.4 验证翻到头后的行为

继续执行：

```text
more 1 2
```

预期：

- 返回空页
- CLI 打印：

```text
No older messages remain for conversation 1.
```

## 6. 沙箱内实际验证结果

我在沙箱里用临时数据库和真实服务端路由，手动跑过一轮 `open + more + more + more` 流程，结果如下：

```text
CHECK 1:
{'messages': [{'message_id': 5, 'conversation_id': 1, 'from_username': 'alice', 'to_username': 'bob', 'content': 'msg-5', 'message_type': 'text', 'ttl_seconds': None, 'expires_at': None, 'status': 'sent', 'is_offline_queued': True, 'is_read': True, 'created_at': '2026-04-03T01:21:38.290077+00:00', 'delivered_at': None, 'read_at': '2026-04-03T01:21:38.315208+00:00'}, {'message_id': 6, 'conversation_id': 1, 'from_username': 'alice', 'to_username': 'bob', 'content': 'msg-6', 'message_type': 'text', 'ttl_seconds': None, 'expires_at': None, 'status': 'sent', 'is_offline_queued': True, 'is_read': True, 'created_at': '2026-04-03T01:21:38.298275+00:00', 'delivered_at': None, 'read_at': '2026-04-03T01:21:38.315208+00:00'}], 'next_before_id': 5}
Use: more 1 2  # load older messages
---
CHECK 2:
{'messages': [{'message_id': 3, 'conversation_id': 1, 'from_username': 'alice', 'to_username': 'bob', 'content': 'msg-3', 'message_type': 'text', 'ttl_seconds': None, 'expires_at': None, 'status': 'sent', 'is_offline_queued': True, 'is_read': True, 'created_at': '2026-04-03T01:21:38.271078+00:00', 'delivered_at': None, 'read_at': '2026-04-03T01:21:38.320208+00:00'}, {'message_id': 4, 'conversation_id': 1, 'from_username': 'alice', 'to_username': 'bob', 'content': 'msg-4', 'message_type': 'text', 'ttl_seconds': None, 'expires_at': None, 'status': 'sent', 'is_offline_queued': True, 'is_read': True, 'created_at': '2026-04-03T01:21:38.279080+00:00', 'delivered_at': None, 'read_at': '2026-04-03T01:21:38.320208+00:00'}], 'next_before_id': 3}
Use: more 1 2  # load older messages
---
CHECK 3:
{'messages': [{'message_id': 1, 'conversation_id': 1, 'from_username': 'alice', 'to_username': 'bob', 'content': 'msg-1', 'message_type': 'text', 'ttl_seconds': None, 'expires_at': None, 'status': 'sent', 'is_offline_queued': True, 'is_read': True, 'created_at': '2026-04-03T01:21:38.255077+00:00', 'delivered_at': None, 'read_at': '2026-04-03T01:21:38.325209+00:00'}, {'message_id': 2, 'conversation_id': 1, 'from_username': 'alice', 'to_username': 'bob', 'content': 'msg-2', 'message_type': 'text', 'ttl_seconds': None, 'expires_at': None, 'status': 'sent', 'is_offline_queued': True, 'is_read': True, 'created_at': '2026-04-03T01:21:38.262081+00:00', 'delivered_at': None, 'read_at': '2026-04-03T01:21:38.325209+00:00'}], 'next_before_id': 1}
Use: more 1 2  # load older messages
---
CHECK 4:
{'messages': [], 'next_before_id': None}
No older messages remain for conversation 1.
---
```

这些结果说明：

- `open` 只拉最新一页
- `more` 会继续拉更早消息
- 翻到头后会明确提示没有更多历史

另外，原有自动化测试也重新跑过，没有被这次改动破坏：

```text
.\.venv\Scripts\python.exe -m unittest -q
----------------------------------------------------------------------
Ran 3 tests in 1.062s

OK
```

## 7. 当前边界

这次实现是最小可用版，边界如下：

- 分页游标只保存在当前 CLI 进程内，不跨重启持久化
- `more` 必须先建立在同一会话里执行过 `open` 或前一次 `more` 的前提上
- CLI 仍然是整页文本输出，不是交互式滚动界面
- 当前只做“向更老消息翻页”，没有做“上一页 / 下一页”双向导航

## 8. 结论

本次已经完成了一个满足 `Project.pdf R25` 基本要求的 CLI 翻页版本：

- `open` 打开最新一页
- `more` 继续加载更早消息
- 用户不需要手动操作底层 `before_id`

对于当前课程项目阶段，这一版已经满足“基础简单，能用就好”的目标。
