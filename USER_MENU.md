# COMP3334 Secure IM User Menu

> E2EE V1 update:
> This build now encrypts message bodies end-to-end on the client.
> The server stores ciphertext envelopes for new chat messages, not plaintext.
> Conversation previews now show `[encrypted]` for encrypted messages.
> The `send`, `open`, push receive flow, and `store-dev-key` behavior described later in this file are superseded by the detailed E2EE notes below and in `E2EE_IMPLEMENTATION.md`.

## 0. E2EE V1 Update

The project no longer treats chat messages as server-readable plaintext in the default CLI flow.

What changed:

- `send <username> <message text>` now encrypts on the sender client before calling `/messages/send`.
- The server stores the encrypted JSON envelope in `messages.content`.
- `message_type` for new encrypted messages is now `e2ee_text`.
- `open <conversation_id> [limit]` decrypts locally before printing history.
- WebSocket `new_message` events decrypt locally before the CLI shows message text.
- `store-dev-key` no longer uploads a fake placeholder key; it now ensures a real X25519 identity key exists locally and republishes the matching public key to the server.
- First contact with a peer uses TOFU trust. If the server later returns a different public key for the same peer, sending is refused.

What did not change:

- Login, contacts, friend requests, conversations, delivered ACK, offline replay, and read tracking still work through the same routes and commands.
- The server still sees usernames, timestamps, contact graph, conversation membership, delivery status, and read status.
- Existing old plaintext data is not a compatibility target for this E2EE upgrade.

New normal outputs to expect:

- After `login`, the CLI now prints an E2EE readiness line containing the device ID and fingerprint.
- After `send`, the CLI still prints a success response, but the displayed `content` is local plaintext for readability while the server-stored value is ciphertext.
- `conversations` shows `[encrypted]` as the last message preview for encrypted chats.
- `store-dev-key` prints the published real device fingerprint instead of a fake placeholder key acknowledgement.

New E2EE-specific errors to expect:

- `error: peer <username> has no published identity key`
- `error: identity key changed for <username>; trusted fingerprint ..., current server fingerprint .... refusing to continue until trust is reset`
- Push/open display placeholders such as `[encrypted message blocked: ...]` or `[encrypted message unavailable: ...]`

How to recover from trust errors:

- If the key change is unexpected, stop and inspect the peer/device state.
- If you intentionally reset the environment, delete `client/client_state.json` and `data/im_phase1.db`, then log in again and rebuild trust from a clean state.


本文件基于当前代码实现整理，目标是从用户视角说明：

- 目前已经实现了哪些功能
- 每个功能对应什么命令
- 正常情况下预期会看到什么输出
- 出错时预期会看到什么报错
- 这些报错通常代表什么原因
- 发生报错后应该怎么处理

适用项目根目录：

```text
D:\Learning\Year3 Sem2\COMP3334\Project_Code\Code
```

注意：

- 这是一份基于当前代码的实际行为说明，不只是 README 摘要。
- CLI 输出是 Python 字典风格，不是格式化 JSON。
- 很多输出依赖数据库当前状态，所以示例中的 `user_id`、`request_id`、`conversation_id`、时间戳和 token 值可能与你本机不同。
- 本项目当前仍是 Phase 1 原型，但默认 CLI 已经实现单设备 E2EE V1。

## 1. 当前已经实现的功能

### 1.1 认证与会话

- 用户注册
- 密码登录
- OTP 二次验证登录
- Session token
- 登出
- 当前用户信息查询

### 1.2 社交关系

- 发送好友请求
- 查看待处理好友请求
- 接受好友请求
- 拒绝好友请求
- 取消自己发出的好友请求
- 查看联系人列表

### 1.3 消息与会话

- 联系人之间发送消息
- 会话列表
- 拉取某个会话中的消息
- 未读计数
- 手动标记已读
- `open` 时自动标记已读

### 1.4 实时能力

- WebSocket 在线推送消息
- WebSocket 推送好友请求变更
- 发送方收到 `delivered` 回执
- 离线消息存储
- 用户重新上线后离线消息补发

### 1.5 E2EE V1

- 当前 CLI 默认发送 `e2ee_text`
- 发送前本地加密，接收后本地解密
- 服务端只存密文 envelope，不存新聊天消息明文
- 本地长期身份密钥管理
- `/identity-key` 公钥发布与拉取
- TOFU 首次信任
- 指纹显示
- 公钥变化时阻止继续发送

