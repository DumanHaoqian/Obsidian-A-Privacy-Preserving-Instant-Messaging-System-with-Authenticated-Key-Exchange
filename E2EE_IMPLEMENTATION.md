# E2EE V1 Implementation Guide

## 1. 目标

本次改造把原项目从“服务器存明文消息”升级为“客户端端到端加密，服务器只存密文 envelope”的实用 V1。

这版 E2EE 的边界非常明确：

- 单设备/用户
- 客户端长期身份密钥
- 客户端本地加密、解密
- 服务器不拥有明文
- TOFU 首次信任
- 检测到同一用户名公钥变化时拒绝继续发送

这版没有实现的内容：

- Signal 双棘轮
- 预密钥体系
- 前向保密轮换
- 指纹人工比对 UI
- 自动恢复信任迁移
- 重放保护

## 2. 这次新增或修改了哪些文件

### 2.1 `shared/e2ee.py`

作用：

- 放置所有可在客户端和未来共享使用的密码学基础逻辑
- 统一消息 envelope 结构
- 统一加密、解密、指纹计算逻辑

主要内容：

- `generate_identity_keypair()`
  - 生成 X25519 长期密钥对
  - 返回 `device_id`、`private_key`、`public_key`、`fingerprint`
- `public_key_fingerprint()`
  - 对公钥做 SHA-256 指纹
- `build_aad()`
  - 构造 AES-GCM 认证附加数据
- `encrypt_message()`
  - 用发送方私钥和接收方公钥计算共享密钥
  - 用 HKDF 派生 AES-GCM 内容密钥
  - 输出 JSON envelope 字符串
- `decrypt_message()`
  - 用本地私钥和对端公钥恢复共享密钥
  - 校验 AAD 后解密

实现选择：

- 非对称密钥交换：X25519
- KDF：HKDF-SHA256
- 对称加密：AES-GCM
- Envelope 存储格式：JSON 文本

### 2.2 `client/e2ee_client.py`

作用：

- 管理客户端本地长期密钥
- 管理 TOFU 信任缓存
- 对接服务端现有 `/identity-key` 接口
- 为 CLI 提供“发送前加密”和“显示前解密”的高层方法

主要内容：

- `ensure_local_identity()`
  - 确保当前用户名在本地存在长期身份密钥
- `publish_identity()`
  - 把本地真实公钥发布到服务端
- `_fetch_remote_identity()`
  - 读取对端当前公钥
- `resolve_peer_for_send()`
  - 发送前进行 TOFU 检查
  - 若首次看到该 peer，则写入本地信任缓存
  - 若发现公钥变化，则拒绝发送
- `resolve_peer_for_decrypt()`
  - 解密时优先使用已信任的 peer 公钥
  - 若此前没信任过，首次读取服务端公钥并写入 TOFU 缓存
- `encrypt_outbound_message()`
  - 把用户输入的明文转换为密文 envelope
- `decrypt_message_for_user()`
  - 按消息方向决定“本地私钥 + 哪个 peer 公钥”来解密

### 2.3 `client/state.py`

作用：

- 扩展客户端本地状态文件结构
- 为旧版本状态文件提供向后兼容的默认字段补齐

新增状态项：

- `device_keys`
  - 每个本地用户名对应一个长期身份密钥对
- `trusted_peer_keys`
  - 每个本地用户名下，对每个 peer 的 TOFU 信任记录

当前 `client/client_state.json` 结构核心如下：

```json
{
  "access_token": "...",
  "username": "alice",
  "known_otp_secrets": {
    "alice": "..."
  },
  "device_keys": {
    "alice": {
      "device_id": "cli-device-1",
      "private_key": "...",
      "public_key": "...",
      "fingerprint": "..."
    }
  },
  "trusted_peer_keys": {
    "alice": {
      "bob": {
        "device_id": "cli-device-1",
        "public_key": "...",
        "fingerprint": "...",
        "trusted_at": "..."
      }
    }
  }
}
```

### 2.4 `client/api_client.py`

作用：

- 让客户端可以读取对端身份公钥
- 让 `send_message()` 支持显式 `message_type`

本次变化：

- 新增 `get_identity_keys(username)`
- `send_message()` 增加 `message_type` 参数

