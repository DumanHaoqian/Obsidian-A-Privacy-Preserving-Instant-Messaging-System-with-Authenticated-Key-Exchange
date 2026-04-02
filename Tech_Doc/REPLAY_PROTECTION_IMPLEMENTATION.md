# Replay Protection / Duplicate Detection 技术说明

## 1. 目标

本文档说明当前仓库里 `replay protection / duplicate detection` 的设计与实现。

本次实现要解决的核心问题是：

1. 同一条加密消息在未 ACK 前，被服务端重复推送给接收端。
2. 同一份旧密文被重新插入数据库，伪装成一条新的服务端消息。

当前实现的目标不是构建完整现代消息协议，而是在现有单设备 E2EE V1 原型上，提供一个最小、可运行、可验证的重放检测机制。

## 2. 背景问题

在旧实现里：

- 服务端会把 `delivered_at IS NULL` 的消息在用户重新连上 WebSocket 时继续补发。
- 客户端没有本地“已处理消息”的持久化状态。
- 因此同一条消息只要还没被 ACK，就可能被反复显示。
- 更严重的是，如果旧密文被复制成新的数据库行，客户端也无法区分“这是一条新消息”还是“这是旧消息重放”。

这正是 README 里原来提到的 replay protection 缺口。

## 3. 设计思路

### 3.1 总体策略

当前采用的是：

- 发送端生成 `replay_token`
- 把 `replay_token` 放进加密 envelope
- 同时把 `replay_token` 绑定进 AES-GCM 的 AAD
- 接收端把已经见过的 `replay_token` 持久化到本地状态文件
- 后续再看到同一个 token 时，按规则区分“重复投递”还是“重放攻击”

这个方案选择了客户端本地判定，而不是服务端判定，原因是：

1. 当前 E2EE 设计里，消息正文由客户端负责加解密。
2. 客户端最清楚“这条消息我是否已经处理过”。
3. 即使服务端继续保留离线补发逻辑，客户端也能在显示层阻止重复内容再次展示。

### 3.2 为什么要把 token 放进 AAD

如果 `replay_token` 只是普通 envelope 字段，而不纳入 AAD，那么服务端或中间人可以替换 token，绕过重放检测。

因此本次实现要求：

- `replay_token` 进入 envelope
- `replay_token` 进入 AAD

这样任何对 `replay_token` 的篡改都会导致 AES-GCM 验证失败，消息无法被正常解密。

### 3.3 为什么需要区分两类情况

当前把重复情况分成两种：

1. `Duplicate delivery`
2. `Replay attack`

区分依据是“相同 `replay_token` 对应的 `message_id` 是否相同”。

#### Duplicate delivery

条件：

- `replay_token` 相同
- `message_id` 也相同

含义：

- 这是同一条服务端消息的重复投递
- 常见于接收端还没 ACK 就断线重连，服务端再次补发

处理：

- 不重复显示内容
- 标记为 `duplicate delivery ignored`
- CLI 仍然会继续 ACK，帮助服务端停止重发

#### Replay attack

条件：

- `replay_token` 相同
- `message_id` 不同

含义：

- 这不是同一条服务端消息的重投，而是“旧内容被包装成新消息”
- 典型场景是数据库层把旧密文复制成一条新 row

处理：

- 拒绝当作正常消息显示
- 标记为 `replay blocked`
- CLI 仍然会继续 ACK，避免该伪造消息被持续重发

## 4. 数据结构设计

### 4.1 Envelope 版本升级

共享加密模块现在把新消息 envelope 版本从 `v=1` 升级到 `v=2`。

新格式示意：

```json
{
  "alg": "x25519-hkdf-sha256-aesgcm",
  "ciphertext": "...",
  "nonce": "...",
  "replay_token": "0123456789abcdef0123456789abcdef",
  "salt": "...",
  "sender_device_id": "cli-device-1",
  "v": 2
}
```

说明：

- `replay_token` 是发送端本地生成的 16 字节随机值，使用 32 个十六进制字符表示。
- 新 envelope 在 [shared/e2ee.py](./shared/e2ee.py) 中生成。
- 旧版 `v=1` envelope 仍然兼容读取，但不带 replay protection。

### 4.2 AAD 绑定字段

V2 envelope 的 AAD 当前绑定：

- `from_username`
- `to_username`
- `sender_device_id`
- `message_type`
- `replay_token`

这意味着如果有人试图修改 token 再让消息通过去重逻辑，会先在解密阶段失败。

### 4.3 本地 replay cache