### 1.6 已经做了但还不完整的保护

- Argon2 密码哈希
- 内存限流
- TOFU 信任模型
- 只有联系人才能发送消息
- 公钥变更检测
- 新加密消息的 replay protection / duplicate detection

## 2. 还没有实现的功能

以下能力在 README 和代码中都明确还没完成：

- TLS 部署
- 多设备安全会话
- 本地状态加密 / keychain 集成
- CLI 没有直接继续使用 `before_id` 的翻页命令，虽然 HTTP API 支持分页

## 3. 启动方式

### 3.1 启动服务端

在项目根目录打开 PowerShell：

```powershell
cd "D:\Learning\Year3 Sem2\COMP3334\Project_Code\Code"
.\.venv\Scripts\python.exe -m uvicorn server.main:app --reload
```

预期输出：

```text
INFO:     Uvicorn running on http://127.0.0.1:8000
```

解释：

- 说明 FastAPI 服务已经启动，默认监听 `127.0.0.1:8000`
- 第一次启动时会自动建库

### 3.2 启动客户端

另开一个终端：

```powershell
cd "D:\Learning\Year3 Sem2\COMP3334\Project_Code\Code"
.\.venv\Scripts\python.exe client\cli.py http://127.0.0.1:8000
```

预期输出：

```text
Connected to http://127.0.0.1:8000
Commands:
  help
  register <username> <password>
  login <username> <password>
  logout
  me
  contacts
  blocked
  pending
  send-request <username>
  respond <request_id> <accept|decline>
  cancel-request <request_id>
  remove-contact <username>
  block <username>
  unblock <username>
  conversations
  open <conversation_id> [limit]
  send <username> <message text>
  send-ttl <username> <ttl_seconds> <message text>
  fingerprint <username>
  verify <username>
  reset-trust <username>
  mark-read <conversation_id>
  store-dev-key
  exit
```

如果本地还保存着有效 token，可能还会额外看到：

```text
[push] system: {'message': 'connected as alice'}
```

解释：

- `Connected to ...` 表示 CLI 已连上 HTTP 服务
- `Commands:` 是命令菜单
- `[push] system...` 表示 WebSocket 也自动连接成功，当前已有登录态

## 4. 命令总览

当前 CLI 支持的命令如下：

```text
help
register <username> <password>
login <username> <password>
logout
me
contacts
blocked
pending
send-request <username>
respond <request_id> <accept|decline>
cancel-request <request_id>
remove-contact <username>
block <username>
unblock <username>
conversations
open <conversation_id> [limit]
send <username> <message text>
send-ttl <username> <ttl_seconds> <message text>
fingerprint <username>
verify <username>
reset-trust <username>
mark-read <conversation_id>
store-dev-key
exit
```

## 5. 详细用户菜单

### 5.1 `help`

#### 功能

显示命令帮助。

#### 命令

```text
help
```

#### 预期输出

```text
Commands:
  help
  register <username> <password>
  login <username> <password>
  logout
  me
  contacts
  blocked
  pending
  send-request <username>
  respond <request_id> <accept|decline>
  cancel-request <request_id>
  remove-contact <username>
  block <username>
  unblock <username>
  conversations
  open <conversation_id> [limit]
  send <username> <message text>
  send-ttl <username> <ttl_seconds> <message text>
  fingerprint <username>
  verify <username>
  reset-trust <username>
  mark-read <conversation_id>
  store-dev-key
  exit
```

#### 输出解释

- 这是本地帮助文本
- 不访问服务器
- 不要求登录

#### 预期报错

无。

#### 解决办法

无。

### 5.2 `register <username> <password>`

#### 功能

注册新用户，并返回 OTP secret。

CLI 会自动把这个用户的 OTP secret 保存到本地 `client/client_state.json`，这样后续登录通常不需要你手动查 OTP。

#### 命令

```text
register alice StrongPass123
```

#### 预期输出

```text
{'user_id': 1, 'username': 'alice', 'otp_secret': 'JBSWY3DPEHPK3PXP...', 'otp_uri': 'otpauth://totp/COMP3334-IM:alice?secret=...&issuer=COMP3334-IM', 'message': 'registration successful; save the OTP secret in your authenticator app'}
Current OTP code: 123456
```

#### 输出解释

