# TLS 功能实现说明

## 1. 目标

按 `Project.pdf` 的以下硬性要求，为当前项目补齐 client-server 传输层 TLS：

- `4.2 Transport security`
- `7. Security Requirements` 中的 `Transport security: use TLS for client-server communication`

这次实现的目标很明确：

- HTTP API 改为可通过 `https://` 访问
- WebSocket 推送改为可通过 `wss://` 访问
- CLI 默认拒绝明文 `http://`，避免“代码支持 TLS，但实际仍然裸连”
- 本地开发环境可直接生成并复用证书，保证仓库里可以真正跑起来

## 2. 本次设计

### 2.1 采用的最小可用方案

这次没有引入外部反向代理，也没有要求用户自己手写 OpenSSL 命令，而是直接在仓库里补齐一套最小但完整的 TLS 流程：

1. 服务端启动脚本自动生成本地开发 CA 和服务端证书
2. Uvicorn 直接加载服务端证书和私钥，提供 HTTPS / WSS
3. CLI 侧为 HTTP 和 WebSocket 共用同一套受信 CA 校验逻辑
4. CLI 默认强制要求 `https://`，只有显式加 `--allow-insecure-http` 才允许旧的明文模式

这样做的原因是：

- `Project.pdf` 要求的是“使用 TLS”，不是“仓库里留一组证书文件但默认继续跑 HTTP”
- 如果客户端默认仍然接受明文连接，那么 TLS 很容易在演示或实际运行时被绕过
- 自签名开发证书如果不做校验，安全效果接近于没有，因此客户端必须显式信任本地 CA

### 2.2 证书工作流

当前工作流如下：

- `server.run_tls` 启动时调用 `server.tls.ensure_dev_tls_materials(...)`
- 如果 `certs/dev/` 下还没有证书，就自动生成：
  - `ca_cert.pem`
  - `ca_key.pem`
  - `server_cert.pem`
  - `server_key.pem`
- 服务端证书默认覆盖：
  - `localhost`
  - `127.0.0.1`
  - 当前启动时传入的 `--host`

这样可以直接满足当前项目最常见的本地演示方式：

- `https://127.0.0.1:8443`
- `wss://127.0.0.1:8443/ws?...`

### 2.3 客户端校验策略

客户端侧做了两件关键事：

1. `ApiClient` 使用 `ssl.create_default_context(...)` 创建校验上下文，再交给 `httpx.Client`
2. `WebSocketListener` 使用同一套 CA 证书创建 `ssl.SSLContext`，再交给 `websockets.sync.client.connect`

也就是说，这次不是“启用了 HTTPS 但关闭校验”，而是：

- 服务端有证书
- 客户端校验证书
- HTTP 和 WebSocket 都走同一套 TLS 信任链

### 2.4 为什么保留 `--allow-insecure-http`

从课程要求看，真正交付和演示应当走 TLS。

但仓库里已经有一批旧文档、旧测试习惯和历史开发流程仍以 `http://` 为基础。为了避免完全阻断调试，CLI 保留了：

```text
--allow-insecure-http
```

但这个开关是显式的、非默认的，目的只是：

- 兼容旧流程
- 明确告诉使用者这不是课程要求下的安全默认值

## 3. 实现位置

### 3.1 服务端

文件：

- [server/tls.py](/d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/server/tls.py)
- [server/run_tls.py](/d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/server/run_tls.py)

说明：

- `server/tls.py`
  - 负责生成本地开发 CA 和服务端证书
  - 证书 SAN 自动覆盖 `localhost`、`127.0.0.1` 和当前 host
- `server/run_tls.py`
  - 提供统一 HTTPS/WSS 启动入口
  - 自动准备证书后再调用 `uvicorn.run(...)`

### 3.2 客户端

文件：

- [client/tls.py](/d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/client/tls.py)
- [client/api_client.py](/d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/client/api_client.py)
- [client/ws_client.py](/d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/client/ws_client.py)
- [client/cli.py](/d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/client/cli.py)

说明：

- `client/tls.py`
  - 统一处理 base URL 校验
  - 统一解析 CA 证书路径
  - 统一创建 TLS `SSLContext`
- `client/api_client.py`
  - 默认只接受 `https://`
  - HTTP 请求默认做证书校验
- `client/ws_client.py`
  - `https://` 自动映射到 `wss://`
  - WebSocket 建连也使用同一 CA 证书进行验证
- `client/cli.py`
  - 默认服务器地址改为 `https://127.0.0.1:8443`
  - 支持 `--ca-cert`
  - 只有显式加 `--allow-insecure-http` 才允许回退到明文模式

