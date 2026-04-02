# Trust Reset 功能实现说明

## 1. 目标

按照 `Project.pdf` 的 `R6` 要求，为当前仓库补上基础可用版的 trust reset 功能，满足下面几点：

- 当联系人身份公钥变化时，客户端明确报警
- 默认阻止继续发送和解密
- 用户可以手动执行 trust reset，接受对方当前新公钥作为新的 trusted key
- reset 之后仍然必须重新人工验证，才能恢复正常安全消息流程

这次实现刻意保持简单，不做复杂状态机，也不做多设备恢复，只做当前 CLI 原型最小可用的一版。

## 2. 本次设计

### 2.1 采用的策略

本次采用的策略是：

- 如果检测到对方公钥变化，立即阻止继续使用
- 用户必须显式执行：

```text
reset-trust <username>
```

- 执行后，客户端把“当前服务端上的新公钥”设为新的 trusted key
- 但这时仍然不能继续发消息或解密
- 只有再次执行：

```text
verify <username>
```

才会真正恢复正常使用

也就是说，这次的策略是：

- `block until re-verified`

这正是 `Project.pdf` 在 `R6` 里允许的策略之一。

### 2.2 为什么 reset-trust 之后还不能立刻继续

如果 `reset-trust` 一执行完就允许继续发消息，那么它本质上只是“把旧 trusted key 替换成新 key”，用户并没有真正完成重新核验。

所以本次把 trust reset 分成两步：

1. `reset-trust <username>`
2. `verify <username>`

这样设计的好处是：

- 用户必须显式确认自己知道“这个 key 已经变了”
- 用户必须再做一次人工验证，才会恢复消息能力
- 更符合 `R6` 的“重新验证”要求

## 3. trust reset 和指纹人工验证的区别

这两个功能有关联，但不是同一个东西。

### 指纹人工验证

作用：

- 让用户查看当前指纹
- 让用户把当前 trusted key 标记为 `verified`

命令：

```text
fingerprint <username>
verify <username>
```

重点：

- 它解决的是 `R5`
- 它回答的是“这把 key 我是否人工确认过”

### trust reset

作用：

- 在 key 已经变化之后，允许用户放弃旧 trusted key，改用当前新 key 作为新的 trusted candidate
- 但改完后仍然要求再次 `verify`

命令：

```text
reset-trust <username>
```

重点：

- 它解决的是 `R6`
- 它回答的是“旧 key 已经失效了，我是否接受现在这把新 key 进入重新验证流程”

一句话区分：

- `verify` 是确认当前 key
- `reset-trust` 是在 key 变了以后，切换到新 key，并要求重新确认

## 4. 实现位置

### 4.1 本地状态

文件：

- [client/state.py](d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/client/state.py)

新增状态：

- `reverify_required_peer_keys`

用途：

- 记录哪些 peer 在 trust reset 后还处于“必须重新验证”的状态

### 4.2 E2EE 管理层

文件：

- [client/e2ee_client.py](d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/client/e2ee_client.py)

新增能力：

- `_reverify_required_peer_keys()`
- `_get_reverify_required_peer()`
- `_describe_reverify_required()`
- `reset_peer_trust()`

核心逻辑：

1. 如果发现 key mismatch，现有逻辑仍然报 `TrustError`
2. 用户运行 `reset_peer_trust()` 后：
   - 当前服务端公钥写入 `trusted_peer_keys`
   - 旧 `verified_peer_keys` 记录被清掉
   - 当前 peer 被写入 `reverify_required_peer_keys`
3. 在 `resolve_peer_for_send()` 和 `resolve_peer_for_decrypt()` 中：
   - 只要 peer 还在 `reverify_required_peer_keys` 里
   - 就继续报 `TrustError`
   - 提示用户先 `fingerprint` 再 `verify`
4. 用户执行 `verify` 后：
   - 写入 `verified_peer_keys`
   - 同时移除 `reverify_required_peer_keys`

### 4.3 CLI

文件：

- [client/cli.py](d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/client/cli.py)

新增命令：

```text
reset-trust <username>
```

命令行为：

- 拉取该用户当前服务端公钥
- 覆盖本地 trusted key
- 清理旧 verified 状态
- 标记 `verification required: yes`
- 提示用户下一步运行：

```text
fingerprint <username>
verify <username>
```

## 5. 使用方式

