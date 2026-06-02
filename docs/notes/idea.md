# Akasha 算法详解（边聊边记）

> 记录约定：🎯 = 原始设计意图（花月）｜⚙️ = 代码实际机制（已核对源码）｜🔍 = 观察 / 评价 / 存疑
> 每块聊拢了才落笔；🎯 留空的等花月补。

---

## Q1：项目空库时，第一个 query 进来会发生什么？记录成什么格式？

### ⚙️ 机制（已核对 engine.py / store.py / core.py）

整个过程分两个阶段，中间隔着一次 LLM 回答：

**阶段 A — query 进来（同步检索）** `query()` engine.py:231 → `_retrieve` :496
1. `_graph_snapshot()` 取图，空库 → `nodes={}`、`edges={}`
2. dense / graph_seed / activation / ripple **全为空**（core.py:1234 `if not nodes: return [],[],trace(0,0)`）
3. `_format_context_block([],[])` → `text_block = ""`：**第一个 query 注入给 LLM 的记忆是空的（冷启动，零召回）**
4. 但仍写**一条 query_log**（engine.py:290，条件：intent ∈ {context, answer} 且有 session_key）——所以"第一个被记录的东西"是一条**全空检索日志**

**阶段 B — turn 结束后（异步）** `TurnCommitted` 事件 → `_on_turn_committed` :591
1. `_load_committed_turn_messages` 拿到 user（+assistant）消息
2. `embed_batch` 嵌入
3. 逐条：
   - `upsert_cached_embedding` → 写 **message 级 embedding**（后续 dense 检索用的就是它，store.py:96 表）
   - `upsert_message_node` → 写 **turn 级节点**（store.py:394）：
     - turn key = `{session_key}:{turn_seq}`；**user(seq=N) 与 assistant(seq=N+1) 合并进同一节点**（turn_seq=N，core.py:378 `turn_key`）
     - **首条消息 salience = 0**（`causal_salience` 在 prior_count=0 时返回 0——没有"过去"就无所谓"新颖"）
     - strength = `initial_strength(0)` = **2.1**（= cap 3.0 × (0.70 + 0.30·σ)，σ=0）
     - resource=1.0、recall_count=0、last_*_ts = first_ts_unix、emb_count 1→2（assistant 再 upsert 同 key 时均值合并 embedding、salience 取 max、anchor 保持 user）
     - `advance_salience_state`：全局重心累加（写 akasha_salience_state 'global'，供后续算新颖度）
4. pending activation：第一个 query 的 activation_items 为空 → `_remember_pending_activation` 提前返回 → **不建边、不写 activation_events**

### 第一轮结束后 DB 内容
| 表 | 行数 | 内容 |
|---|---:|---|
| akasha_query_log | 1 | 全空检索（seed_count=0 / activated_count=0 / inject_chars=0 / items 为 `[]`） |
| akasha_embedding_cache | 1–2 | user / assistant 的 message embedding |
| akasha_nodes | 1 | 这一轮 turn，salience=0、strength=2.1、resource=1.0、emb_count=2 |
| akasha_salience_state | 1 | 'global' 重心累加 + count |
| akasha_edges | **0** | 还没有结构 |
| akasha_activation_events | **0** | 没激活到任何旧节点 |

### key / id 格式
- **turn key**：`{session_key}:{turn_seq}`，例 `telegram:7674283004:7315`
- **query_id**：`{session_key}:{seq}:{intent}:{sha1("{intent}\n{query}")[:10]}`，例 `telegram:7674283004:7315:context:5ed3c3037e`（同一轮的预检索与显式 recall 各留一条日志）

### 🔍 观察 / 存疑
- **冷启动第一 query 必然零召回**；系统第一步只"长出一个孤立节点"，**边要到第 2 个 query 才开始出现**（需要有旧节点被激活、才能与当前 turn 共激活连边）。
- **novelty 是相对量**：第一个节点 salience=0、strength=2.1（base 档）。库越大、重心越稳，后来的新颖度判断才有意义。
- **学习是异步、滞后一轮的**：检索用的永远是"上一轮 commit 时"的图；当前 turn 的边和状态更新发生在回答之后。
- 存疑：salience=0 的首节点 strength 仍有 2.1（偏高），早期少量节点会以较高基线进入图——是否影响早期召回结构，待后面聊"状态动力学"时回看。

### 🎯 原始意图（待花月补充）
-

---

## Q2：算法全貌 + 一个能体现"方方面面"的实验场景

### ⚙️ 算法全貌（按数据流五层，已核对源码）

**① 编码层（节点怎么生）**
- turn 节点 = user+assistant 合并（`core.py:378 turn_key`），embedding 按 `emb_count` 加权均值
- `salience = (1−cos(emb, 全局重心))×2`：新颖度，相对量；首节点=0
- `strength₀ = 3.0×(0.70+0.30·salience)`：编码即峰值，越新颖起步越高
- resource=1.0、recall_count=0

