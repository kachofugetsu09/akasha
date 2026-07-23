# Akasha：Salience 消融与模式补全实验留档

日期：2026-07-23 至 2026-07-24

时区：Asia/Shanghai

最终选择：保留完全不依赖 salience 的实现，暂不合入任何 Temporal / Burst / Community 实验。

## 1. 最终结论

本轮正式保留的基线是 `61f2d65 refactor(akasha): remove salience-driven retrieval`：

- 不再把 BlackHole 节点补入 seed 池。
- 不再计算 causal salience，也不保存它的运行状态。
- RWR 初始状态不再乘 `exp(1.4 × salience)`。
- 最终排序不再乘 `1 + 0.8 × salience`。
- 新节点的初始 strength 不再由 salience 分档。
- dashboard、snapshot 和 dump 不再用 salience 改变节点含义或大小。
- `akasha_nodes.salience` 与对象字段暂时只作为 schema 兼容字段存在，所有节点恒为
  `1.0`；它不再影响 seed、扩散、排序、长期强度或展示。

最终召回链路是：

```text
当前 query
    │
    ├── Dense embedding
    └── FTS
          │
          ▼
      有限 seed pool
          │
          ▼
  mutual KNN / 历史共激活图上的 RWR
          │
          ▼
    MI 收敛与 hub 惩罚
          │
          ├── Activation：用于本轮图更新
          └── Ripple：去掉 Dense 重复后注入
```

当前实现不声称已经解决所有模式补全问题。它只是一个更干净、可解释、没有隐藏显著度
先验的新基线。睡眠工具规则、人物关系和短句续接等能力应该以后用明确的事件/关系模型
补回，不应再借助 salience 黑箱放大。

## 2. 复现实验的共同契约

### 2.1 冻结输入

本轮所有正式 A/B 重建使用同一份只读输入：

| 输入 | SHA-256 |
|---|---|
| `sessions.db` | `3e064ac37c8ffc10bba619659f6edf3ec57aa95bd0c03e1680104e6e9c70b0a3` |
| 重建前 live `akasha.db` | `8718aab13baa6c5795c0b0abe3d544d00833a99a392fd6754b29780b692dc72f` |

本机只读输入备份在仓库外的
`/mnt/data/coding/.akasha-readonly-backups/salience-study-20260723/`。仓库不提交数据库。

共同条件：

- embedding 模型名：`text-embedding-v4`。
- 重放顺序：按消息时间、session key、seq 升序进行 causal replay。
- 只在 query 当时可见的节点和边上计算，不读取未来节点。
- 用户消息保留完整内容；助手回复预览最多保留前 50 个字符。
- Dense、Ripple、Activation 分开记录；不能把内部 Activation 当成实际返回的 Ripple。
- 每个输出数据库都执行 `PRAGMA integrity_check`。
- A/B 之间保持 `sessions.db`、embedding cache、query 顺序和非目标参数不变。

### 2.2 固定 Query 集

| seq | Query |
|---:|---|
| 3011 | 轻舟已过万重山 |
| 5294 | 实习生的脑科学 / RAG 系统 |
| 7877 | 最近就医记录，头孢还是其他危险情况 |
| 8464 | 我昨晚睡得咋样 |
| 8566 | 发烧为什么喝温热水，不是冰水更好吗 |
| 9224 | 我昨晚睡得怎么样 |
| 9624 | 和 zcliu 参加的比赛是什么 |
| 9710 | 比赛没获奖，但 +2 给第二名评价，算好消息吗 |
| 9892 | 插件系统重构后怎么工作 |
| 10306 | 少年少女真好听 |

短句连续事件实验另外固定使用：

| seq | Query |
|---:|---|
| 10308 | 其实应该是 op，听的时候有一种恍惚感 |
| 10310 | 我忘记 ED 是什么了 |
| 10312 | 我咋没印象了，你上网搜搜 |
| 10314 | 笑死了，我就说我去听了一下怎么没印象 |
| 10321 | 模型架构本身好没意思，不太有兴趣（负对照） |