### 5.1 正常情况

如果没有换钥：

```text
fingerprint bob
verify bob
```

### 5.2 检测到换钥

如果发送或解密时报错，类似：

```text
identity key changed for bob; trusted fingerprint ..., current server fingerprint .... refusing to continue until trust is reset
```

则处理流程是：

```text
fingerprint bob
reset-trust bob
fingerprint bob
verify bob
```

之后再继续发消息。

## 6. 如何人工检验

下面给出一套最直接的人工验收步骤。

### 6.1 检验换钥后会被阻止

1. 启动服务端。
2. 启动 `alice` 和 `bob` 两个客户端。
3. 先让 `alice` 对 `bob` 做过一次：

```text
verify bob
```

4. 让 `bob` 重新生成并发布新的身份公钥。
5. `alice` 再尝试发送消息。

预期：

- 会报 key changed 错误
- 不允许继续发送

### 6.2 检验 reset-trust 后仍然不能直接发送

1. `alice` 执行：

```text
reset-trust bob
```

2. 再次直接尝试发送消息。

预期：

- 仍然不允许发送
- 错误提示会要求先重新验证

### 6.3 检验 verify 后恢复正常

1. `alice` 执行：

```text
fingerprint bob
verify bob
```

2. 再尝试发送消息。

预期：

- 此时消息可以正常发送

## 7. 沙箱内实际验证结果

我在沙箱里用临时数据库实际跑过一轮流程，结果如下：

```text
CHECK 1: before key change -> {'verified': True, 'trust_state': 'trusted'}
CHECK 2: after key change -> {'verified': False, 'trust_state': 'mismatch', 'warning': 'identity key changed for bob; trusted fingerprint 1ec6ec08a34a6e83bd11458dc94d9be749139d94613cb23ee0e01b0a5171272f, current server fingerprint 98cc4f74e59810ee65234e19be7dc287cb2fd03092e7f58f111a4b27ad4e6d0f. refusing to continue until trust is reset'}
CHECK 3: send before reset -> blocked as TrustError
CHECK 4: reset-trust stored -> {'fingerprint': '98cc4f74e59810ee65234e19be7dc287cb2fd03092e7f58f111a4b27ad4e6d0f', 'reset_at': '2026-04-02T09:42:41.164462+00:00'}
CHECK 5: after reset -> {'verified': False, 'trust_state': 'trusted', 'verification_required': True, 'warning': 'peer bob must be re-verified before secure messaging continues; current trusted fingerprint 98cc4f74e59810ee65234e19be7dc287cb2fd03092e7f58f111a4b27ad4e6d0f. run: fingerprint bob then verify bob'}
CHECK 6: send after reset but before verify -> blocked as TrustError
CHECK 7: verify after reset -> {'verified_fingerprint': '98cc4f74e59810ee65234e19be7dc287cb2fd03092e7f58f111a4b27ad4e6d0f', 'verification_required': False, 'verified': True}
CHECK 8: send after verify -> envelope length 250
CHECK 9: original vs rotated fingerprint -> 1ec6ec08a34a6e83bd11458dc94d9be749139d94613cb23ee0e01b0a5171272f 98cc4f74e59810ee65234e19be7dc287cb2fd03092e7f58f111a4b27ad4e6d0f
```

这些结果说明：

- 换钥后会先阻止继续
- reset-trust 只是把新 key 纳入新的 trusted candidate
- 在 verify 之前依然会阻止继续
- verify 之后才恢复正常发送

另外，原有自动化测试也重新跑过，没有被这次改动破坏：

```text
.\.venv\Scripts\python.exe -m unittest -q
----------------------------------------------------------------------
Ran 3 tests in 1.074s

OK
```

## 8. 当前边界

这次实现是最小可用版，边界如下：

- trust reset 只管理单设备 `cli-device-1`
- 不做跨设备同步
- reset 后仍然依赖用户自己做带外指纹核验
- 旧历史消息如果是基于旧公钥建立的，换钥后可能无法继续正常解密

## 9. 结论

本次已经完成了一个满足 `Project.pdf R6` 基本要求的 trust reset 版本：

- 检测到换钥会明确报警
- 默认阻止继续
- 用户可以手动 reset trust
- reset 之后必须重新 verify

对于当前项目阶段，这一版已经满足“基础简单，能用就好”的目标。