**② 结构层（边怎么长）** `core.py:282 activation_edge_updates`
- 本轮召回 items 与当前 turn：因果 1.0（item→now）、反因果 0.35（now→item）
- items 两两：共激活边 = √(score_i·score_j)
- 落库 `weight = bounded_add(旧·衰减, 0.12·strength, 2.0)`；边 14 天衰减

**③ 检索层（五步）**
1. 种子 `seed_pool`：Dense(cos>0.675) ∪ FTS(jieba+IDF≥3.5 的 BM25 top10, FTS-only 限5) ∪ BlackHole(salience>0.8 且 cos>0.60 top5)；Dense 空→Dense(FB) top10；Dense∩FTS 能量 ×1.3
2. 微图 = 种子 + (距种子 ≤30min 且 cos>0.28 的邻居)
3. RWR：`转移 = cos × state × (1+36·Hebbian边)`，每列 top12，2 迭代，α=0.2；`state = exp(1.4·salience+1.0·long)·resource/√(1+fan)`
4. 打分：`content_base = noisyOR(ripple=current·3·state, direct=0.5·cos)` `× (1+0.8σ)(1+0.6long)(1+0.5edge) × resource × hop × user / (1+fan)^0.1`，阈值 0.22
5. Bridge(2hop 桥节点提升)/soft-recall；另有独立 `graph_expand` 一跳通道 `edge_signal=w/√(out·in)`（电导归一，真抑 hub）

**④ 注入层** `_format_context_block`：两块都按时间排——`左脑:精确回忆`(dense top10) + `右脑:潜意识第一反应`(ripple-only，去掉 dense 已有)，6000 字预算

**⑤ 学习闭环 + 时间动力学**：检索→命中节点 strength 增/resource 耗/recall+1；strength 7d、resource 30min 恢复、edge 14d 衰减；检索滞后一轮（用上一轮 commit 的图）

### ⚙️ 实验场景设计（手指就医主簇 + 跨域钩子）

**语料 T1–T9（user+assistant，从空库按时间喂）**
| # | user | 目的 |
|---|---|---|
| T1 | 我喜欢咬手指 把指甲咬出倒刺了 有点肿这几天咋整 | 冷启动首节点 salience=0 |
| T2 | 昨晚涂了鱼石脂 用创口贴包住了 | 低新颖度；埋稀有词"鱼石脂"(高IDF→FTS) |
| T3 | 肿得更厉害还热热的 去医院切开引流 塞了根引流条 | 情节升级 |
| T4 | 打麻药的时候为什么也很疼 | "麻药"，与"绷带"embedding 不近（留给 ripple 演涌现） |
| T5 | 医生说周日去换药 | |
| T6 | 手指被绷带裹着伸不直 晚上睡觉很别扭 | "绷带"首现 |
| T7 | 我好失败 感觉啥都做不好 好自卑 | 跨域、高 salience→BlackHole 候选 |
| T8 | akashic 晚安 | 通用句，反复共激活→养 hub |
| T9 | 我手老不自觉地抖 是不是和咬手指焦虑有关 | 桥：连"手指(健康)"与"焦虑/失败(情绪)" |

**探针 P1–P6（接着按时间喂，各点亮特定机制）**
| 探针 | 机制 / 要看的 var |
|---|---|
| P1 鱼石脂怎么涂啊 | 稀有词 FTS-BM25、Dense∩FTS ×1.3、seed_pool 三路 |
| P2 那还要搞绷带吗 | **核心涌现**：dense 对"绷带"弱，ripple 经边拉回麻药/引流条；看 transition/current/1hop/ripple-only |
| P3 那还要搞绷带吗（紧接重发） | resource 短期抑制：刚召回节点排名下移 |
| P4 我是不是有点焦虑 | Bridge 2hop：P→T9(手抖)→T7(失败)，bridge 提升/soft_recall/hop 惩罚 |
| P5 我现在状态怎么样 | hub 污染：无锚→T8(晚安)等高 fan 主导；看 fan 惩罚为何压不住 |
| P6 那还要搞绷带吗（隔 10 天） | 时间衰减：strength(7d)/edge(14d) 衰减后同 query 变化 |

每个探针都会打印：种子能量 e0 → 转移矩阵 → current(ripple) → 各 gain → 最终 score → 入选/抑制 → 建边 → 状态更新，全用真实数字。

### ⚙️ 工程：预嵌入库（避免反复调 embedding）
- 用 `/mnt/data/coding/akasic-agent/config.toml` 的 `[memory.embedding]`（dashscope text-embedding-v4）一次性嵌入全部语料+探针，存进 `akasha/experiments/fixture.db`，实验时只读不再调 API。

### 🎯 原始意图（待花月补充）
-

---

## Q3：真实 trace 跑出来的结果（harness 直接调 core.py，fixture 预嵌入）