- `user_id`：数据库中的用户主键
- `username`：后端会统一转成小写
- `otp_secret`：当前 demo 直接返回给客户端的 OTP 密钥
- `otp_uri`：可被认证器导入的 URI
- `message`：注册成功提示
- `Current OTP code: 123456`：CLI 本地根据 secret 计算出来的当前 6 位 OTP，用于演示

#### 预期报错

```text
error: username already exists
```

```text
error: rate limit exceeded, please try again later
```

或 Pydantic 校验错误，常见情况是用户名或密码不符合要求。

#### 报错原因

- 用户名已经被注册
- 在短时间内重复注册太多次，触发限流
- 用户名长度不合法，或包含非法字符
- 密码长度不足 8 位

#### 解决办法

- 换一个没有用过的用户名
- 等待 1 分钟后再试
- 用户名只使用字母、数字、下划线、连字符
- 密码长度至少 8 位

### 5.3 `login <username> <password>`

#### 功能

执行两阶段登录：

- 第一步：密码登录，拿到 challenge token
- 第二步：OTP 验证，拿到 access token

成功后，CLI 会：

- 保存 token 到本地状态
- 启动 WebSocket 监听

#### 命令

```text
login alice StrongPass123
```

#### 预期输出

如果本地保存了这个账号的 OTP secret，通常会看到：

```text
Using locally stored OTP code for demo: 123456
{'access_token': 'eyJ...', 'token_type': 'bearer', 'expires_at': '2026-04-01T15:22:31.123456+00:00'}
```

之后可能马上看到：

```text
[push] system: {'message': 'connected as alice'}
```

如果本地没有这个账号的 secret，则会提示：

```text
OTP code:
```

然后需要你自己输入当前 6 位 OTP。

#### 输出解释

- `Using locally stored OTP code...`：CLI 从本地状态文件中读取了注册时保存的 secret，自动算出了当前 OTP
- `access_token`：后续所有受保护接口都会用到这个 token
- `token_type`：固定为 `bearer`
- `expires_at`：token 过期时间，当前配置为 12 小时
- `[push] system...`：WebSocket 鉴权成功，你现在已经处于在线状态

#### 预期报错

```text
error: invalid username or password
```

```text
error: invalid OTP code
```

```text
error: invalid or expired challenge token
```

```text
error: rate limit exceeded, please try again later
```

#### 报错原因

- 用户名不存在
- 密码错误
- OTP 输入错误
- OTP 输入太慢，challenge token 已过期
- 登录尝试过于频繁，触发限流
- 本地没有保存这个用户的 OTP secret，但你手动输入了错误的 OTP

#### 解决办法

- 检查用户名和密码是否正确
- 如果刚注册过，优先使用注册时输出的 `Current OTP code`
- 如果你是用当前 CLI 注册的同一个用户，重新执行登录时应优先出现 `Using locally stored OTP code...`
- 若 OTP 超时，重新执行一次 `login <username> <password>`
- 如果触发限流，等待 1 分钟后再试

### 5.4 `logout`

#### 功能

登出当前 session，并清理本地 token。

#### 命令

```text
logout
```

#### 预期输出

```text
{'ok': True, 'message': 'logged out successfully'}
```

#### 输出解释

- 服务端已把当前 token 撤销
- CLI 会清掉本地 `access_token`
- WebSocket 会停止

#### 预期报错

```text
error: missing bearer token
```

```text
error: invalid or expired token
```

#### 报错原因

- 你当前根本没有登录
- 本地 token 已经过期或失效

#### 解决办法

- 如果没登录，不需要再执行 `logout`
- 重新执行 `login <username> <password>`

### 5.5 `me`

#### 功能

查看当前登录用户的信息。

#### 命令

```text
me
```

#### 预期输出

```text
{'id': 1, 'username': 'alice', 'created_at': '2026-04-01T03:00:00.000000+00:00'}
```

#### 输出解释

- `id`：用户 ID
- `username`：当前登录用户
- `created_at`：注册时间

#### 预期报错

```text
error: missing bearer token
```

```text
error: invalid or expired token
```

#### 报错原因

- 你尚未登录
- 你之前登录过，但 token 已经过期或被登出

#### 解决办法

- 先执行 `login <username> <password>`

### 5.6 `contacts`

#### 功能

查看联系人列表。

#### 命令

