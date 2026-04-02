# 指纹人工验证功能实现说明

## 1. 目标

按照 `Project.pdf` 的 `R5` 要求，为当前仓库补上基础可用版的指纹人工验证功能，满足下面两点：

- 能向用户显示联系人设备身份公钥的指纹
- 能让用户把联系人当前公钥标记为本地 `verified`

这次实现故意保持简单，不做复杂的安全号码系统，也不把它扩展成完整的 trust reset 机制。当前目标只是把 `R5` 做到“基础简单，能用就好”。

## 2. 本次设计

### 2.1 继续保留现有 TOFU

当前项目原本已经有 TOFU：

- 第一次和联系人建立安全关系时，把对方当前公钥记到本地
- 以后如果服务端返回不同公钥，就报错并阻止继续

这次没有推翻这套设计，只是在它上面额外加了一层“人工 verified 标记”。

原因很简单：

- 现有代码已经围绕 TOFU 跑通
- `Project.pdf` 对 `R5` 的要求只是“显示 fingerprint，并允许标记 verified”
- 没必要为了这一步重做整套信任模型

### 2.2 verified 和 trusted 分开

本次把两个概念分开：

- `trusted`: 当前客户端真正用于加解密的本地信任公钥
- `verified`: 用户人工核对过后，明确确认的那把公钥

这样做的好处是：

- 不会把“第一次见到就默认信任”误当成“用户已经人工核验”
- 用户可以先看指纹，再决定是否 `verify`

### 2.3 最小命令设计

新加两个 CLI 命令：

```text
fingerprint <username>
verify <username>
```

含义：

- `fingerprint <username>`
  - 查看该用户当前服务端公钥的指纹
  - 查看本地 trusted fingerprint
  - 查看是否已经 verified
- `verify <username>`
  - 把该用户当前 trusted fingerprint 记为本地 verified

这是最简单直接的用户界面，也已经满足 `Project.pdf` 对 UI 的要求。

### 2.4 换钥后不再视为 verified

如果对方公钥变了：

- 原有 TOFU 逻辑仍然会报 key mismatch
- `fingerprint <username>` 会显示 `trust_state: mismatch`
- 之前的 verified 状态不会再被当成有效 verified

这一步很重要，因为否则旧 verified 标记会误导用户。

注意：

- 这不等于已经实现 trust reset
- trust reset 仍然是后续要补的 `R6` 缺口

## 3. 实现位置

### 3.1 本地状态

文件：

- [client/state.py](d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/client/state.py)

改动：

- 本地状态新增 `verified_peer_keys`
- 保存时会和其他本地字典状态一起合并落盘

当前核心状态包括：

- `device_keys`
- `trusted_peer_keys`
- `verified_peer_keys`

### 3.2 E2EE 管理层

文件：

- [client/e2ee_client.py](d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/client/e2ee_client.py)

新增能力：

- `get_peer_verification_status()`
  - 返回 peer 当前的 server fingerprint、trusted fingerprint、verified 状态、warning
- `mark_peer_verified()`
  - 将当前 trusted fingerprint 标记为 verified

实现要点：

- 如果还没有本地 trusted key，`verify` 会先获取当前公钥并建立 trusted 记录
- 如果当前 server key 和本地 trusted key 不一致，则拒绝 verify，并交给后续 trust reset 处理
- 如果 verified 记录和当前 trusted key 不一致，会自动视为失效

### 3.3 CLI

文件：

- [client/cli.py](d:/Learning/Year3%20Sem2/COMP3334/Project_Code/Code/client/cli.py)

新增命令：

```text
fingerprint <username>
verify <username>
```

输出内容包括：

- peer 用户名
- server device id
- server fingerprint
- trusted fingerprint
- trust state
- verified yes/no
- verified_at
- warning

## 4. 使用方式

### 4.1 查看对方指纹

```text
fingerprint bob
```

典型输出会包含：

- `server fingerprint`
- `trusted fingerprint`
- `trust state`
- `verified`

### 4.2 手工验证对方

先通过课题允许的方式做线下核对，比如面对面、语音、截图对比等，然后执行：

