# 消息自毁 / TTL 功能实现说明

## 1. 目标

按照 `Project.pdf` 的要求，为当前仓库补上基础可用版的消息自毁 / TTL 功能，满足下面三点：

- 支持发送带 TTL 的消息
- 过期消息不再出现在 UI 中
- 服务端对过期离线密文做 best-effort 清理，避免过期后再补发

这次实现刻意保持简单，不做复杂协议设计，只做当前原型足够可用的一版。

## 2. 本次设计

### 2.1 采用的简单策略

- TTL 单位使用秒，字段名为 `ttl_seconds`
- TTL 从服务端接收消息并入库时开始计时
- 服务端同时保存 `expires_at`
- 一旦当前时间超过 `expires_at`，该消息视为过期

这样设计的原因很简单：

- 当前系统已经有服务端统一入库时间，直接用它计算过期时间最稳定
- 不需要额外引入“读后销毁”之类更复杂状态机
- 对课程项目来说，基础 TTL 自毁已经够用

### 2.2 如何保证 TTL 不能被偷偷改掉

对于默认 CLI 的加密消息，这次把 `ttl_seconds` 放进了 E2EE envelope，并且纳入了 AES-GCM 的 AAD。

结果是：

- 服务端可以读取 TTL 元数据来做过期清理
- 但如果有人篡改 envelope 里的 `ttl_seconds`，接收端解密会失败

这满足了 `Project.pdf` 里“TTL/expiry policy 要放进 authenticated metadata”的要求。

### 2.3 过期后怎么处理

服务端：

- 过期消息会被清理出 `messages` 表
- 同时重算受影响会话的 `last_message_id` 和 `last_message_at`
- WebSocket 用户重新上线时，会先做一次过期清理，再决定是否补发离线消息

客户端：

- `open` 拉历史消息时，不再显示已过期消息
- 新收到的自毁消息会在本地启动一个简单定时器，到期后打印一条过期提示

说明：

- 当前客户端是 CLI，不是 GUI，无法真的把终端里已经打印出来的那一行“擦掉”
- 因此这里采用的可接受做法是：后续历史中不再显示，并在本次运行里打印过期提示

## 3. 实现位置

### 3.1 加密层

文件：

- [shared/e2ee.py](d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/shared/e2ee.py)

改动：

- 新增 `MIN_TTL_SECONDS` 和 `MAX_TTL_SECONDS`
- `build_aad()` 支持 `ttl_seconds`
- `encrypt_message()` 支持把 `ttl_seconds` 写入 envelope
- `decrypt_message()` 用 envelope 里的 `ttl_seconds` 参与 AAD 校验
- 新增 `extract_ttl_seconds()`

### 3.2 服务端数据模型和数据库

文件：

- [server/schemas.py](d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/server/schemas.py)
- [server/db.py](d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/server/db.py)

改动：

- `MessageSendRequest` 新增可选字段 `ttl_seconds`
- `messages` 表新增：
  - `ttl_seconds`
  - `expires_at`
- `init_db()` 增加了简单迁移逻辑，兼容已有数据库

### 3.3 服务端 TTL 逻辑

文件：

- [server/main.py](d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/server/main.py)

改动：

- 新增 `cleanup_expired_messages()`
- 在以下时机做 best-effort 清理：
  - 服务启动时
  - 发送消息前
  - 拉取消息前
  - 标记已读前
  - 获取会话列表前
  - 记录 ACK 前
  - WebSocket 上线补发离线消息前
- `messages/send` 会：
  - 读取 `ttl_seconds`
  - 对加密消息校验 request 里的 TTL 和 envelope 里的 TTL 一致
  - 计算并保存 `expires_at`

### 3.4 CLI

文件：

- [client/api_client.py](d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/client/api_client.py)
- [client/e2ee_client.py](d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/client/e2ee_client.py)
- [client/cli.py](d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/client/cli.py)

改动：

- 新增命令：

```text
send-ttl <username> <ttl_seconds> <message text>
```

- `encrypt_outbound_message()` 支持传入 TTL
- `send_message()` 支持把 TTL 发给服务端
- CLI 在历史消息展示时会跳过已过期消息
- CLI 会为当前运行中显示过的自毁消息安排过期提示

## 4. 人工使用方式

### 4.1 发送普通消息

原命令不变：

```text
send bob hello
```

### 4.2 发送自毁消息

新命令：

```text
send-ttl bob 30 hello
```

含义：

- 发给 `bob`
- TTL 为 30 秒
- 消息内容是 `hello`

## 5. 如何人工检验

下面给一套最直接的人工验收步骤。

### 5.1 检验发送和过期隐藏

1. 启动服务端。
2. 分别启动两个 CLI，登录 `alice` 和 `bob`。
3. 先把两人加成联系人。
4. `alice` 执行：

```text
send-ttl bob 5 hello-ttl
```

5. 立刻在 `bob` 侧打开会话，应该能看到这条消息。
6. 等待 6 秒以上，再次 `open` 同一会话，这条消息应该已经不见了。

预期：

- 过期前看得到
- 过期后历史里看不到

### 5.2 检验离线过期不补发

1. 让 `bob` 退出 CLI，保持离线。
2. `alice` 执行：

```text
send-ttl bob 5 offline-ttl
```

3. 等待 6 秒以上。
4. 再让 `bob` 登录并连上 WebSocket。

预期：

- `bob` 不会收到这条已经过期的离线消息

### 5.3 检验 TTL 被篡改会失效

这个项目里默认走 E2EE。

预期：

- 如果有人改动加密 envelope 里的 `ttl_seconds`
- 接收端解密会失败

这说明 TTL 已经被放进了认证元数据。

## 6. 沙箱内实际验证结果

我在沙箱里用临时数据库实际跑过一轮流程，结果如下：

```text
CHECK 1: send-ttl accepted -> 5 2026-04-02T08:37:49.230423+00:00
CHECK 2: before expiry messages -> 1
CHECK 3: decrypted text -> ttl works
CHECK 4: after expiry messages -> 0
CHECK 5: expired message rows in DB -> 0
CHECK 6: first websocket event after offline expiry -> system
CHECK 7: tampered ttl decrypt -> blocked as DecryptionError
```

这几项分别说明：

- 服务端已经接受并记录 TTL
- 过期前消息可读
- 过期后消息不会继续出现在历史里
- 服务端数据库中的过期消息已被删除
- 已过期的离线消息不会在用户重新上线后补发
- 篡改 TTL 会导致解密失败

另外，原有自动化测试也重新跑过，没有被这次改动破坏：

```text
.\.venv\Scripts\python.exe -m unittest -q
----------------------------------------------------------------------
Ran 3 tests in 1.130s

OK
```

## 7. 当前版本的边界

这次实现是基础可用版，边界如下：

- TTL 从服务端入库时开始计时，不是“已读后开始计时”
- CLI 只能用“过期后不再展示 + 打印过期提示”的方式近似表示“从 UI 移除”
- 这是课程原型需要的基础实现，不是复杂的商业级阅后即焚系统

## 8. 结论

本次已经完成了一个符合 `Project.pdf` 基本要求的 TTL / 自毁消息版本：

- 可发送带 TTL 的消息
- TTL 已进入加密认证元数据
- 过期消息不会继续展示
- 服务端会 best-effort 清理过期消息并阻止离线过期补发

对于当前项目阶段，这一版已经满足“基础简单，能用就好”的目标。