```text
contacts
```

#### 预期输出

如果已有联系人：

```text
{'contacts': [{'id': 2, 'username': 'bob', 'created_at': '2026-04-01T03:10:00.000000+00:00'}]}
```

如果没有联系人：

```text
{'contacts': []}
```

#### 输出解释

- `contacts`：联系人数组
- `id`：对方用户 ID
- `username`：对方用户名
- `created_at`：联系人关系建立时间

#### 预期报错

```text
error: missing bearer token
```

```text
error: invalid or expired token
```

#### 报错原因

- 你还没有登录
- token 已失效

#### 解决办法

- 先登录

### 5.7 `pending`

#### 功能

查看当前所有仍为 `pending` 状态的好友请求。

结果会分成：

- `incoming`：别人发给你的
- `outgoing`：你发给别人的

#### 命令

```text
pending
```

#### 预期输出

```text
{'incoming': [{'request_id': 1, 'status': 'pending', 'created_at': '2026-04-01T03:15:00.000000+00:00', 'responded_at': None, 'from_username': 'alice', 'to_username': 'bob'}], 'outgoing': []}
```

#### 输出解释

- `request_id`：好友请求编号
- `status`：这里一定是 `pending`
- `created_at`：请求发出时间
- `responded_at`：待处理时为 `None`
- `from_username`：发起者
- `to_username`：接收者

#### 预期报错

```text
error: missing bearer token
```

```text
error: invalid or expired token
```

#### 报错原因

- 未登录
- token 失效

#### 解决办法

- 重新登录

### 5.8 `send-request <username>`

#### 功能

向目标用户发好友请求。

#### 命令

```text
send-request bob
```

#### 预期输出

发送方终端：

```text
{'ok': True, 'message': 'friend request sent', 'request_id': 1, 'target_username': 'bob', 'target_user_id': 2}
(Request #1 sent to user @bob, id=2)
```

如果接收方在线，对方终端还会收到：

```text
[push] friend request update: {'request_id': 1, 'from_username': 'alice', 'status': 'pending'}
```

#### 输出解释

- `request_id`：后续用于 `respond` 或 `cancel-request`
- `target_username`：请求发送的目标用户名
- `target_user_id`：目标用户 ID
- 第二行括号内容是 CLI 自己补充的友好提示
- 对方的 `[push]` 表示 WebSocket 实时通知已送达

#### 预期报错

```text
error: target user not found
```

```text
error: cannot send a friend request to yourself
```

```text
error: you are already contacts
```

```text
error: friend request already pending
```

```text
error: friend request blocked by user policy
```

```text
error: rate limit exceeded, please try again later
```

```text
error: usage: send-request <username>
```

#### 报错原因

- 对方用户名不存在
- 你给自己发请求
- 你们已经是联系人
- 同一方向已经存在待处理请求
- 数据库里存在 block 关系
- 短时间发送太多好友请求
- 命令参数缺失

#### 解决办法

- 确认对方用户名正确
- 不要给自己发
- 先用 `contacts` 或 `pending` 检查状态
- 如果是限流，等 1 分钟再试
- 如果是参数问题，按正确格式重输

### 5.9 `respond <request_id> <accept|decline>`

#### 功能

处理收到的好友请求。

支持两种动作：

- `accept`
- `decline`

#### 命令

```text
respond 1 accept
```

或：

```text
respond 1 decline
```

#### 预期输出

接受：

```text
{'ok': True, 'message': 'friend request accepted'}
```

拒绝：

```text
{'ok': True, 'message': 'friend request declined'}
```

如果发送方在线，对方还会收到：

```text
[push] friend request update: {'request_id': 1, 'from_username': 'alice', 'to_username': 'bob', 'status': 'accepted'}
```

或：

```text
[push] friend request update: {'request_id': 1, 'from_username': 'alice', 'to_username': 'bob', 'status': 'declined'}
```

#### 输出解释

- `accepted`：双方都会被加入 `contacts`
- `declined`：只更新请求状态，不会建立联系人关系
- 对方的 `[push]` 表示请求状态变化已实时通知

#### 预期报错

```text
error: friend request not found
```

```text
error: you are not the recipient of this request
```

```text
error: request already accepted
```

```text
error: request already declined
```

```text
error: usage: respond <request_id> <accept|decline>
```

#### 报错原因