### 2.3 统一评价方式

每条 query 都需要同时阅读：

1. query 当时的真实前文；
2. Dense 命中的用户原文；
3. Ripple 命中的用户原文与助手前 50 字；
4. Activation 中影响建边但没有注入的节点；
5. source、direct、路径、score 和时间；
6. 召回内容是否能改变当前回答，而不只是语义相似。

核心质量指标不是固定 `Recall@k`，而是：

- 当前回答所需事实或操作规则是否被补齐；
- 正确 episode 的质量是否集中；
- 第一个错误 attractor 在哪里出现；
- Ripple 是否提供 Dense 之外的有效增量；
- 当前 prompt 已有内容是否被重复返回；
- 算法停止是数值收敛，还是人为截断。

## 3. 前置演化：形成此次实验的旧基线

这些尝试早于 salience 消融，但决定了本轮所用图结构，保留 commit 即可复现。

### 3.1 自适应激活基线

- 提交：`44e1795 akasha: 自适应右脑激活基线`
- 方向：让召回预算随 query 的 Dense 形状变化，而不是所有 query 固定同一数量。
- 结论：为短句和长句提供了不同计算预算，但不能解释“为什么某个旧 episode 应被补全”。

### 3.2 动态召回预算

- 提交：`6a50657 feat(akasha): 动态调节召回激活预算`
- 方向：由 Dense 的集中程度决定 activation 计算范围。
- 结论：适合控制计算量，不适合作为模式存在与否的证据。

### 3.3 K=3 mutual KNN 模式补全

- 提交：`6f7705d feat(akasha): graph_expand 改为 K=3 mutual k-NN BFS`
- 方向：每个节点只保留互惠 top-3 邻接，让相似节点自然形成局部簇，再从 seed 扩张。
- 结果：图中确实出现可解释的小 community；Sonny Boy、睡眠规则、工作比赛等主题能形成
  局部结构。
- 问题：KNN community 是传播拓扑，不等于独立 seed。错误 Dense 没进入正确 community 时，
  簇不会凭空被点亮。

### 3.4 Ripple 与 Activation 统一、MI 收敛

- 提交：`0a2fdc2 feat(akasha): ripple=activation 统一筛选 + MI 收敛 + hub 惩罚`
- 方向：不再让线上和 replay 分别跑两套 soft recall；使用同一 Activation，再做 Dense 去重。
- 结论：线上/重放语义更一致，但 seed 中的 BlackHole 与扩散/排序中的 salience 仍会重写
  整张历史图。

### 3.5 Noisy-OR 离线评价

在 3,728 个有效 turn 上，将 Akasha 与纯 message-KNN 对未来消息的额外覆盖做 Noisy-OR
聚合：

- 主口径平均差 `A - B' = -0.007`，均值没有优势。
- `q95=+0.130`、`q99=+0.256`，Akasha 的价值集中在少量右尾。
- 右尾主要是睡眠 snapshot 元规则、B23 下载规则、同 session 的密集讨论簇。
- 短空洞句会因 base cosine 过低制造假阳性。

这个结果改变了评价目标：Akasha 不应追求“平均多召回”，而应在少数需要历史模式补全的
query 上提供不可替代的增量。

## 4. 实验一：完整复现旧线上算法

### 4.1 变量

旧算法同时包含四条 salience 路径：

1. `salience > 0.8` 且 `direct > 0.60` 时，最多补 5 个 BlackHole seed；
2. RWR 状态近似为

   `state ∝ exp(1.4 × salience + long_score) × resource / sqrt(fan)`；
3. 最终候选分数乘 `1 + 0.8 × salience`；
4. 写入时由 salience 决定 initial strength，继续影响 long score。

### 4.2 重建结果