### 3.3 自动化验证

文件：

- [tests/test_tls_transport.py](/d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/tests/test_tls_transport.py)

说明：

- 该测试会在临时目录里生成 TLS 证书和测试数据库
- 用真实 Uvicorn socket 起 HTTPS/WSS 服务
- 再用真实 `ApiClient`、`WebSocketListener`、`ClientE2EEManager` 跑完整链路

## 4. 如何使用

### 4.1 启动服务端

在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -m server.run_tls
```

默认行为：

- 监听 `https://127.0.0.1:8443`
- 自动生成 `certs/dev/` 下的 CA 和服务端证书

### 4.2 启动客户端

```powershell
.\.venv\Scripts\python.exe client\cli.py https://127.0.0.1:8443 --ca-cert certs\dev\ca_cert.pem
```

如果你使用默认证书目录，CLI 也可以自动发现该 CA：

```powershell
.\.venv\Scripts\python.exe client\cli.py https://127.0.0.1:8443
```

### 4.3 旧的明文模式

如果只是为了兼容旧调试流程，才允许显式这样启动：

```powershell
.\.venv\Scripts\python.exe client\cli.py http://127.0.0.1:8000 --allow-insecure-http
```

注意：

- 这不是课程要求下的安全默认值
- 不应作为最终演示或正式交付方式

## 5. 如何人工验证

### 5.1 验证客户端默认拒绝明文 HTTP

直接执行：

```powershell
.\.venv\Scripts\python.exe client\cli.py http://127.0.0.1:8000
```

预期：

- CLI 直接报错并拒绝启动
- 提示使用 `https://` 或显式加 `--allow-insecure-http`

### 5.2 验证 HTTPS / WSS 启动成功

1. 启动服务端：

```powershell
.\.venv\Scripts\python.exe -m server.run_tls
```

2. 启动客户端：

```powershell
.\.venv\Scripts\python.exe client\cli.py https://127.0.0.1:8443 --ca-cert certs\dev\ca_cert.pem
```

预期：

- CLI 会打印 `Using TLS CA certificate: ...`
- CLI 会打印 `Connected to https://127.0.0.1:8443`

### 5.3 验证 TLS 下完整消息流程

可以按原有 demo 流程开两个终端：

终端 A：

```text
register alice StrongPass123
login alice StrongPass123
send-request bob
send bob hello over tls
```

终端 B：

```text
register bob StrongPass123
login bob StrongPass123
pending
respond 1 accept
```

预期：

- 注册、登录、好友请求、消息发送都能正常工作
- Bob 在线时能通过 `wss://` 收到推送消息
- 消息正文仍然由 E2EE 负责保护，TLS 负责传输层防窃听和防中间人

## 6. 沙箱内实际验证结果

我在沙箱里实际跑了两组测试。

### 6.1 TLS 集成测试

命令：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_tls_transport -v
```

结果：

```text
Ran 2 tests in 1.999s

OK
```

覆盖点：

- `ApiClient` 默认拒绝 `http://`
- HTTPS 注册 / 登录
- WSS 在线连接建立
- 在 TLS 传输下完成好友建立、E2EE 发消息、Bob 通过 WebSocket 收到密文推送并成功本地解密

### 6.2 原有安全回归测试

命令：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_replay_protection -v
```

结果：

```text
Ran 3 tests in 0.909s

OK
```

这说明：

- 新增 TLS 逻辑没有破坏原有 replay protection / duplicate detection
- 现有 E2EE 消息流在这次改动后仍然可用

## 7. 当前边界

这次实现解决的是 `Project.pdf` 明确要求的 transport security，不代表所有安全问题都已经完成。

当前边界如下：

- 当前证书工作流是“本地开发 CA + 本地叶子证书”，适合课程项目演示和沙箱验证，不等于生产级证书运维
- CLI 默认强制 TLS，但仍保留显式的 `--allow-insecure-http` 调试后门
- 本地敏感状态仍未加密存储，这仍然是 `Project.pdf` 下尚未补齐的硬性缺口

## 8. 结论

这次已经把 TLS 从“文档里写着应该做”变成了“仓库里可以直接启动、客户端会校验、测试里真实跑通”的功能：

- 服务端现在可以直接提供 HTTPS / WSS
- 客户端默认按 TLS 要求连接并做证书校验
- 仓库内已有自动化测试证明 TLS 下的核心消息流程正常可用

按 `Project.pdf` 的 `4.2 Transport security` 和 `7. Security Requirements` 来看，这一项现在已经补齐。