- `request_id` 不存在
- 该请求不是发给你的
- 该请求已被处理过
- 命令参数错误

#### 解决办法

- 先执行 `pending` 查看正确的请求 ID
- 确保你在接收方账号下执行此命令
- 如果已处理过，不需要重复执行

### 5.10 `cancel-request <request_id>`

#### 功能

取消自己发出的待处理好友请求。

#### 命令

```text
cancel-request 1
```

#### 预期输出

```text
{'ok': True, 'message': 'friend request cancelled'}
```

#### 输出解释

- 该请求会被标记为 `cancelled`
- 当前代码不会向对方发取消推送

#### 预期报错

```text
error: friend request not found
```

```text
error: you are not the sender of this request
```

```text
error: only pending requests can be canceled
```

```text
error: usage: cancel-request <request_id>
```

#### 报错原因

- 请求 ID 不存在
- 你不是这个请求的发送方
- 请求已被接受、拒绝或取消
- 参数缺失

#### 解决办法

- 用 `pending` 查正确的请求 ID
- 确保在发送方账号下执行
- 只有待处理请求能取消

### 5.11 `conversations`

#### 功能

查看当前用户参与的会话列表，按最近活动排序。

#### 命令

```text
conversations
```

#### 预期输出

```text
{'conversations': [{'conversation_id': 1, 'peer_username': 'bob', 'last_message_time': '2026-04-01T03:20:00.000000+00:00', 'last_message_preview': 'hello bob', 'unread_count': 0}]}
```

如果没有会话：

```text
{'conversations': []}
```

#### 输出解释

- `conversation_id`：会话 ID，后续用于 `open` 和 `mark-read`
- `peer_username`：会话对端用户名
- `last_message_time`：最后一条消息时间
- `last_message_preview`：最后一条消息前 60 个字符
- `unread_count`：当前用户收到但尚未标记已读的消息数

#### 预期报错

```text
error: missing bearer token
```

```text
error: invalid or expired token
```

#### 报错原因

- 未登录
- token 已失效

#### 解决办法

- 先登录

### 5.12 `open <conversation_id> [limit]`

#### 功能

拉取某个会话的消息内容。

CLI 内部固定传 `mark_read=True`，所以使用该命令会顺带把当前用户收到的未读消息标记为已读。

#### 命令

```text
open 1
```

或：

```text
open 1 50
```

#### 预期输出

```text
{'messages': [{'message_id': 1, 'conversation_id': 1, 'from_username': 'alice', 'to_username': 'bob', 'content': 'hello bob', 'message_type': 'e2ee_text', 'status': 'delivered', 'is_offline_queued': False, 'is_read': True, 'created_at': '2026-04-01T03:20:00.000000+00:00', 'delivered_at': '2026-04-01T03:20:02.000000+00:00', 'read_at': '2026-04-01T03:25:00.000000+00:00'}], 'next_before_id': 1}
```

#### 输出解释

- `messages`：返回的消息列表
- `message_id`：消息 ID
- `conversation_id`：会话 ID
- `from_username` / `to_username`：发送方和接收方
- `content`：CLI 本地解密后的显示内容；数据库里对加密消息保存的是密文 envelope
- `message_type`：当前 CLI 默认收到的是 `e2ee_text`
- `status`：当前主要是 `sent` 或 `delivered`
- `is_offline_queued`：如果接收方当时不在线，可能为 `True`
- `is_read`：是否已读
- `created_at`：发送时间
- `delivered_at`：接收方客户端 ACK 后才会有值
- `read_at`：已读时间
- `next_before_id`：用于更老消息分页的游标，当前 CLI 没有继续分页命令

如果消息被判定为 replay，`content` 也可能显示为：

```text
[replay blocked: ...]
```

如果本地无法解密，`content` 也可能显示为：

```text
[encrypted message blocked: ...]
```

或：

```text
[encrypted message unavailable: ...]
```

#### 预期报错

```text
error: conversation not found
```

```text
error: not a member of this conversation
```

```text
error: usage: open <conversation_id> [limit]
```

#### 报错原因

- 会话 ID 不存在
- 你不属于这个会话
- 参数缺失或格式错误

#### 解决办法

- 先执行 `conversations` 查看正确的 `conversation_id`
- 确保在会话参与者账号下执行

### 5.13 `send <username> <message text>`

#### 功能

给联系人发送消息。

注意：