客户端把 replay 检测状态存进 `client/client_state.json`。

新增字段：

```json
{
  "replay_cache": {
    "bob": {
      "alice": {
        "0123456789abcdef0123456789abcdef": {
          "message_id": 7,
          "first_seen_at": "...",
          "last_seen_at": "..."
        }
      }
    }
  }
}
```

结构含义：

- 第一层 key：本地用户名
- 第二层 key：对端用户名
- 第三层 key：`replay_token`
- value：该 token 首次出现时对应的 `message_id` 以及时间戳

为什么按 `local_username -> peer_username` 分层：

1. 不同本地账号共享同一个 `client_state.json`
2. 同一个 token 不应跨会话/跨用户误判
3. 这样可以把判定范围控制在“这个本地用户和这个对端的消息关系”里

### 4.4 缓存裁剪

每个 peer 的 replay cache 目前最多保留 `2048` 条记录。

原因：

- 防止 `client_state.json` 无限增长
- 对原型项目而言，这个量已经足够覆盖常规聊天验证

裁剪策略：

- 按 `last_seen_at` / `first_seen_at` / `message_id` 排序
- 保留最新的 2048 条

## 5. 实现位置

### 5.1 `shared/e2ee.py`

作用：

- 生成 V2 envelope
- 校验 replay token
- 把 replay token 纳入 AAD
- 从 envelope 提取 replay token

关键点：

- `ENVELOPE_VERSION = 2`
- `encrypt_message()` 中生成 `replay_token`
- `build_aad()` 支持 `replay_token`
- `parse_envelope()` 校验 token 长度与十六进制格式
- `extract_replay_token()` 用于客户端判定

### 5.2 `client/e2ee_client.py`

作用：

- 管理 replay cache
- 根据消息上下文判定 duplicate 或 replay
- 在解密成功后执行 replay 分类

新增异常：

- `DuplicateDeliveryError`
- `ReplayAttackError`

关键逻辑：

- `_peer_replay_cache()`：定位某个本地用户与某个对端对应的 token 缓存
- `_record_replay_token()`：首次见到 token 时记录
- `_classify_replay_token()`：重复投递 / 重放攻击分类
- `decrypt_message_for_user(..., context='history' | 'push')`

这里特意加入了 `context` 参数，因为“push 重复投递”和“用户重新打开历史消息”必须区别对待。

### 5.3 `client/cli.py`

作用：

- 在 push 场景下，把 duplicate / replay 用明确占位符输出给用户
- 在 `open` 场景下允许历史重看
- 每次 push 或 `open` 后持久化 replay cache

当前 CLI 的展示行为：

- 重复投递：

```text
[duplicate delivery ignored: duplicate delivery detected for message 7; already processed locally]
```

- 重放检测：

```text
[replay blocked: replay detected: token already seen in message 7; current server message id 8]
```

### 5.4 `client/state.py`

作用：

- 为 `replay_cache` 提供默认字段
- 在保存状态时裁剪 replay cache
- 保持旧状态文件兼容

### 5.5 `tests/test_replay_protection.py`

作用：

- 提供可重复运行的自动化回归验证

当前覆盖 3 个核心场景：

1. `test_duplicate_delivery_on_reconnect_is_detected`
2. `test_same_message_can_still_be_opened_from_history`
3. `test_replayed_ciphertext_with_new_server_message_id_is_blocked`

## 6. 生效场景

### 6.1 生效场景一：同一消息重复推送

场景：

- Bob 在线收到消息
- Bob 在 ACK 前重连
- 服务端把同一条 `message_id` 再次推送

当前行为：

- 客户端识别到同一个 `replay_token` 对应的还是同一个 `message_id`
- 判定为 `Duplicate delivery`
- 不再把正文当成一条新消息展示
- 仍会继续 ACK

这是当前最直接的 duplicate detection 场景。

### 6.2 生效场景二：旧密文被复制成新数据库行

场景：

- 一条旧密文消息已经被用户处理过
- 服务端或数据库层把它复制成新 row
- 新 row 拥有新的 `message_id`

当前行为：

- 客户端看到相同 `replay_token`
- 但对应的是新的 `message_id`
- 判定为 `Replay attack`
- 拒绝当成正常新消息显示

这是当前最重要的 replay protection 场景。

### 6.3 生效场景三：历史消息重新查看

场景：

- 用户执行 `open <conversation_id>`
- 重新看到以前已经处理过的消息

当前行为：

- 这不视为攻击，也不视为错误
- 同一条历史消息允许再次显示

