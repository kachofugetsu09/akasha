# 噪音库（noise library）

为 Akasha benchmark 准备的**可复用脱敏噪音集**。从真实库分析出主要噪音来源后，按类型**手写**生成（非 copy、非程序模板），用作造 benchmark 时的 distractor / 去噪测试。

## 噪音的定义（来自真实库实证）

噪音节点的机制签名：**高 fan + 低 strength + 高 recall** —— 频繁被扫到、却从不真正重要。
真实库中 `corr(strength, fan) = -0.34`，印证这批节点是无锚 query 漂移时被虹吸的吸能 hub。

## 8 类（按危害排序）

| 文件 | 类型 | 真实库 fan 量级 | 危害 |
|---|---|---|---|
| `filler.json` | 对话填充/追问 | 346–392 | 万能衔接句，最大背景噪音池 |
| `meta_about_ai.json` | 聊AI本身/调试 | 418–602 | 跨一切话题，最大单点 hub |
| `link.json` | 链接/媒体转发 | 282–330 | 内容在站外，松散连接 hub |
| `affect.json` | 情绪寒暄 | 358–492 | salience 高+共现频繁→自激簇（正文局限#3）|
| `status_query.json` | 天气/体征/状态查询 | 336–416 | 无叙事锚，test 漂移首选目标 |
| `greeting.json` | 寒暄/打招呼 | 282–384 | 经典低价值 hub |
| `courtesy.json` | 客套/应答 | — | 纯连接词，粘连全图 |
| `test_anchorless.json` | 测试/零语义锚 | 142–226 | 零锚，hub-drift 最典型触发源 |

每类 60 对，合计 480 对。

## 格式

```json
{
  "noise_type": "...",
  "label": "...",
  "why_noise": "为什么它在真实库里成噪音",
  "real_evidence": ["真实 fan/strength 佐证"],
  "desensitized": true,
  "pairs": [ {"user": "...", "assistant": "..."}, ... ]
}
```

- **只有文字**，user/assistant 成对。**无时间戳、无向量**——向量在 build benchmark 时统一现 embed（模型相关，不入库）。
- 时间戳由 benchmark 生成器按目标时间分布注入。

## 脱敏

全部内容为**手写合成**：去除真实昵称、产品名、账号 ID、个人事实（健康/求职/生日/技术栈等）。assistant 语气参照真实库（暖、带颜文字、长短不一），但不含任何可定位到真实个人的信息。可安全纳入版本库。

## 用法

造 benchmark 时，从各类按需抽取若干对作为 distractor：
- **锚定 query 测试**：注入这些噪音后，它们**不应**冒进 ripple top → 冒了 = 反 hub 防线漏；
- **无锚 query 测试**：`test_anchorless` / `status_query` 类**会**霸榜 → 验证意图门控触发。