- 当前只允许发给联系人
- 当前不支持给自己发消息
- 当前 CLI 会先本地加密，再把密文 envelope 上传到服务端

#### 命令

```text
send bob hello bob
```

#### 预期输出

发送方看到：

```text
{'ok': True, 'message': 'submitted', 'data': {'message_id': 7, 'conversation_id': 1, 'from_username': 'alice', 'to_username': 'bob', 'content': 'hello bob', 'message_type': 'e2ee_text', 'status': 'sent', 'is_offline_queued': False, 'is_read': False, 'created_at': '2026-04-01T03:30:00.000000+00:00', 'delivered_at': None, 'read_at': None}}
(E2EE sender fingerprint 0123abcd...; trusted peer fingerprint 89ef5678...)
```

如果接收方在线，对方终端会看到：

```text
[push] new message from alice: hello bob
[push] auto-acked message 7 as delivered
```

然后发送方终端会看到：

```text
[push] your message 7 is delivered
```

#### 输出解释

- `submitted`：表示服务器已接收这条消息
- `status: sent`：表示发送成功提交给服务器
- `delivered` 不是立即出现在同步响应里，而是由接收方客户端收到后调用 `/messages/ack`
- `is_offline_queued: False`：表示当时接收方在线，消息直接推送成功
- 如果接收方离线，则同步响应中通常会看到 `is_offline_queued: True`
- `message_type: e2ee_text`：表示当前 CLI 走的是默认加密消息流
- 这里显示给发送方看的 `content` 是本地明文，便于阅读；服务端数据库里存的是密文 JSON envelope
- 第二行会打印发送方本地指纹和当前信任的对端指纹

#### 预期报错

```text
error: recipient not found
```

```text
error: self-messaging is not supported in this prototype
```

```text
error: you can only send chat messages to contacts
```

```text
error: message blocked by user policy
```

```text
error: peer bob has no published identity key
```

```text
error: identity key changed for bob; trusted fingerprint ..., current server fingerprint .... refusing to continue until trust is reset
```

```text
error: peer bob has multiple active devices; this prototype only supports one device
```

```text
error: plaintext message too large; limit is 4000 characters
```

```text
error: message too large
```

```text
error: usage: send <username> <message text>
```

#### 报错原因

- 目标用户名不存在
- 你试图给自己发消息
- 对方不是你的联系人
- 数据库里存在 block 关系
- 对方还没有发布身份公钥
- 对方公钥和本地 TOFU 记录不一致
- 对方存在多个活跃设备公钥，而当前原型只支持一个设备
- 明文消息太长，超过 CLI 的 4000 字符限制
- 加密后 envelope 太长，超过服务端上限
- 缺少参数

#### 解决办法

- 确认接收者用户名正确
- 先通过好友请求建立联系人关系
- 让对方先登录一次，或让对方执行 `store-dev-key`
- 如果你确认是合法环境重置，删除本地状态和数据库后重新建立信任
- 缩短消息长度
- 若是 block，先用 `blocked` 查看，再用 `unblock <username>` 解除

### 5.14 `mark-read <conversation_id>`

#### 功能

把某个会话中当前用户收到且尚未已读的消息全部标记为已读。

#### 命令

```text
mark-read 1
```

#### 预期输出

```text
{'ok': True, 'marked_count': 3}
```

如果没有未读：

```text
{'ok': True, 'marked_count': 0}
```

#### 输出解释

- `marked_count`：本次实际被标记为已读的消息数

#### 预期报错

```text
error: conversation not found
```

```text
error: not a member of this conversation
```

```text
error: usage: mark-read <conversation_id>
```

#### 报错原因

- 会话不存在
- 你不是会话成员
- 参数缺失

#### 解决办法

- 用 `conversations` 先查正确的会话 ID
- 在对应账号下操作

### 5.15 `store-dev-key`

#### 功能

确保当前登录用户的真实身份密钥存在，并重新发布当前设备的真实公钥。

当前原型固定使用设备 ID `cli-device-1`。

#### 命令

```text
store-dev-key
```

#### 预期输出

```text
{'ok': True, 'message': 'identity public key stored', 'device_id': 'cli-device-1', 'fingerprint': '0123abcd...'}
Published the local E2EE identity key for this device.
```

#### 输出解释