原因：

- 重新打开历史是合法用户操作
- 不能把“历史重看”误判成重放攻击

这也是为什么当前实现需要 `context='history'`。

## 7. 不生效或有边界的场景

### 7.1 旧版 V1 消息

旧版 `v=1` envelope 没有 `replay_token`。

因此：

- 旧消息仍然兼容可读
- 但不会获得这套 replay protection

这是为了兼容现有历史数据，而不是因为该场景被完全解决。

### 7.2 非 E2EE 明文 `text`

当前 replay protection 设计主要围绕 `e2ee_text`。

也就是说：

- 默认 CLI 路径会受保护
- 如果有人绕过 CLI 直接调用明文 `text` API，这套基于 E2EE envelope 的 token 机制不会覆盖它

### 7.3 多设备场景

当前系统仍然是单设备原型。

因此：

- replay cache 只按当前单设备假设设计
- 没有多设备共享去重状态
- 没有做跨设备一致性

### 7.4 完整现代协议层的 replay protection

本次实现并不是：

- 双棘轮 replay window
- sequence number / chain key 级别的严格协议设计
- 服务器、客户端、设备三方一致性协议

它是原型阶段“在现有架构上可运行的最小实现”。

## 8. 为什么当前实现是合理的

本次方案的优点：

1. 改动集中
2. 对现有服务端侵入小
3. 不破坏现有离线补发逻辑
4. 不破坏 `open` 查看历史逻辑
5. 能明确区分“重复投递”和“旧密文伪装成新消息”
6. token 被纳入 AAD，安全边界比“纯客户端标记”更稳

它的代价也很明确：

1. 判定状态保存在本地，不是全局一致
2. 旧消息不具备追溯保护
3. 仍然不等价于完整现代安全消息协议

## 9. 如何验证

### 9.1 自动化验证

在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_replay_protection
```

预期：

```text
...
----------------------------------------------------------------------
Ran 3 tests in ...

OK
```

### 9.2 手工验证一：重复投递

这个场景更适合依赖自动化测试，因为 CLI 当前会自动 ACK，手工稳定复现不容易。

自动化测试覆盖：

- `test_duplicate_delivery_on_reconnect_is_detected`

它验证的是：

- 同一条 `message_id` 的重复 push 会被识别为 duplicate delivery

### 9.3 手工验证二：旧密文伪装成新消息

这是最容易手工复现的 replay 场景。

步骤：

1. 启动服务端和两个 CLI。
2. Alice / Bob 注册、登录、加好友。
3. Alice 给 Bob 发一条消息。
4. Bob 用 `open` 看一次该会话，让客户端记录 replay token。
5. 在 PowerShell 里把最新消息复制成一条新的数据库行：

```powershell
cd "D:\Learning\Year3 Sem2\COMP3334\Project_Code\Code"
.\.venv\Scripts\python.exe -c "import sqlite3; from datetime import datetime, timezone; conn=sqlite3.connect('data/im_phase1.db'); conn.execute(\"insert into messages (conversation_id,sender_id,receiver_id,content,message_type,status,is_offline_queued,is_read,created_at) select conversation_id,sender_id,receiver_id,content,message_type,'sent',1,0,? from messages order by id desc limit 1\", (datetime.now(timezone.utc).isoformat(),)); conn.commit(); print('duplicated latest encrypted row')"
```

6. 回到 Bob CLI，再执行一次：

```text
open <conversation_id>
```

预期：

- 原消息继续正常显示
- 新复制出来的那条消息会显示成：

```text
[replay blocked: replay detected: token already seen in message X; current server message id Y]
```

### 9.4 手工验证三：历史重看不会误判

步骤：

1. 正常完成一次加密聊天
2. Bob 执行两次：

```text
open <conversation_id>
open <conversation_id>
```

预期：

- 历史消息两次都能正常显示明文
- 不会因为已经见过 token 就把历史重看误判成 replay

## 10. 当前结论

当前仓库里的 replay protection 已经具备以下能力：

- 能识别并抑制同一条消息的重复投递
- 能阻止旧密文被包装成新消息时的重放
- 不会破坏正常的历史查看
- 对旧消息保持兼容读取

但它仍然是课程原型阶段的实现，不应被表述成“已经拥有完整现代安全消息协议级别的重放防护”。

如果后续继续增强，优先方向应是：

1. 多设备场景的 replay 状态设计
2. 更强的协议级序号 / ratchet 机制
3. 与 TTL、过期清理、forward secrecy 一起统一设计