| 指标 | 旧线上算法 |
|---|---:|
| nodes | 4,750 |
| edges | 635,376 |
| query logs | 4,723 |
| Dense items | 41,862 |
| Ripple items | 46,833 |
| Activation events | 68,731 |
| BlackHole events | 5,983 |
| 文件大小 | 445.3 MiB |
| integrity check | ok |

输出库 SHA-256：
`f5a884b0524d0d1af4e00a17c32bba4bc20969c0326a1d3315bafd892d5890ec`。

### 4.3 观察

- 睡眠 query 能找回“必须读实时 snapshot”的操作规则。
- 工作比赛能找回部分人物/组织关系。
- Sonny Boy、RAG 和比赛结果中出现高显著度旁支。
- BlackHole 不是简单的额外 5 条结果；它改变 Activation，随后改变边、fan、strength 和
  后续所有 replay 状态。

旧线上版是功能较全的对照，但 salience 的因果解释不清晰。

## 5. 实验二：只删除 BlackHole seed

### 5.1 唯一变量

删除 BlackHole seed 路径，其余三条 salience 路径保持不变。Dense 输入、embedding、
replay 顺序和配置完全相同。

### 5.2 全量结果

| 指标 | 旧线上 | 去 BlackHole | 变化 |
|---|---:|---:|---:|
| nodes | 4,750 | 4,750 | 0 |
| edges | 635,376 | 671,394 | +36,018 |
| Ripple items | 46,833 | 49,052 | +2,219 |
| Activation events | 68,731 | 69,908 | +1,177 |
| BlackHole events | 5,983 | 0 | -5,983 |

输出库 SHA-256：
`b30b660f5bb20539acfd97551c0835ee48eafe15ad44e0be2c4803b6a19e146b`。

Dense 的 4,723 条结果全部不变，但：

- 4,614 / 4,723 条 query 的 Ripple 集合变化；
- Ripple Jaccard 均值 / 中位数为 `0.376 / 0.333`；
- 4,650 / 4,723 条 query 的 Activation 集合变化；
- 旧图 327,510 条边消失，新图增加 363,528 条边。

### 5.3 Query 结论

- 变好：插件系统重构、比赛结果、实习生 RAG。
- 变差：就医时间线、两条睡眠 query、比赛身份。
- 混合：Sonny Boy、发烧饮水。

结论：拒绝。只拆 BlackHole 会保留其他 salience 吸引子，却让历史图重新洗牌，既不干净，
质量也最不稳定。

## 6. 实验三：所有 salience 恒为 1

### 6.1 唯一变量组

这是一次完整机制消融，不是仅在读取处把数值改成 1：

- 删除 BlackHole；
- 删除全局 embedding 重心与 causal salience；
- 删除 salience state；
- `initial_strength()` 不再接受 salience；
- RWR 从 `exp(1.4 × salience + long)` 变为 `exp(long)`；
- 终排删除 salience gain；
- schema 兼容字段在创建、读取和导出时恒为 `1.0`。

### 6.2 全量结果

| 指标 | 旧线上 | 去 BlackHole | salience=1 |
|---|---:|---:|---:|
| nodes | 4,750 | 4,750 | 4,750 |
| edges | 635,376 | 671,394 | 454,232 |
| Dense items | 41,862 | 41,862 | 41,862 |
| Ripple items | 46,833 | 49,052 | 36,270 |
| Activation events | 68,731 | 69,908 | 56,466 |
| 文件大小 | 445.3 MiB | 459.6 MiB | 364.8 MiB |
| salience distinct | 3,866 | 3,866 | 1 |
| integrity check | ok | ok | ok |

输出库 SHA-256：
`15fe326774fc7b244e35fd1123f4d391e4a6837d32972a544be089a6bcc6f7c2`。

相对旧线上：

- 边减少 28.5%；
- Ripple 减少 22.6%；
- Activation 减少 17.8%；
- 数据库减少 18.1%；
- Dense 完全不变；
- 99.6% 的 query Activation 集合改变，证明这是图动力学重写。