- 第一行说明后端已成功存储公钥记录
- 第一行里的 `device_id` 和 `fingerprint` 是当前真实本地身份
- 第二行是 CLI 补充说明
- 这不是假数据占位命令，而是重新发布当前真实公钥

#### 预期报错

```text
error: missing bearer token
```

```text
error: invalid or expired token
```

#### 报错原因

- 没有登录
- token 失效

#### 解决办法

- 重新登录后再执行

### 5.16 `exit`

#### 功能

退出 CLI。

#### 命令

```text
exit
```

#### 预期输出

```text
bye
```

#### 输出解释

- CLI 会结束运行
- WebSocket 监听会停止
- HTTP 客户端会关闭

#### 预期报错

无。

#### 解决办法

无。

## 6. 自动推送事件菜单

除了你主动输入命令外，CLI 还会因为 WebSocket 收到这些自动事件。

### 6.1 系统连接成功

#### 预期输出

```text
[push] system: {'message': 'connected as alice'}
```

#### 含义

- 当前 token 对应的 WebSocket 已连接成功
- 当前账号已经在线

#### 如果没看到

- 可能还没登录
- 可能 token 无效
- 可能服务端没开

#### 解决办法

- 先执行 `login`
- 确认服务端在运行

### 6.2 收到新消息

#### 预期输出

```text
[push] new message from alice: hello bob
[push] auto-acked message 7 as delivered
```

#### 含义

- 第一行表示你收到了实时消息
- 第二行表示 CLI 自动调用 `/messages/ack`

#### 重复投递 / replay 检测

如果同一条消息因为未 ACK 被服务端再次推送，可能看到：

```text
[push] [duplicate delivery ignored: duplicate delivery detected for message 7; already processed locally]
[push] auto-acked message 7 as delivered
```

如果同一 replay token 以新的 server message id 再次出现，可能看到：

```text
[push] [replay blocked: replay detected: token already seen in message 7; current server message id 8]
[push] auto-acked message 8 as delivered
```

#### 如果第二行失败

可能看到：

```text
[push] failed to ack message 7: invalid or expired token
```

#### 原因

- token 已过期
- 网络或服务端异常

#### 解决办法

- 重新登录
- 确认服务端正常运行

### 6.3 对方收到你的消息后给出 delivered 回执

#### 预期输出

```text
[push] your message 7 is delivered
```

#### 含义

- 对方客户端已经实际收到并 ACK
- 这比“服务器已入队”更强

#### 如果迟迟没有看到

可能原因：

- 对方离线
- 对方还没连 WebSocket
- 对方客户端没有正常自动 ACK

#### 解决办法

- 让对方重新登录上线
- 等待离线消息补发和自动 ACK

### 6.4 好友请求状态变化

#### 预期输出

新请求到达：

```text
[push] friend request update: {'request_id': 1, 'from_username': 'alice', 'status': 'pending'}
```

请求被接受或拒绝：

```text
[push] friend request update: {'request_id': 1, 'from_username': 'alice', 'to_username': 'bob', 'status': 'accepted'}
```

#### 含义

- 有新的好友请求
- 或已有请求状态发生变化

#### 如果没收到

可能原因：

- 接收方当时不在线
- WebSocket 未连接
- 当前代码对“取消请求”不做推送

#### 解决办法

- 用 `pending` 手动查询
- 确保双方都已登录并在线

### 6.5 WebSocket 鉴权失败

#### 预期输出

```text
[push] auth failed: websocket authentication failed (token invalid or expired); please login again
[push] local session cleared. run: login <username> <password>
```

#### 含义

- WebSocket 使用的 token 已失效
- CLI 已自动清空本地 session

#### 解决办法

- 重新执行 `login <username> <password>`

### 6.6 WebSocket 重连提示

#### 预期输出

```text
[push] system: {'message': 'websocket reconnecting after error: ...'}
```

#### 含义

- WebSocket 暂时断开
- 客户端正在每 2 秒尝试重连

#### 常见原因

- 服务端刚重启
- 网络中断
- 本地退出再重连

#### 解决办法

- 确认服务端进程仍在运行
- 等待自动重连
- 如果已失效则重新登录

## 7. 常见全局报错说明

### 7.1 `error: unknown command; type help`

#### 含义

输入的命令不存在。

#### 常见原因

- 输入了 `contact`，但正确命令其实是 `contacts`
- 输入拼写错误

#### 解决办法

