# COMP3334 - 网络安全课程项目报告

## Obsidian: 端到端加密即时通讯系统

---

**团队 ID:** [Team28]  
**提交日期:** 2026年4月

**团队成员:**
FENG Luquan:
YANG Shu: 23098979D
LIU Chen:
DU Haoqian:
Du Haoyang

---

## 目录

1. [摘要](#1-摘要)
2. [引言](#2-引言)
3. [威胁模型与假设](#3-威胁模型与假设)
4. [系统架构](#4-系统架构)
5. [设计说明](#5-设计说明)
6. [安全分析](#6-安全分析)
7. [测试评估](#7-测试评估)
8. [结论](#8-结论)

---

## 1. 摘要

本项目实现了一个名为 **Obsidian** 的端到端加密即时通讯系统，旨在提供一个完整的安全通讯原型。系统采用现代密码学技术，确保消息内容在传输和存储过程中对服务器保持机密性。

**核心技术特点:**
- **端到端加密**: 使用 X25519 椭圆曲线密钥交换 + HKDF-SHA256 密钥派生 + AES-GCM 认证加密
- **双重认证**: 密码认证 + TOTP 二次验证
- **安全传输**: HTTPS/WSS TLS 加密传输
- **信任管理**: TOFU (Trust On First Use) 信任模型
- **攻击防护**: 防重放攻击、防中间人攻击

**主要成果:**
- 完整的客户端-服务器架构原型
- 支持 1对1 实时加密通讯
- 完善的用户管理和社交关系系统
- 详细的安全测试验证


---

## 2. 引言

### 2.1 项目背景

传统的即时通讯系统往往存在安全隐患：

- **服务器可访问明文**: 大多数商业 IM 服务提供商能够访问用户消息内容
- **隐私泄露风险**: 用户数据可能被第三方机构获取或滥用
- **安全威胁**: 面临网络窃听、中间人攻击、重放攻击等威胁

端到端加密技术是解决这些问题的关键方案，它确保只有通信双方能够访问消息内容，即使是服务提供商也无法解密。

### 2.2 项目目标

本项目的目标是实现一个学术级的端到端加密即时通讯系统，具体包括：

1. **技术验证**: 验证现代密码学协议在实际系统中的应用
2. **安全保证**: 实现服务器无法获取明文的安全目标
3. **原型完整**: 提供功能完整的即时通讯原型

### 2.3 现有方案分析

| 方案 | 优点 | 缺点 |
|------|------|------|
| Signal Protocol | 前向安全、多设备支持 | 实现复杂 |
| WhatsApp E2EE | 用户基数大、易用性好 | 闭源、元数据泄露 |
| Telegram Secret Chat | 端到端加密 | 仅限1对1、无群组 |
| **本项目** | **学术透明、完整实现** | **单设备、静态密钥** |

---

## 3. 威胁模型与假设

### 3.1 威胁模型

```
威胁者能力分析:
├── 网络攻击者
│   ├── 窃听网络流量 [防护] (被TLS+E2EE防护)
│   ├── 修改网络数据 [防护] (被数字签名防护)
│   └── 重放攻击 [防护] (被replay token防护)
├── 服务器攻击者
│   ├── 获取服务器数据 [部分] (只能获取密文)
│   ├── 修改服务器逻辑 [假设] (假设服务器代码可信)
│   └── 注入恶意代码 [假设] (假设服务器环境安全)
└── 客户端攻击者
    ├── 本地数据访问 [假设] (假设客户端环境安全)
    ├── 恶意软件感染 [超出] (超出项目范围)
    └── 物理设备获取 [假设] (假设设备安全)
```

### 3.2 安全假设

**可信假设:**
- 服务器代码未被篡改且行为正确
- 客户端运行环境安全，无恶意软件
- 密码学库实现正确无误
- 操作系统随机数生成器质量可靠
- 用户能够正确验证对方指纹

**不可信假设:**
- 网络传输可能被窃听或篡改
- 服务器可能被攻击者获取物理访问
- 用户设备可能丢失或被盗

### 3.3 保护目标

| 安全目标    | 具体实现            | 保护程度 |
| ------- | --------------- | ---- |
| **机密性** | 消息内容端到端加密       | 完全保护 |
| **完整性** | AES-GCM 认证加密    | 完全保护 |
| **认证性** | 公钥指纹验证          | 完全保护 |
| **抗重放** | Replay token 机制 | 完全保护 |


---

## 4. 系统架构

### 4.1 整体架构图

```
┌─────────────────┐    HTTPS/WSS    ┌─────────────────┐
│   Client A      │ ◄─────────────► │   Server        │
│                 │                 │                 │
│ ┌─────────────┐ │                 │ ┌─────────────┐ │
│ │ CLI界面     │ │                 │ │ FastAPI     │ │
│ └─────────────┘ │                 │ └─────────────┘ │
│ ┌─────────────┐ │                 │ ┌─────────────┐ │
│ │ E2EE加密    │ │                 │ │ SQLite DB   │ │
│ └─────────────┘ │                 │ └─────────────┘ │
│ ┌─────────────┐ │                 │ ┌─────────────┐ │
│ │ 本地状态    │ │                 │ │ WebSocket  │ │
│ └─────────────┘ │                 │ └─────────────┘ │
└─────────────────┘                 └─────────────────┘
         │                                   │
         │                                   │
         └───────────────────────────────────┘
                    加密消息流
```

### 4.2 数据流设计

#### 4.2.1 消息发送流程
```
1. 用户输入明文消息
   ↓
2. 客户端获取接收方公钥 (GET /identity-key/{username})
   ↓
3. 本地 X25519 密钥交换
   ↓
4. HKDF-SHA256 密钥派生
   ↓
5. AES-GCM 加密消息 + AAD 绑定
   ↓
6. 构建 JSON 密文信封
   ↓
7. HTTPS 发送到服务器 (POST /messages/send)
   ↓
8. 服务器存储密文到 SQLite
   ↓
9. WebSocket 推送给接收方
```

#### 4.2.2 消息接收流程
```
1. 接收 WebSocket 推送事件
   ↓
2. 获取发送方公钥 (本地缓存或服务器查询)
   ↓
3. 本地 X25519 密钥交换
   ↓
4. HKDF-SHA256 密钥派生
   ↓
5. AES-GCM 解密消息 + AAD 验证
   ↓
6. 显示明文消息给用户
   ↓
7. 发送已读回执 (POST /messages/ack)
```

### 4.3 技术栈

| 组件 | 技术选择 | 版本 | 作用 |
|------|----------|------|------|
| **后端框架** | FastAPI | ≥0.115.0 | REST API 和 WebSocket |
| **数据库** | SQLite | 3.x | 用户数据和消息存储 |
| **加密库** | cryptography | ≥42.0.0 | 密码学原语实现 |
| **HTTP客户端** | httpx | ≥0.27.0 | 异步 HTTP 请求 |
| **WebSocket** | websockets | ≥12.0 | 实时通信 |
| **密码哈希** | argon2-cffi | ≥23.1.0 | 密码安全存储 |
| **数据验证** | pydantic | ≥2.0.0 | API 数据验证 |

---

## 5. 设计说明

### 5.1 协议设计

#### 5.1.1 会话建立协议

**阶段1: 用户注册**
```http
POST /register
Content-Type: application/json

{
  "username": "alice",
  "password": "StrongPass123"
}

Response:
{
  "user_id": 1,
  "username": "alice",
  "otp_secret": "JBSWY3DPEHPK3PXP...",
  "otp_uri": "otpauth://totp/COMP3334-IM:alice?secret=...",
  "message": "registration successful"
}
```

**阶段2: 双重认证登录**
```http
# 步骤1: 密码认证
POST /login/password
{
  "username": "alice",
  "password": "StrongPass123"
}

Response:
{
  "challenge_token": "eyJ...",
  "expires_at": "2026-04-01T15:17:00Z"
}

# 步骤2: OTP验证
POST /login/otp
{
  "challenge_token": "eyJ...",
  "otp_code": "123456"
}

Response:
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "expires_at": "2026-04-02T03:17:00Z"
}
```

**阶段3: 密钥管理**
```http
POST /identity-key
Authorization: Bearer <access_token>

{
  "device_id": "cli-device-1",
  "public_key": "base64编码的X25519公钥"
}

Response:
{
  "ok": true,
  "device_id": "cli-device-1",
  "fingerprint": "0123abcd89ef5678..."
}
```

**阶段4: 信任建立**
```http
GET /identity-key/bob
Authorization: Bearer <access_token>

Response:
{
  "username": "bob",
  "device_id": "cli-device-1",
  "public_key": "base64编码的公钥",
  "fingerprint": "89ef56780123abcd...",
  "created_at": "2026-04-01T03:00:00Z"
}
```

#### 5.1.2 消息格式设计

**加密信封格式:**
```json
{
  "v": 2,
  "alg": "x25519-hkdf-sha256-aesgcm",
  "ciphertext": "base64编码的AES-GCM密文",
  "nonce": "base64编码的12字节随机数",
  "salt": "base64编码的16字节HKDF盐值",
  "replay_token": "32位十六进制字符串",
  "sender_device_id": "cli-device-1",
  "ttl_seconds": 3600
}
```

**附加认证数据 (AAD):**
```json
{
  "from_username": "alice",
  "to_username": "bob",
  "message_type": "e2ee_text",
  "sender_device_id": "cli-device-1",
  "replay_token": "abc123def456...",
  "ttl_seconds": 3600
}
```

#### 5.1.3 消息传输协议

**发送消息:**
```http
POST /messages/send
Authorization: Bearer <access_token>

{
  "to_username": "bob",
  "content": "JSON格式的加密信封",
  "message_type": "e2ee_text"
}

Response:
{
  "ok": true,
  "message": "submitted",
  "data": {
    "message_id": 7,
    "conversation_id": 1,
    "from_username": "alice",
    "to_username": "bob",
    "content": "本地明文显示",
    "message_type": "e2ee_text",
    "status": "sent",
    "created_at": "2026-04-01T03:30:00Z"
  }
}
```

### 5.2 密码学原语选择

#### 5.2.1 密钥交换: X25519

**选择理由:**
- **安全性**: 提供128位安全级别，抗量子计算攻击
- **效率**: 计算速度快，适合移动设备和嵌入式系统
- **标准化**: RFC 7748标准，广泛支持和验证
- **实现质量**: `cryptography`库提供安全可靠的实现

**技术参数:**
```python
# 密钥生成
private_key = X25519PrivateKey.generate()
public_key = private_key.public_key()

# 密钥交换
shared_secret = private_key.exchange(peer_public_key)
# 输出: 32字节共享密钥
```

#### 5.2.2 密钥派生: HKDF-SHA256

**选择理由:**
- **安全性**: 基于SHA-256的HMAC，抗碰撞性强
- **灵活性**: 可输出任意长度的密钥材料
- **标准化**: RFC 5869标准，密码学界共识
- **适用性**: 适合从共享密钥派生多个子密钥

**技术实现:**
```python
hkdf = HKDF(
    algorithm=hashes.SHA256(),
    length=32,                    # AES-256密钥长度
    salt=salt,                    # 16字节随机盐
    info=b'comp3334-im-e2ee-v1'   # 应用特定信息
)
content_key = hkdf.derive(shared_secret)
```

#### 5.2.3 对称加密: AES-GCM

**选择理由:**
- **认证加密**: 同时提供机密性和完整性保护
- **性能优势**: 现代CPU提供硬件加速支持
- **标准化**: NIST SP 800-38D标准
- **安全性**: 抗选择密文攻击等高级攻击

**技术实现:**
```python
aesgcm = AESGCM(content_key)
ciphertext = aesgcm.encrypt(
    nonce=nonce,                    # 12字节随机数
    data=plaintext.encode('utf-8'), # 明文数据
    associated_data=aad             # 附加认证数据
)
```

#### 5.2.4 密码学库版本和依赖

**核心依赖:**
```
cryptography>=42.0.0
├── 支持X25519椭圆曲线密钥交换
├── 支持HKDF-SHA256密钥派生
├── 支持AES-GCM认证加密
├── 提供安全的随机数生成
└── 符合FIPS 140-2标准

argon2-cffi>=23.1.0
├── 内存困难的密码哈希函数
├── 抗GPU/ASIC暴力破解
└── OWASP密码哈希推荐算法
```

---

## 6. 安全分析

### 6.1 服务器无法获取明文分析

#### 6.1.1 加密位置和流程

```
客户端加密流程:
明文消息
    ↓ [本地加密]
X25519密钥交换 → HKDF密钥派生 → AES-GCM加密
    ↓
JSON密文信封
    ↓ [HTTPS传输]
服务器 (仅存储密文)
```

**关键安全保证:**
1. **密钥不离开客户端**: 私钥仅存储在 `client/client_state.json`
2. **服务器无解密能力**: 缺少私钥无法进行X25519密钥交换
3. **传输层保护**: TLS防止网络窃听中间人攻击

#### 6.1.2 服务器存储内容分析

**数据库消息表结构:**
```sql
CREATE TABLE messages (
    message_id INTEGER PRIMARY KEY,
    conversation_id INTEGER,
    from_username TEXT,
    to_username TEXT,
    content TEXT,              -- JSON密文信封
    message_type TEXT,         -- 'e2ee_text'
    status TEXT,
    is_offline_queued BOOLEAN,
    is_read BOOLEAN,
    created_at TEXT,
    delivered_at TEXT,
    read_at TEXT
);
```

**服务器视角的数据:**
```json
{
  "from_username": "alice",           // 明文元数据
  "to_username": "bob",               // 明文元数据  
  "content": "eyJ2IjoywiJhbGci...=",  // 密文信封 (无法解密)
  "message_type": "e2ee_text",        // 明文类型标识
  "created_at": "2026-04-01T03:30:00Z", // 明文时间戳
  "status": "delivered",              // 明文状态信息
  "is_read": true                     // 明文已读状态
}
```

#### 6.1.3 解密能力验证

**服务器尝试解密 (失败):**
```python
# 服务器端伪代码 - 无法成功
def server_decrypt_attempt():
    encrypted_content = get_message_from_db()
    envelope = json.loads(encrypted_content)
    
    # 缺少私钥，无法进行密钥交换
    try:
        shared_secret = ???  # 服务器没有alice的私钥
        content_key = hkdf_derive(shared_secret, envelope['salt'])
        plaintext = aesgcm_decrypt(envelope, content_key)
    except Exception as e:
        return "解密失败: 缺少必要的私钥材料"
```

### 6.2 元数据泄露分析

#### 6.2.1 泄露的元数据类型

**用户关系图:**
```
服务器可知的社交关系:
├── 联系人关系
│   ├── Alice ↔ Bob (联系人)
│   ├── Alice ↔ Carol (联系人)
│   └── Bob ↔ Carol (非联系人)
├── 好友请求历史
│   ├── Alice → Bob (已接受)
│   ├── Carol → Alice (已拒绝)
│   └── Bob → Alice (待处理)
└── 黑名单关系
    ├── Alice blocked Dave
    └── Bob blocked Eve
```

**通信模式分析:**
```
可推断的行为模式:
├── 时间模式
│   ├── Alice每天9-18点活跃
│   ├── Bob主要晚间在线
│   └── 周末消息频率增加50%
├── 关系强度
│   ├── Alice-Bob: 每日10+消息
│   ├── Alice-Carol: 每周2-3消息
│   └── 新建联系人: 初始消息频率高
└── 网络拓扑
    ├── 核心用户: 连接数>20
    ├── 边缘用户: 连接数<5
    └── 桥接节点: 连接不同社群
```

**技术元数据:**
```
系统可知信息:
├── 账户信息
│   ├── 注册时间: 2026-03-15
│   ├── 最后登录: 2026-04-01 15:30
│   └── 设备ID: cli-device-1
├── 消息统计
│   ├── 发送消息数: 1,247
│   ├── 接收消息数: 1,198
│   ├── 平均消息长度: 45字符
│   └── 加密消息大小: 280字节平均
└── 网络信息
    ├── IP地址: 192.168.1.100
    ├── 地理位置: 香港
    └── 网络类型: 家庭宽带
```

#### 6.2.2 隐私保护措施

**已实现的保护:**
- **消息内容加密**: 核心通信内容完全保密
- **身份验证**: 公钥指纹防止中间人攻击
- **完整性保护**: AES-GCM防止消息篡改
- **重放防护**: Replay token防止重复攻击

**未保护的元数据:**
- **通信关系**: 谁和谁在通信
- **时间信息**: 通信时间和频率
- **网络拓扑**: 用户社交网络结构
- **行为模式**: 用户活跃规律

#### 6.2.3 隐私影响评估

**低风险影响:**
- 消息内容完全保密
- 无法进行内容审查
- 保护用户言论隐私

**中等风险影响:**
- 可推断社交关系网络
- 可分析用户行为模式
- 可能的流量分析攻击

**高风险影响 (未实现):**
- 缺乏元数据混淆技术
- 无匿名化通信机制
- 无流量填充保护

### 6.3 系统局限性

#### 6.3.1 技术限制

**密钥管理限制:**
```
当前限制:
├── 静态密钥系统
│   ├── 无前向安全 (Forward Secrecy)
│   ├── 无后向安全 (Backward Secrecy)
│   ├── 无密钥轮换机制
│   └── 密钥泄露影响所有历史消息
├── 单设备支持
│   ├── 仅支持 cli-device-1
│   ├── 无多设备同步
│   ├── 无设备管理机制
│   └── 设备丢失导致密钥丢失
└── 信任模型简化
    ├── 仅TOFU信任模式
    ├── 无手动密钥验证流程
    ├── 无信任等级管理
    └── 无密钥变更审计
```

**存储安全限制:**
```
本地存储问题:
├── 明文状态存储
│   ├── client_state.json 未加密
│   ├── 包含私钥、OTP密钥等敏感信息
│   ├── 无密码保护机制
│   └── 恶意软件可直接获取
├── 无安全删除
│   ├── 删除账户后密钥残留
│   ├── 无内存安全清理
│   └── 无磁盘安全擦除
└── 无备份加密
    ├── 状态文件备份未加密
    ├── 云同步存在泄露风险
    └── 无版本控制安全
```

**协议功能限制:**
```
功能缺失:
├── 消息功能
│   ├── 无群组消息支持
│   ├── 无文件传输功能
│   ├── 无消息撤回机制
│   └── 无消息编辑功能
├── 用户体验
│   ├── CLI界面复杂
│   ├── 无图形界面
│   ├── 错误提示不友好
│   └── 无使用向导
└── 系统管理
    ├── 无用户管理界面
    ├── 无系统监控
    ├── 无审计日志
    └── 无备份恢复
```

#### 6.3.2 安全改进建议

**短期改进 :**
1. **本地状态加密**: 使用系统密钥链加密客户端敏感数据，防止本地文件泄露
2. **增强错误处理**: 提供更友好的安全错误提示和用户指导
3. **内存安全**: 实现敏感数据的内存清理和安全释放机制

**中期改进 :**
1. **实现前向安全**: 采用双棘轮算法 (Double Ratchet)，每次消息生成新的临时密钥
2. **多设备支持**: 实现预密钥机制和设备管理，支持多设备同步
3. **群组消息**: 扩展协议支持群组端到端加密

**长期改进 :**
1. **元数据保护**: 实现洋葱路由或混淆技术，隐藏通信关系和时间信息
2. **生产环境部署**: 添加负载均衡、安全监控和容灾备份机制
3. **性能优化**: 优化加密算法实现，提升大规模用户支持能力

---

## 7. 测试评估

### 7.1 功能演示

#### 7.1.1 完整通讯流程测试

**测试环境:**
- 操作系统: Windows 11 / Ubuntu 22.04
- Python版本: 3.11+
- 依赖版本: requirements.txt 指定版本

**测试步骤:**

```bash
# 1. 启动服务器
$ python -m server.run_tls

# 2. 终端A: Alice注册和登录
$ python client/cli.py https://127.0.0.1:8443
> register alice StrongPass123

> login alice StrongPass123

# 3. 终端B: Bob注册和登录  
$ python client/cli.py https://127.0.0.1:8443
> register bob StrongPass123

> login bob StrongPass123
```
![[Pasted image 20260405232758.png]]
Alice 和 Bob注册并登录


```bash
# 4. Alice添加好友
> send-request bob

# 5. Bob接受好友请求
> pending
> respond 1 accept

# 6. Alice发送加密消息
> send bob "Hello Bob! This is a secret message."

# 7. Bob查看消息
> conversations
> open 1
```

成功发送并接收：
![[Pasted image 20260405233109.png]]

二人互相发送信息：
![[Pasted image 20260405235216.png]]

bob离线，alice发给bob消息，bob登录后能看到：
![[Pasted image 20260406001333.png]]

alice拉黑bob，两人无法通信：
![[Pasted image 20260406002237.png]]

alice unblock bob，然后两人添加好友，之后可以互相发送信息：
![[Pasted image 20260406002442.png]]

alice设置了30秒过期的信息，bob在30秒内在历史记录可以查看：
![[Pasted image 20260406002943.png]]

过了时间之后就看不到了：
![[Pasted image 20260406003038.png]]

#### 7.1.2 加密验证测试

**数据库验证:**
- 查看服务器数据库，验证存储的消息内容为密文格式
- 确认消息类型为 `e2ee_text`，content字段为Base64编码的加密信封
- 验证密文包含版本号、算法标识、密文、nonce、salt和replay_token等字段
![[Pasted image 20260405233506.png]]
数据库无法看到明文内容

**客户端解密验证:**
- 使用客户端私钥从服务器获取密文
- 调用解密函数进行解密
- 验证解密后的明文与原始消息一致
- 确认服务器无法直接获取明文内容

### 7.2 安全测试用例

#### 7.2.1 安全测试用例1: 重放攻击防护

**测试目标:** 验证replay token机制有效防护重放攻击

**测试实现:** 基于项目 `tests/test_replay_protection.py` 中的 `ReplayProtectionTests` 类

**测试方法:**
1. **环境设置**: 使用 `TemporaryDirectory` 创建独立的测试数据库
2. **用户初始化**: 通过 `TestClient` 注册Alice和Bob用户并获取访问令牌
3. **E2EE管理器**: 初始化 `ClientE2EEManager` 进行端到端加密操作
4. **好友关系**: 建立Alice和Bob之间的联系人关系

**关键测试用例:**

**测试1: 重复投递检测** (`test_duplicate_delivery_on_reconnect_is_detected`)
- Alice发送消息给Bob
- Bob通过WebSocket首次接收消息
- 模拟重连后收到相同消息
- 验证系统抛出 `DuplicateDeliveryError` 异常

**测试2: 重放密文阻止** (`test_replayed_ciphertext_with_new_server_message_id_is_blocked`)
- Alice发送原始消息
- 攻击者将相同密文插入数据库（模拟重放攻击）
- 尝试解密重放消息
- 验证系统抛出 `ReplayAttackError` 异常

*详细测试代码请参考: `tests/test_replay_protection.py` 第106-185行*
测试结果：三项测试全部通过
![[Pasted image 20260405234152.png]]

**测试结果验证:**
- `DuplicateDeliveryError` 异常正确抛出
- `ReplayAttackError` 异常正确抛出
- 原始消息正常解密，重放消息被阻止
- 系统具备完整的重放攻击防护能力

**安全意义:**
- 防止攻击者截获消息后重复发送
- 保护通信完整性和新鲜性
- 防止消息计数和状态混淆
- 验证了replay token机制的有效性

#### 7.2.2 安全测试用例2: TLS传输安全测试

**测试目标:** 验证TLS/SSL加密传输的安全性

**测试实现:** 基于项目 `tests/test_tls_transport.py` 中的TLS传输测试

**测试方法:**
1. **TLS服务器**: 使用 `_TLSUvicornServer` 启动独立的TLS测试服务器
2. **证书生成**: 通过 `ensure_dev_tls_materials()` 生成开发用TLS证书
3. **端口管理**: 使用 `_find_free_port()` 动态分配可用端口
4. **客户端连接**: 使用 `httpx` 和 `WebSocketListener` 进行安全连接测试

**关键测试组件:**

**TLS服务器管理**:
- 使用uvicorn配置SSL证书和密钥
- 在独立线程中运行TLS服务器
- 支持HTTPS和WSS连接

*详细TLS服务器实现请参考: `tests/test_tls_transport.py` 第31-50行*

**测试流程:**
1. **证书准备**: 生成自签名CA证书和服务器证书
2. **服务器启动**: 在随机端口启动TLS服务器
3. **HTTPS连接**: 客户端验证服务器证书并建立HTTPS连接
4. **WSS连接**: 建立安全的WebSocket连接
5. **数据传输**: 验证所有通信都通过TLS加密

**安全验证点:**
- **证书验证**: 客户端正确验证服务器证书链
- **加密传输**: 所有HTTP/WebSocket通信都通过TLS 1.2+加密
- **端口隔离**: 测试使用独立端口避免冲突
- **连接安全**: 防止中间人攻击和窃听

**测试结果:**
- TLS服务器成功启动并监听指定端口
- HTTPS客户端连接建立成功，证书验证通过
- WebSocket over TLS (WSS) 连接正常工作
- 所有网络流量都经过加密保护

两项测试全部通过：
![[Pasted image 20260405234256.png]]

**安全意义:**
- 验证了TLS传输层的正确实现
- 确保客户端-服务器通信的机密性和完整性
- 防止网络层面的中间人攻击
- 为端到端加密提供安全的传输基础

---

## 8. 结论

### 8.1 项目成果总结

本项目成功实现了一个名为 **Obsidian** 的端到端加密即时通讯系统，达到了所有预设目标：

**技术成果:**
- **完整的端到端加密实现**: 基于 X25519 + HKDF-SHA256 + AES-GCM 的现代密码学方案
- **服务器无法获取明文**: 通过客户端加密确保消息内容对服务器完全保密
- **安全的身份验证**: 密码 + TOTP 双重认证机制
- **实时通讯能力**: WebSocket 支持的实时消息推送
- **完善的社交功能**: 好友管理、联系人系统、黑名单功能

**安全成果:**
- **防重放攻击**: Replay token 机制有效防护重放攻击
- **防中间人攻击**: TOFU 信任模型检测密钥篡改
- **传输安全**: TLS 加密保护网络传输
- **完整性保护**: AES-GCM 认证加密防止消息篡改

**学术价值:**
- 提供了完整的端到端加密系统实现参考
- 验证了现代密码学协议的实际应用
- 为网络安全教育提供了实践案例
- 详细的安全分析和测试方法

### 8.2 技术贡献

**创新点:**
1. **学术透明实现**: 完整开源的端到端加密系统，适合学术研究和教学
2. **简化而不简陋**: 在保证安全的前提下简化设计，便于理解和学习
3. **完整测试验证**: 提供了详细的安全测试用例和验证方法
4. **威胁模型分析**: 系统性的安全威胁分析和防护设计

**实用价值:**
1. **可部署原型**: 可直接部署运行的完整系统
2. **教育工具**: 适合网络安全课程的实践教学
3. **研究基础**: 为进一步研究提供基础平台
4. **标准遵循**: 遵循 RFC 标准和最佳实践


### 8.3 项目意义

本项目的成功实现证明了：

1. **技术可行性**: 端到端加密技术在学术项目中的完全可实现性
2. **安全保证**: 通过正确的设计可以实现服务器无法获取明文的安全目标
3. **教育价值**: 完整的实现为网络安全教育提供了宝贵的实践资源


**Obsidian** 项目不仅是一个技术实现，更是对现代数字隐私保护的实践探索，展示了如何在保证可用性的同时实现强大的安全保护。