### 2.5 `client/cli.py`

作用：

- 把原本明文聊天流程切换成默认 E2EE
- 保持用户命令不变

本次变化：

- 登录成功后自动确保本地身份密钥存在并上传真实公钥
- `send` 改为：
  - 加密明文
  - 调用 `/messages/send` 发送密文 envelope
- `open` 改为：
  - 拉取消息后本地解密再显示
- WebSocket 收到 `new_message` 时：
  - 本地解密再显示
  - 然后保留原有自动 ACK
- `store-dev-key` 改为：
  - 确保真实密钥存在并重新发布
  - 打印设备指纹

### 2.6 `server/schemas.py`

作用：

- 允许消息类型新增 `e2ee_text`
- 允许密文 envelope 通过更大的长度校验

变化：

- `message_type`
  - 从 `Literal['text']`
  - 扩展为 `Literal['text', 'e2ee_text']`
- `content`
  - 最大长度从 4000 提高到 16000

### 2.7 `server/config.py`

作用：

- 区分“明文输入长度”和“密文 envelope 存储长度”

变化：

- `MAX_PLAINTEXT_MESSAGE_LENGTH = 4000`
- `MAX_ENCRYPTED_MESSAGE_LENGTH = 16000`
- `MAX_MESSAGE_LENGTH = MAX_ENCRYPTED_MESSAGE_LENGTH`

### 2.8 `server/main.py`

作用：

- 兼容接收 `e2ee_text`
- 不在会话预览里泄露明文

本次变化：

- `/messages/send`
  - 明文消息仍按 4000 校验
  - 密文消息按 envelope 上限校验
- `/conversations`
  - 若最后一条消息类型是 `e2ee_text`
  - `last_message_preview` 固定显示 `[encrypted]`

服务端其余行为保持原样：

- 仍然转发消息
- 仍然保存 `content`
- 仍然返回 `content`
- 但对于加密消息，它看到的只是 envelope 文本

### 2.9 `requirements.txt`

作用：

- 新增 `cryptography` 依赖

## 3. 新的端到端加密流程

### 3.1 登录与身份初始化流程

1. 用户执行 `login <username> <password>`
2. CLI 完成原有密码 + OTP 登录
3. 登录成功后：
   - 若本地没有该用户名的长期身份密钥，则生成一对 X25519 密钥
   - 将公钥发布到服务端 `/identity-key`
4. CLI 打印设备指纹
5. WebSocket 建立连接

结果：

- 当前用户已具备可接收密文消息的真实身份公钥
- 其他联系人现在可以安全地向这个用户加密发送消息

### 3.2 首次发送给某个联系人

1. Alice 输入 `send bob hello`
2. CLI 读取 Alice 本地私钥
3. CLI 通过 `/identity-key/bob` 获取 Bob 公钥
4. 如果 Alice 本地还没有信任 Bob：
   - 把 Bob 当前公钥写入 `trusted_peer_keys`
   - 这就是 TOFU
5. CLI 使用：
   - Alice 私钥
   - Bob 公钥
   - HKDF
   - AES-GCM
   生成密文 envelope
6. CLI 调用 `/messages/send`，`message_type=e2ee_text`
7. 服务端把 envelope 当普通字符串存进 `messages.content`

结果：

- 服务端无法看到 `hello`
- 只看到一段 JSON 密文 envelope

### 3.3 接收方在线时

1. 服务端把 envelope 通过 WebSocket 推送给 Bob
2. Bob CLI 收到 `new_message`
3. Bob CLI：
   - 识别 `message_type=e2ee_text`
   - 读取 Bob 本地私钥
   - 读取或建立对 Alice 的 TOFU 公钥缓存
   - 使用本地私钥 + Alice 公钥解密
4. CLI 向用户显示明文
5. 保留原有 `/messages/ack`

结果：

- Bob 看到明文
- Alice 仍能看到 delivered

### 3.4 接收方离线时

1. Alice 发送密文 envelope
2. 服务端把 envelope 存库，`is_offline_queued=1`
3. Bob 重新连上 WebSocket
4. 服务端把未送达密文 envelope 补发给 Bob
5. Bob CLI 本地解密后显示明文
6. Bob 自动 ACK