- 执行 `help`
- 按帮助菜单重输

### 7.2 `error: missing bearer token`

#### 含义

当前命令需要登录，但 CLI 本地没有 token。

#### 常见原因

- 还没登录
- 刚执行过 `logout`
- 登录 OTP 失败，实际上没有获得 token
- 本地 session 已被清除

#### 解决办法

- 执行 `login <username> <password>`

### 7.3 `error: invalid or expired token`

#### 含义

你本地有 token，但服务端认为它无效或已过期。

#### 常见原因

- token 已过期
- token 已被 `logout` 撤销
- 服务端数据库状态被清理

#### 解决办法

- 重新登录

### 7.4 `error: invalid OTP code`

#### 含义

第二步 OTP 验证失败。

#### 常见原因

- 你输入了错误 OTP
- OTP 码已经过期
- 当前账号对应的 secret 不对

#### 解决办法

- 重新执行 `login`
- 用最新的 6 位 OTP
- 如果当前 CLI 注册过这个用户，优先使用自动生成的 OTP

### 7.5 `error: rate limit exceeded, please try again later`

#### 含义

触发了服务端限流。

#### 当前代码涉及的限流

- 注册
- 登录
- 好友请求发送

#### 解决办法

- 等待 1 分钟后再试
- 不要短时间反复发送同类请求

## 8. 功能验证建议流程

以下是当前最完整的一套人工验证流程。

### 8.1 验证注册和登录

终端 A：

```text
register alice StrongPass123
login alice StrongPass123
me
```

预期：

- 注册成功
- 登录成功
- `me` 返回 alice 信息

### 8.2 验证第二个用户

终端 B：

```text
register bob StrongPass123
login bob StrongPass123
me
```

预期：

- 注册成功
- 登录成功
- `me` 返回 bob 信息

### 8.3 验证好友请求

终端 A：

```text
send-request bob
```

终端 B：

```text
pending
respond 1 accept
contacts
```

终端 A：

```text
contacts
```

预期：

- Bob 看到 Alice 的请求
- Bob 接受后双方都能在 `contacts` 里看到对方

### 8.4 验证在线消息

终端 A：

```text
send bob hello bob
conversations
```

终端 B：

```text
conversations
open 1
```

预期：

- Bob 立即收到 `[push] new message...`
- Alice 看到 `[push] your message ... is delivered`
- 双方会话列表都出现该会话

### 8.5 验证离线消息

终端 B 先退出：

```text
exit
```

终端 A：

```text
send bob are_you_there
```

然后重新启动 Bob 客户端并登录。

预期：

- Bob 登录上线后会自动收到离线消息
- Alice 在 Bob 自动 ACK 后看到 delivered 推送

### 8.6 验证已读

终端 A：

```text
send bob m1
send bob m2
send bob m3
```

终端 B：

```text
conversations
open 1
conversations
```

预期：

- 第一次 `conversations` 中 `unread_count` 大于 0
- `open 1` 后该会话未读数下降或清零

## 9. 数据持久化说明

### 9.1 服务端数据库

文件位置：

```text
data/im_phase1.db
```

保存内容包括：

- 用户
- OTP secret
- session
- 好友请求
- 联系人
- 会话
- 消息
- 回执

### 9.2 客户端本地状态

文件位置：

```text
client/client_state.json
```

保存内容包括：

- 已知 OTP secret
- 当前 access token
- 当前用户名

这意味着：

- 你关闭 CLI 再重新打开，可能仍然处于自动在线状态
- 如果你想完全重新开始，可以删除数据库和本地状态文件

## 10. 重置环境的方法

如果你想清空当前项目状态：

```powershell
Remove-Item .\data\im_phase1.db -Force -ErrorAction SilentlyContinue
Remove-Item .\client\client_state.json -Force -ErrorAction SilentlyContinue
```

然后重新启动服务端和客户端。

效果：

- 所有用户、好友关系、消息都会清空
- 本地保存的 token 和 OTP secret 也会清空

## 11. 总结

当前项目已经可以完整演示以下流程：

- 注册
- 密码加 OTP 登录
- 建立联系人关系
- 在线消息推送
- 离线消息补发
- delivered 回执
- 会话列表与未读数

但它仍是课程原型，不应被误认为已经完成真正的安全即时通信系统。当前最重要的缺口仍然是：

- 没有 TLS