### 6.3 重点 Query

| Query | 最重要观察 |
|---|---|
| 就医记录 | 组成了头孢、换药、脓肿、荨麻疹和气道危险信号的完整链，优于其余两版。 |
| Sonny Boy | Ripple 从 10 收缩到 4，集中到同一作品和歌曲 episode。 |
| 发烧饮水 | 反而从 12 膨胀到 22，说明“去 salience”不自动等于“更少”。 |
| 两条睡眠 query | 只剩语义相似旧问句，丢失“实时 snapshot”操作规则。 |
| 插件重构 | 可用，但只去 BlackHole 版的局部路径更好。 |
| 比赛是啥 | 旧报告曾把智能贷后/催收比赛链误判成噪声；用户补充工作背景后，这部分应判为正确。真正噪声是电竞比赛、Hela Mem 论文和通勤支线。 |
| 比赛结果 | 能同时补回比赛背景和 LD / +1 / +2 关系，优于旧版的电竞吸引子。 |
| 实习生 RAG | 脑科学、图检索、向量化和 star 仓库形成一致主题。 |

### 6.4 为什么最后选择它

最初的九条人工审阅曾给出“旧线上 4 胜、salience=1 4 胜、去 BlackHole 1 胜”，并因睡眠
工具路由的错误成本较高而暂判旧线上第一。继续审阅真实上下文后，最终选择改为
salience=1，原因是：

1. 智能贷后比赛是用户真实工作上下文，不应当作为时间/工作簇噪声；
2. 睡眠 snapshot 是明确操作规则，应由可解释的规则/工具路由召回，而不是依赖 salience；
3. salience=1 在医疗、窄主题音乐、RAG 和比赛结果上更聚焦；
4. 其失败是“缺少新信号”，可以继续建模；旧版失败是隐藏显著度直接改写图，难以解释；
5. 它提供最干净的后续实验基线，避免 Temporal 实验与旧 salience 相互混淆。

## 7. 实验四：Temporal PPR 与 95% activation mass

### 7.1 方向

把时间相邻节点建成传播边，并把时间 cue 直接放入 seed；PPR 计算后，把累计
activation mass 达到 95% 的节点作为返回候选。

### 7.2 全量结果

| 指标 | Temporal PPR |
|---|---:|
| nodes | 4,750 |
| edges | 2,832,166 |
| query logs | 4,723 |
| Activation events | 146,492 |
| integrity check | ok |

典型 Ripple 数量：

- `3011 轻舟已过万重山`：39；
- `9624 比赛是啥`：25；
- `9710 比赛结果`：25；
- `9892 插件重构`：17；
- `8566 发烧饮水`：23；
- `7877 就医记录`：3；
- `5294 实习生 RAG`：1。

### 7.3 结论

拒绝。95% 是“数值质量覆盖”而不是“内容质量保留”：

- 分布平坦时必须返回很多节点才能凑满 95%；
- 分布尖锐时只返回很少节点；
- 它不能判断剩余节点是否对当前回答有增量；
- 时间近邻已经在 prompt 中时，会产生大量重复；
- 边数和 Activation 均显著膨胀，比赛和“轻舟”出现明显长尾。

PPR residual 可以作为计算停止误差，但不能直接当 Ripple 集合的选择规则。

## 8. 实验五：只加时间边，与 Context Relay 对照

### 8.1 假设

时间首先应成为拓扑和图可塑性信号。当前 prompt 的近邻内容不应重复注入，但短句需要一个
连续入口，把 RWR 带回正在进行的事件。

令当前 query 与上一 turn 的同事件后验为：

\[
c_t = \sigma\left(
\operatorname{logit}P(\text{short burst}\mid \Delta t)
+\log\frac{f_{\text{same}}(\operatorname{cos})}
{f_{\text{different}}(\operatorname{cos})}
\right)
\]

