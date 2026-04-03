# 项目待实现项

这份文档只保留 `Project.pdf` 明确要求、但当前仓库还没做完的内容。

## 还必须做的

### 1. TLS

为什么要做：

- `4.2 Transport security` 和 `7. Security Requirements` 都明确要求 client-server 连接使用 TLS

当前缺口：

- 当前默认仍是 `http://` 和 `ws://`
- 仓库里没有 TLS 配置

代码证据：

- [client/cli.py](d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/client/cli.py#L296)
- [client/ws_client.py](d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/client/ws_client.py#L22)

### 2. 本地敏感数据安全存储

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
- `block` / `unblock` / `remove-contact`
- 非联系人默认不能直接发消息
- 离线密文转发
- `Sent` / `Delivered`
- 会话列表、未读数
- CLI 翻页 / incremental loading
- 指纹查看与人工 verified 标记
- trust reset / 重新验证流程
- replay protection / duplicate detection
- CLI 作为 UI 形式本身是符合要求的

## 不属于当前必须补的

下面这些不是 `Project.pdf` 的硬性缺口，所以这里不列入必须做：

- 更强的现代协议，比如 double ratchet / prekeys
- 多设备完整支持
- 额外的“next priority”工程建议

## 最终结论

如果只按 `Project.pdf` 严格看，你现在还必须补这 2 项：

1. TLS
2. 本地敏感数据安全存储