工具：`experiments/{scenario.py, build_fixture.py, run_trace.py, fixture.db}`；用 `.venv/bin/python` 跑（要 jieba）。

### ⚙️ 被干净验证的机制
- **冷启动**：首节点 strength0=2.1（salience_user=0）；第 2 个 turn 起才有边。
- **方向性 STDP**：因果边(item→now) ≈ 0.21–0.45，反因果边(now→item) ≈ 0.07–0.16，比值≈0.35，与 `STDP_ACAUSAL_EDGE_GAIN` 一致。
- **BlackHole 种子**：T3 检索时 T1(salience>0.8 且 cos>0.6) 以 BlackHole/1hop 进入。
- **Dense∩FTS**：T3、P1 命中"鱼石脂"出现 `Dense+FTS` 源（×1.3 boost）。
- **resource 短期抑制**：P3 距 P2 仅 1 分钟，被 P2 召回的 hub resource 0.67→0.45，ripple score 明显下降（T13 4.68→3.38）。
- **hub 自我放大**：T10 fan 随探针 28→30→32→34→36，越被共激活越大。

### 🔍 核心发现（诚实，且部分超出设计预期）
**P2「那还要搞绷带吗」完整 ripple 排名：**
| # | 节点 | src | cos | fan | score |
|---:|---|---|---:|---:|---:|
| 1 | T13 你都有什么功能 | Graph | .37 | 26 | 4.68 |
| 2 | T10 akashic在吗 | Graph | .39 | 30 | 4.42 |
| 3 | T11 你好呀 | Graph | .32 | 30 | 4.10 |
| 4 | T7 我好失败 | Graph | .43 | 22 | 1.87 |
| 5 | T14 陪我聊会天 | Graph | .36 | 22 | 1.62 |
| 6 | **T4 打麻药** | Dense(FB) | .49 | 24 | 1.37 |
| 8 | T3 引流条 | Dense(FB) | .58 | 28 | 1.20 |

1. **右脑 ripple 块成了"hub 放大器"，不是"涌现引擎"**：top5 全是问候 hub + 失败，与"绷带"无关；cos 仅 0.3，却靠 `edge`(=1.1–1.5，被 cross_boost×36 放大) + 高 fan 拿到 4+ 分。
2. **预期的涌现没发生**：本应靠边浮现的"麻药/引流条"排到第 6、第 8，而且它们本就在 **dense（左脑）top10 里** → 图扩散在这没给出 dense 之外的独特价值，需要的东西其实是左脑给的。
3. **学习也被 hub 主导**：建边用的 activation_items top5 也是 hub → 边继续往 hub 长，正反馈（见 fan 自我放大）。
4. **每个探针 ripple top 都被同一批 hub 占据**（P1鱼石脂、P4焦虑、P5状态都一样）→ 右脑块对 query 几乎"不应答"，只反映全局连接度。

### 🔍 必须说明的 caveat（否则会高估严重性）
- **15 节点图过小、近全连接**（166 边/15 点）→ 问候 hub 与任何 query 都 1 跳可达，所以 hub 普遍性被**放大**。真实 3000 节点稀疏图里簇更分离，锚定 query 的 on-topic 簇能赢（对应真实库的 good case）。所以本实验干净地展示了**机制与失败模式**，但**严重程度被小图夸大**。
- **P6 衰减演示不干净**：隔 10 天后 resource 完全恢复(+) 压过 strength/edge 衰减(−)，hub 分数反而更高；strength 衰减是否如预期生效待再核（可能 hub 的 last_strength_ts 未按预期推进）。

### 🔧 Q3 结论修正（用真实脱敏数据复跑后）
合成短句版的"右脑=跨域 hub 放大器、涌现没发生"是**场景假象**：短句 cos 几乎从不 >0.675 → 种子全塌成 Dense(FB) 全局 top10（39% vs 真实 13%）→ 簇分不开。
用 `experiments/run_real.py`（从 sessions.db 抽字节/游戏/健康 3 个连续窗口、脱敏、96 turn、真实长文本）复跑后：
- **PH「那还要搞绷带吗」：右脑 ripple top10 = 9/10 健康（手肿/鱼石脂/发紫/揭开）+ 2 条 Bridge → 涌现成立、没漂走。**
- **PG「L玩什么职业」/ PX「我现在状态」：右脑被工作簇 mega-hub（`这个jd是啥` fan164）入侵 → 跨域漂移。**
- **真相：簇强弱决定成败**——query 落在强自连簇→右脑 on-topic 且加 Bridge（=真实库 good case）；落在弱簇/无锚→全局最大 hub 通吃（=真实库 bad case）。正好复现真实库 good/bad 分裂。
- harness 现已对齐真实 regime（`run_real.py` + `real_emb_cache.db` 缓存嵌入）。hub 抑制 A/B 应在这版上做。

### 🎯 原始意图（待花月补充）
-