时间是先验，embedding 相容性是似然。两者不是固定线性加分。

Context relay source：

\[
e_0=(1-c_t)q_{\text{semantic}}+c_t\delta_{\text{previous}}
\]

### 8.2 静态对照

在 no-salience 图上比较：

1. 只有 mutual-KNN 语义图；
2. 加软时间边但没有时间 seed；
3. 同一张图，加连续 context relay seed。

Sonny Boy 旧 episode 进入非 Dense Top-10 的数量：

| seq | `P(common)` | 旧 Temporal Ripple | 只加时间边 | Context relay |
|---:|---:|---:|---:|---:|
| 10306 | 0.000004 | 1 | 4 | 4 |
| 10308 | 0.946260 | 0 | 0 | 6 |
| 10310 | 0.757159 | 0 | 0 | 5 |
| 10312 | 0.920232 | 0 | 0 | 4 |
| 10314 | 0.971111 | 0 | 0 | 5 |

### 8.3 结论

方向成立：

- 时间边能改善已经进入正确 episode 的传播；
- 错误 Dense 根本没有进入该局部图时，只有时间边不会自行启动；
- context relay 能救“我忘记 ED 是什么了”“你上网搜搜”这类低信息续句；
- relay 节点应参与 Activation 和建边，但通常不应作为 Ripple 返回。

这仍只是静态图证据，不足以替换生产 replay。

## 9. 实验六：重建互惠 KNN + 时间边

### 9.1 图与停止条件

- 6,918 条 mutual-KNN 语义边；
- 9,452 条相邻用户 turn 时间边；
- PPR local push 以 `L1 residual ≤ 1e-4` 停止；
- 严格排除未来节点；
- Ripple 由被选语义吸引盆决定，不使用固定 top-k 或 95% mass。

### 9.2 Sonny Boy 结果

| seq | `P(common)` | Active | basin | Ripple |
|---:|---:|---:|---:|---:|
| 10306 | 0.000004 | 161 | 5 | 2 |
| 10308 | 0.946260 | 590 | 6 | 4 |
| 10310 | 0.757159 | 1,995 | 7 | 6 |
| 10312 | 0.920232 | 1,370 | 7 | 7 |
| 10314 | 0.971111 | 291 | 9 | 8 |

### 9.3 结论

旧 Sonny Boy episode 被稳定点亮，数量由局部拓扑变化而不是固定截断。但 10310–10314
仍会把当前 prompt 中更早的 user turn 当成 Ripple。只排除“上一轮”不够，runtime 必须
传入整个 prompt 的 node keys，做结构性去重。

## 10. 实验七：后验 Run Length 与有限 MAP seed

### 10.1 时间分布

4,783 个正相邻用户消息间隔呈明显 burst：

| 分位数 | 间隔 |
|---|---:|
| P10 | 34.6 秒 |
| P25 | 55.1 秒 |
| P50 | 119.3 秒 |
| P75 | 894.3 秒 |
| P90 | 10,593.9 秒 |
| P95 | 28,921.5 秒 |

在 `log(1 + gap)` 空间拟合短 burst / 长间隔两个 log-normal 分量，不手写“五分钟内算
上下文”。

### 10.2 Run-length 后验

相邻两轮同事件概率为 `c_i`：

\[
P(R=0)=1-c_1
\]

\[
P(R=r)=\left(\prod_{i=1}^{r}c_i\right)(1-c_{r+1})
\]

第一次静态实现对所有 `R` 做 Bayesian model averaging。审阅后收紧语义不变量：

- 只有有限 MAP run 的真实 prompt 成员作为 context seed；
- Query、ContextSeed 和 DirectSeed 全部可激活、可建边，但绝不回传为 Ripple；
- 不再把概率很小的长 tail 当作“软可见上下文”。

### 10.3 Sonny Boy 结果

