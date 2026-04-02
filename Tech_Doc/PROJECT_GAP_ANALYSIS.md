# 项目待实现项

这份文档只保留 `Project.pdf` 明确要求、但当前仓库还没做完的内容。

## 还必须做的

### 1. 换钥后的 trust reset / 重新验证流程

为什么要做：

- `R6` 明确要求 key change detection，而且换钥后要有明确策略

当前缺口：

- 现在只能检测到换钥并拒绝继续
- 但没有用户可操作的 trust reset / re-verify 流程

代码证据：

- [client/e2ee_client.py](d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/client/e2ee_client.py#L107)
- [client/e2ee_client.py](d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/client/e2ee_client.py#L187)
- [client/e2ee_client.py](d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/client/e2ee_client.py#L248)

### 2. block / unblock / remove contact

为什么要做：

- `R15` 明确要求 users can remove friends and block users

当前缺口：

- 数据库有 `blocks` 表
- 发送请求和消息时也会检查 block
- 但没有 block / unblock / remove contact 的 CLI 或 API

代码证据：

- [server/db.py](d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/server/db.py#L118)
- [server/main.py](d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/server/main.py#L126)
- [server/main.py](d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/server/main.py#L319)
- [server/main.py](d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/server/main.py#L517)
- [client/cli.py](d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/client/cli.py#L19)

### 3. CLI 翻页

为什么要做：

- `R25` 明确要求 basic pagination or incremental loading

当前缺口：

- 后端已经支持 `before_id`
- 但 CLI 只有 `open <conversation_id> [limit]`
- 不能继续加载更早消息

代码证据：

- [server/main.py](d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/server/main.py#L591)
- [client/api_client.py](d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/client/api_client.py#L83)
- [client/cli.py](d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/client/cli.py#L257)

### 4. TLS

为什么要做：

- `4.2 Transport security` 和 `7. Security Requirements` 都明确要求 client-server 连接使用 TLS

当前缺口：

- 当前默认仍是 `http://` 和 `ws://`
- 仓库里没有 TLS 配置

代码证据：

- [client/cli.py](d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/client/cli.py#L296)
- [client/ws_client.py](d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/client/ws_client.py#L22)

### 5. 本地敏感数据安全存储

为什么要做：

- `7. Security Requirements` 明确要求 secure local storage

当前缺口：

- `client_state.json` 明文保存 OTP secret、token、私钥、trusted peer keys

代码证据：

- [client/state.py](d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/client/state.py#L9)
- [client/state.py](d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/client/state.py#L83)

## 已经做了，不用再补的

- 注册、密码哈希、登录限流、密码 + OTP 登录、登出
- 1:1 E2EE 私聊
- 好友请求发送 / 接受 / 拒绝 / 取消
- 非联系人默认不能直接发消息
- 离线密文转发
- `Sent` / `Delivered`
- 会话列表、未读数
- 指纹查看与人工 verified 标记
- replay protection / duplicate detection
- CLI 作为 UI 形式本身是符合要求的

## 不属于当前必须补的

下面这些不是 `Project.pdf` 的硬性缺口，所以这里不列入必须做：

- 更强的现代协议，比如 double ratchet / prekeys
- 多设备完整支持
- 额外的“next priority”工程建议

## 最终结论

如果只按 `Project.pdf` 严格看，你现在还必须补这 5 项：

1. trust reset / 重新验证流程
2. block / unblock / remove contact
3. CLI 翻页
4. TLS
5. 本地敏感数据安全存储