```text
verify bob
```

如果成功，CLI 会输出：

- 已标记的 fingerprint
- `verified: yes`
- `verified at: ...`

## 5. 如何人工检验

下面给出一套最直接的人工验收步骤。

### 5.1 检验未验证状态

1. 启动服务端。
2. 分别启动 `alice` 和 `bob` 两个客户端并登录。
3. 在 `alice` 侧执行：

```text
fingerprint bob
```

预期：

- 能看到 `bob` 当前的 `server fingerprint`
- `verified` 初始应为 `no`

### 5.2 检验人工 verify

1. 在 `alice` 侧确认 `bob` 的 fingerprint。
2. 执行：

```text
verify bob
```

3. 再执行一次：

```text
fingerprint bob
```

预期：

- `verified` 变成 `yes`
- 能看到 `verified at`

### 5.3 检验换钥后 verified 不再生效

1. 让 `bob` 重新生成并上传新的身份公钥。
2. 在 `alice` 侧再次执行：

```text
fingerprint bob
```

预期：

- `trust state` 变成 `mismatch`
- `verified` 不再是 `yes`
- 会出现 key changed 警告

这说明：

- verified 标记没有掩盖换钥风险
- 当前系统仍然坚持原来的 key change detection 策略

## 6. 沙箱内实际验证结果

我在沙箱里用临时数据库实际跑过一轮流程，结果如下：

```text
CHECK 1: before manual verify -> {'verified': False, 'trust_state': 'untrusted', 'server_fingerprint': '560f83fea0ed693206929b7b41281394fe495500732b60ef399003a96b003df5'}
CHECK 2: verify stored -> {'verified_fingerprint': '560f83fea0ed693206929b7b41281394fe495500732b60ef399003a96b003df5', 'verified_at': '2026-04-02T09:24:45.702427+00:00'}
CHECK 3: after manual verify -> {'verified': True, 'trust_state': 'trusted', 'trusted_fingerprint': '560f83fea0ed693206929b7b41281394fe495500732b60ef399003a96b003df5', 'verified_at': '2026-04-02T09:24:45.702427+00:00'}
CHECK 4: local verified state keys -> ['bob']
CHECK 5: after peer key change -> {'verified': False, 'trust_state': 'mismatch', 'warning': 'identity key changed for bob; trusted fingerprint 560f83fea0ed693206929b7b41281394fe495500732b60ef399003a96b003df5, current server fingerprint 3381761aa6eacf9d92e6c997ddf023256a625e589b9e9bbb876bd23cdfaab503. refusing to continue until trust is reset'}
CHECK 6: alice local fingerprint -> ce660c51194e379eb35c9cce013fb8fa896ae42ba1240fe61020b1d9c21319e3
CHECK 7: bob original fingerprint -> 560f83fea0ed693206929b7b41281394fe495500732b60ef399003a96b003df5
CHECK 8: bob rotated fingerprint -> 3381761aa6eacf9d92e6c997ddf023256a625e589b9e9bbb876bd23cdfaab503
```

这些结果说明：

- 初始状态下 peer 还没有被人工验证
- 执行 verify 后，verified 状态已经落到本地状态里
- 再查询时会显示 verified
- 如果 peer 换钥，系统会显示 mismatch，verified 不再被视为有效

另外，原有自动化测试也重新跑过，没有被这次改动破坏：

```text
.\.venv\Scripts\python.exe -m unittest -q
----------------------------------------------------------------------
Ran 3 tests in 1.034s

OK
```

## 7. 当前边界

这次实现是最小可用版，边界如下：

- 指纹是 SHA-256 十六进制字符串，不是更复杂的 safety number
- verified 只保存在本地状态文件中，不跨设备同步
- 目前只实现了 `R5`
- trust reset 仍然没有做

## 8. 结论

本次已经完成了一个满足 `Project.pdf R5` 基本要求的指纹人工验证版本：

- 能查看 peer 的 fingerprint
- 能把 peer 当前 trusted key 标记为本地 verified
- 换钥后不会错误地继续显示为 verified

对于当前项目阶段，这一版已经满足“基础简单，能用就好”的目标。