| seq | `P(same)` | MAP R | Active | Ripple |
|---:|---:|---:|---:|---:|
| 10306 | 0.000004 | 0 | 190 | 2 |
| 10308 | 0.946260 | 1 | 590 | 4 |
| 10310 | 0.757159 | 2 | 1,995 | 5 |
| 10312 | 0.920232 | 3 | 1,370 | 5 |
| 10314 | 0.971111 | 4 | 291 | 5 |

动态上下文长度自然形成 `0 → 1 → 2 → 3 → 4`，没有固定 N。Ripple 均来自 prompt 外的旧
Sonny Boy episode。

### 10.4 负对照

`10321` 与上一事件间隔约三小时：

- `P(same)=1.96e-11`；
- MAP run length 为 0；
- 时间上下文没有污染新话题。

但“必须选一个最大语义盆”仍返回 5 条泛化节点。问题不在时间 seed，而在输出模型缺少
`H0：没有模式可补全，Ripple=空`。这是该实验没有进入生产的关键原因。

## 11. 实验八：有限 MAP 完整 causal replay

### 11.1 集成内容

把有限 MAP context seed、seed 不回传、prompt 去重和吸引盆选择接入完整 replay；线上与
重放走同一入口。所有 4,723 个 query 按时间重建。

### 11.2 重建结果

| 指标 | 有限 MAP 完整重建 |
|---|---:|
| nodes | 4,723 |
| edges | 622,894 |
| query logs | 4,723 |
| Activation events | 66,222 |
| build wall time | 387.69 秒 |
| max RSS | 1,262,256 KiB |
| embedding cache hit / miss | 9,446 / 0 |
| integrity check | ok |

输出库 SHA-256：
`1f81045695325f4cd5c03d7f6e33b932d2ed0c3444bf53690dd926a63fc561e9`。

全量诊断确认：

- seed 与 Ripple 交集为 0；
- Dense 与 Ripple 交集为 0；
- 用户内容完整，助手预览不超过 50 字；
- query 通常只扫描 2–8 条相邻边，工程上可做增量更新。

### 11.3 十条 Query 的数量

计数为 `Dense / Ripple / Activation`：

| seq | 数量 | MAP context |
|---:|---:|---:|
| 3011 | 10 / 3 / 5 | 4 |
| 5294 | 10 / 7 / 12 | 2 |
| 7877 | 9 / 6 / 13 | 7 |
| 8464 | 4 / 10 / 23 | 0 |
| 8566 | 10 / 12 / 17 | 0 |
| 9224 | 4 / 12 / 24 | 1 |
| 9624 | 10 / 13 / 16 | 1 |
| 9710 | 10 / 20 / 28 | 0 |
| 9892 | 7 / 2 / 11 | 0 |
| 10306 | 10 / 4 / 10 | 0 |

### 11.4 结论

不采用：

- 短句续接和智能贷后比赛 case 有真实改善；
- 比赛工作节点本身是正确上下文，不能误判为噪声；
- 但插件重构和初始 Sonny Boy query 不稳定；
- `9710` 的比赛多义性仍会让电竞 attractor 与工作比赛竞争；
- 没有模式时仍可能被迫选一个 basin；
- 边数、内存和 replay 复杂度均高于 no-salience 基线。

因此它是有价值的方向验证，不是当前最佳成品。

## 12. 实验九：reciprocal embedding community 过滤

最后尝试把“返回哪个盆”从历史 Hebbian top-3 改为更干净的 reciprocal embedding-KNN
community：

- context seed 不回传的语义不变量保持不变；
- 时间只负责选择当前事件入口；
- reciprocal community 只负责输出收敛范围；
- 目标是避免旧共激活边把电竞比赛、通勤、Hela Mem 等错误 attractor 混入。

该尝试只完成工程原型，尚未完成 benchmark 和完整 rebuild，因而没有可报告的质量结果。
它不进入最终代码。要复现该方向，应从 no-salience 基线重新实现，并以本文固定 query、
完整 causal replay、`H0` 空模式和 prompt 结构去重为验收条件，不能沿用未验证原型。