结果：

- 离线补发继续有效
- 服务端补发的仍是密文，不是明文

### 3.5 打开历史会话时

1. 用户执行 `open <conversation_id>`
2. 服务端返回消息列表，其中 `content` 对于加密消息是 envelope
3. CLI 遍历消息
4. 对 `e2ee_text` 本地解密
5. 最终打印给用户的是明文内容

结果：

- 本地用户像以前一样能读历史
- 服务端仍只保存密文

## 4. Envelope 长什么样

当前 envelope 是一个 JSON 字符串，字段固定包含：

```json
{
  "alg": "x25519-hkdf-sha256-aesgcm",
  "ciphertext": "...",
  "nonce": "...",
  "salt": "...",
  "sender_device_id": "cli-device-1",
  "v": 1
}
```

字段说明：

- `v`
  - envelope 版本
- `alg`
  - 算法标识
- `sender_device_id`
  - 发送方设备 ID
- `salt`
  - HKDF salt
- `nonce`
  - AES-GCM nonce
- `ciphertext`
  - 实际密文和认证标签

## 5. AAD 绑定了什么

当前 AES-GCM 的 AAD 绑定这些元数据：

- `from_username`
- `to_username`
- `sender_device_id`
- `message_type`

这意味着如果服务端篡改这些字段之一，解密会失败。

这不能隐藏元数据，但能防止“改字段仍被客户端当真”。

## 6. TOFU 是怎么工作的

TOFU = Trust On First Use。

当前策略：

- 第一次和某个 peer 通信时，客户端读取服务端当前公钥并本地缓存
- 之后再次发送给该 peer 时，会重新读取服务端公钥并与缓存比对
- 如果不同，直接拒绝发送

为什么这样做：

- 第一次仍然需要信任服务器返回的是对的
- 但后续如果服务器悄悄换钥，就不会被静默接受

当前拒绝发送的错误会长这样：

```text
error: identity key changed for bob; trusted fingerprint <old>, current server fingerprint <new>. refusing to continue until trust is reset
```

## 7. 为什么现在算“真正拥有端到端加密”

改造前：

- CLI 把明文 `hello bob` 直接发到服务端
- 服务端在 `messages.content` 中明文存储 `hello bob`
- 服务端和任何能读库的人都能看到消息内容

改造后：

- CLI 在本地把 `hello bob` 加密
- 服务端只收到 envelope/ciphertext
- 服务端不会持有解密所需的本地私钥
- Bob 只能依赖自己的本地私钥恢复明文

因此“消息正文保密”这一点已经从服务器侧移到了客户端侧。

## 8. 如何验证改造前后差异

### 8.1 验证改造前没有 E2EE

在旧版本里：

1. Alice 和 Bob 建立联系人
2. Alice 执行：

```text
send bob hello bob
```

3. 打开数据库查看：

```powershell
cd "D:\Learning\Year3 Sem2\COMP3334\Project_Code\Code"
.\.venv\Scripts\python.exe -c "import sqlite3; conn=sqlite3.connect('data/im_phase1.db'); print(conn.execute('select id, content, message_type from messages order by id desc limit 3').fetchall())"
```

旧版本预期：

- `content` 里直接出现 `hello bob`
- `message_type` 是 `text`

### 8.2 验证改造后拥有 E2EE

1. 清空旧状态：

```powershell
Remove-Item .\data\im_phase1.db -Force -ErrorAction SilentlyContinue
Remove-Item .\client\client_state.json -Force -ErrorAction SilentlyContinue
```

2. 启动服务端
3. 启动 Alice 和 Bob 两个 CLI
4. 分别注册并登录
5. 建立联系人
6. Alice 执行：

```text
send bob hello bob
```

7. 再查看数据库：

```powershell
cd "D:\Learning\Year3 Sem2\COMP3334\Project_Code\Code"
.\.venv\Scripts\python.exe -c "import sqlite3; conn=sqlite3.connect('data/im_phase1.db'); print(conn.execute('select id, content, message_type from messages order by id desc limit 3').fetchall())"
```

新版本预期：