## 13. 方案对比与最终排序

| 方案 | 解释性 | 质量判断 | 工程状态 | 最终决定 |
|---|---|---|---|---|
| 旧线上 salience | 低 | 操作规则强，但有显著度吸引子 | 已运行 | 仅作对照 |
| 只去 BlackHole | 中 | 图大幅重连，重点 case 最不稳定 | 已重建 | 淘汰 |
| salience=1 | 高 | 整体最克制，失败边界清楚 | 已重建、已提交 | **保留** |
| Temporal PPR + 95% | 中 | 数量失控，内容明显退化 | 已重建 | 淘汰 |
| 只加时间边 | 高 | 无入口时不能救短句 | 静态实验 | 结论保留 |
| Context relay | 高 | 能救续句，但重复 prompt | 历史图实验 | 方向保留 |
| 后验 run length | 高 | 动态上下文长度成立 | 静态实验 | 方向保留 |
| 有限 MAP 全 replay | 中高 | 有好 case，但总体未胜 | 已完整重建 | 不合入 |
| reciprocal community | 目标较高 | 未完成评价 | 原型 | 不合入 |

如果交给不了解实现的人盲审，最可能的选择仍是：

1. salience=1：窄主题、医疗时间线、RAG 和比赛结果更集中；
2. 旧线上：睡眠工具路由等少数 case 很强；
3. 有限 MAP：部分上下文很聪明，但波动和数量仍大；
4. 只去 BlackHole：既没有完全去掉 salience，也没有稳定质量。

## 14. 后续研究约束

未来若继续做模式补全，应从当前 no-salience 基线开始，并保持这些约束：

1. 时间既可形成边，也可作为连续后验控制的 event relay；不是固定 N，也不是布尔 gate。
2. 当前 prompt 成员只能作为内部 source / Activation / 学习依据，不能原样回传。
3. Dense、FTS、context、community 都必须有明确 provenance。
4. PPR residual 只负责计算收敛；Ripple 数量由模式证据决定。
5. 必须显式比较 `H0：无模式` 与候选 episode，允许自然返回 0。
6. 多个 episode 必须竞争，不能把所有局部簇并集后继续发散。
7. 睡眠 snapshot 等操作规则应有明确关系或工具路由，不重新引入 salience。
8. 任何新方案先做冻结静态图，再做完整 causal replay；不能只在最终图上反推质量。

参考方向：

- Event Segmentation Theory：当前事件与长期记忆边界；
- Temporal Context Model / Context Maintenance and Retrieval：context 作为检索 cue；
- Bayesian Online Changepoint Detection：run-length 后验；
- Bayesian causal inference：时间和语义 cue 的共同来源推断；
- Kleinberg burst model：密集时间片的潜在状态；
- Personalized PageRank local push：有误差界的局部扩散；
- conductance sweep：从 PPR 向量找局部 community；
- query clarity：判断 Dense 结果分布是否清晰；
- latent-cause inference：继续、恢复或新建事件；
- noisy-OR / competing risks：多路径证据融合与 attractor 竞争。

## 15. 清理与恢复边界

最终仓库只保留：

- no-salience 正式实现；
- 本文档；
- 此前明确要求的助手预览最多 50 字行为；
- 与本轮无关的用户文件、同步备份和 `bench` 工作树。

本轮生成的数据库、逐 query 长表、实验脚本和临时代码不提交，并从工作区移入系统回收站。

仍可恢复的边界：

- no-salience 实现：Git 提交 `61f2d65`；
- pattern-completion 静态实验：分支
  `experiment/pattern-completion-seeds` 的提交 `845ca51`；
- 未验收 Temporal 集成：具名 Git stash
  `backup: unfinished temporal pattern integration before clean salience main`；
- 冻结输入数据库：仓库外只读备份目录；
- 所有实验变量、公式、输入哈希、query 集和结论：本文。