- `message_type` 是 `e2ee_text`
- `content` 是一段 JSON envelope
- 这段 `content` 中不应出现原始字符串 `hello bob`

### 8.3 验证聊天仍然能用

终端 A：

```text
register alice StrongPass123
login alice StrongPass123
```

终端 B：

```text
register bob StrongPass123
login bob StrongPass123
```

终端 A：

```text
send-request bob
```

终端 B：

```text
pending
respond 1 accept
```

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

- Bob 看到明文 `hello bob`
- Alice 看到 delivered
- `conversations` 的 `last_message_preview` 显示 `[encrypted]`

### 8.4 验证离线消息仍然可用

1. Bob 退出客户端
2. Alice 执行：

```text
send bob while_you_were_offline
```

3. Bob 重新启动并登录

预期：

- Bob 收到离线消息并看到解密后的明文
- 数据库仍只存密文 envelope

### 8.5 验证 TOFU 与换钥拒绝

1. Alice 和 Bob 先正常完成一次加密聊天
2. 此时 Alice 本地已经缓存了 Bob 的 trusted fingerprint
3. 手工改数据库里 Bob 的公钥：

```powershell
cd "D:\Learning\Year3 Sem2\COMP3334\Project_Code\Code"
.\.venv\Scripts\python.exe -c "import base64, sqlite3; from cryptography.hazmat.primitives import serialization; from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey; conn=sqlite3.connect('data/im_phase1.db'); pub = X25519PrivateKey.generate().public_key().public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw); conn.execute(\"update identity_public_keys set public_key=? where user_id=(select id from users where username='bob')\", (base64.b64encode(pub).decode('ascii'),)); conn.commit(); print('updated')"
```

4. Alice 再次执行：

```text
send bob hello_again
```

预期：

- Alice 客户端拒绝发送
- 输出明确的 key changed / trust mismatch 错误

## 9. 为什么服务端还能看到这些信息

即使有了 E2EE，服务端仍然知道：

- 谁给谁发消息
- 谁和谁是联系人
- 会话 ID
- 消息发送时间
- 是否 delivered
- 是否已读
- 在线状态

它只是不能直接看到消息正文。

这是当前架构下的正常结果，不代表实现错误。

## 10. 可能看到的新错误及含义

### 10.1 `peer <username> has no published identity key`

含义：

- 对方当前没有已发布的 E2EE 公钥

常见原因：

- 对方还没登录过新版客户端
- 对方清空了状态但还没重新登录

解决：

- 让对方先登录一次
- 或让对方执行 `store-dev-key`

### 10.2 `identity key changed for <username> ... refusing to continue`

含义：

- 当前服务端返回的 peer 公钥和你第一次信任时缓存的不同

常见原因：

- 对方真的重装/重置了环境
- 服务端数据库被改了
- 存在 MITM 风险

解决：

- 如果你确信这是合法重置，删除本地 `client/client_state.json` 后重新建立信任
- 如果你不确定，不要继续

### 10.3 `[encrypted message unavailable: ...]`

含义：

- 客户端拿到了密文，但当前无法成功解密

常见原因：

- 本地状态文件被删了，但数据库里还保留旧会话
- peer 公钥不可用
- envelope 被破坏

解决：

- 在允许重置的前提下清空 `data/im_phase1.db` 和 `client/client_state.json` 后重新开始

## 11. 与旧数据兼容的结论

本次实现默认选择“允许重置，不兼容旧明文状态”。

这意味着：

- 旧数据库里的明文消息不是本版重点兼容对象
- 旧客户端状态文件若没有对应密钥，也可能无法解密新旧混合场景
- 最稳的验证方式是清空数据库和本地状态后从头跑一遍

## 12. 最后总结

本次改造已经完成了“服务器无法读取新消息正文”的核心目标。

你现在拥有的是一版真实可运行的客户端 E2EE V1：

- 本地长期身份密钥
- 客户端加密
- 客户端解密
- 服务端只存密文
- TOFU 公钥绑定
- 公钥变更拒绝发送
- 离线补发、已读、delivered 仍保留

但它仍不是完整的现代安全消息协议，还需要继续补：

- 预密钥
- 前向保密
- 双棘轮
- replay protection
- 指纹人工验证
- key change UX
