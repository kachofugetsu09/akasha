# Akasha Benchmark 合成规格（全英文 · 海+case 组合检索）

**日期**：2026-06-05
**状态**：设计已确认，进入实现
**前序**：`2026-06-04-longmemeval-sea-real-timing-design.md`（海的构造）

## 0. 关键转向（相对前序）

- **全英文**：海(LongMemEval)不译；case 新造英文；规避中英跨语言 cos confound，且省掉 120 万 token 翻译。
- **海不是探针**：海 = 纯背景图噪音，提供真实规模 + 真实时序的稀疏长尾（小图验不出系统能力）。LongMemEval 的 12 个 question 不再当 probe。
- **评测靶 = 我们自有的 case**。
- **系统无关**：语料是带时间戳的消息流，probe 配 qrels。任何记忆系统（Akasha/mem0/Zep/MemGPT…）都能 ingest + 对 probe 返回 ranked 召回，用同一把尺子打分。

## 1. 这个系统在证什么

Dense = 纯 embedding 余弦 top-k，盲区是"语义不像但实际相关"的记忆。
Ripple = 共激活图扩散（从 dense 种子沿养粗的边扩散 + 时间衰减/salience/fan），能把对 query 低 cos、dense 够不到、但经边连到种子的节点整段重建。

> **存在"对 query 语义不像、纯检索必漏"的相关记忆；好系统应靠结构/关联/时序捞回。Ripple 能、纯 dense 不能——增量量出来。**

## 2. 三件套

- **海**：固定背景。LongMemEval 连续切片(temporal-reasoning idx 233–244) + 真实库脱敏时序，已就绪 = `bench/sea/sea_en.json`（2976 节点 / 576 session / 跨48天 / sea_end=2025-02-18T11:01）。
- **case**：一个个文件，逐个追加到海末尾（见 §3）。
- **组合**：海固定共享，运行时种子化拼 `海+case_i`，各跑一条检索，case 间零污染（见 §5）。

## 3. case 文件格式（`bench/cases/<case_id>.json`，系统无关）

```jsonc
{
  "case_id": "en01_<topic>", "lang": "en", "description": "...",
  "episode": [
    { "local_id":0, "role":"user", "text":"...",
      "member_role":"anchor|killer|control|filler" }, ...
  ],
  "probes": [
    { "probe_id":"en01_main", "query":"...", "kind":"main",
      "gold_local_ids":[...], "killer_local_ids":[...] },
    { "probe_id":"en01_neg", "query":"...", "kind":"anchorless" }
  ],
  "timing": { "span_hint_days":7, "killer_placement":"mid|late" }
}
```

- **member_role**：`anchor`(对 probe 高 cos、dense 够得到，锚+对照) / `killer`(低 cos、dense 必漏，判别点) / `control`(高 cos 对照基线) / `filler`(簇内填充)。
- **probe.kind**：`main`(正测) / `anchorless`(负控，无真锚，应低误召回)。

## 4. 时间锚定（case 落海后，簇状真实）

- 起点 = `sea_end + 采样静默`；簇内时间戳由 `bench/build/temporal_model.json`（真实段间静默 lognormal + 段内连发经验百分位）生成 → 真实 bursty，非规整。
- **硬约束**：`killer_placement` 默认 `mid`/`late`——killer 不孤立埋早期，否则 strength 衰光、边来不及养，对**任何**靠时序衰减的系统都不可解、benchmark 不公平。
- 末尾追加 probe turn（发问）。全程时间戳单调。

## 5. 组装管线（`海+case → 检索`）

海固定共享、不复制；`compose(sea, case_i)` 种子化(seed=42)确定性输出：
```
corpus(messages-schema 行: session_key/seq/role/content/ts)
queries(probe → query_text, ts)
qrels(probe → { node_key: 相关度 }，killer=2 / 相关=1 / 其余=0)
```
node_key = `case:<case_id>:<seq>` 真实落地键。
```
compose → bge-m3 嵌入(远端，海嵌入缓存复用) → 系统 ingest+retrieve(统一预算 k=10) → 对 qrels 打分
```

Akasha 路径：物化 source sqlite + 嵌入 → `AkashaReplayRuntime`(+`replay_fast` 加速，数字等价) 按 ts 因果逐 turn 重放 → probe turn 抓 dense / ripple 两路召回。

## 6. 工厂验收（killer 合格判据，embedder 客观）

bge-m3 嵌入全簇 + probe，case 入库前自动筛：
- **killer 合格** ⟺ 完整组合语料里**纯 dense rank > k**（dense recall@k=0，够不到）；
- **anchor/control 合格** ⟺ 纯 dense rank ≤ k（够得到）；
- **可救回性** ⟺ killer 与某 anchor 簇内同段/相邻共现（关联路径存在，否则对谁都不可解）；
- 不满足 → 打回重造。判据全基于数据 + 参照 embedder，对所有被测系统公平。

## 7. 指标（统一 k，跨系统可比）

| 指标 | 含义 |
|---|---|
| **★ Killer-Recall@k** | 低 cos killer 进 top-k 没 —— 判别主指标 |
| **Δ over dense** | `Killer-Recall(系统) − Killer-Recall(纯dense)` = 比纯 dense 多带来多少 |
| Recall@k / nDCG@k | qrels 全相关集总质量 |
| Anchor-Recall@k | 高 cos anchor 召回（应≈满，验证没把易的做坏） |
| False-recall@anchorless | 负控误召回（越低越好） |
| (Akasha 内诊) | 每 killer 报 dense_full_rank vs ripple_rank vs act_rank |

默认：参照 embedder = bge-m3；k=10；seed=42。

## 8. 仓库落点

```
bench/
  sea/sea_en.json            海（已就绪）
  cases/en01_*.json          英文 case（新造）
  build/build_sea.py         海构造（已就绪）
  build/temporal_model.json  真实脱敏时序（已就绪）
  build/compose.py           compose(sea,case)→corpus+queries+qrels
  build/factory.py           case 工厂化验收（bge-m3 筛 killer/anchor/可救回）
  run/embed_remote.py        远端 bge-m3 嵌入（海缓存）
  run/run_bench.py           replay_fast 因果重放 + 打分 → 指标
```
旧中文 `cases/case01_cat_gastroenteritis.json`、`noise/*`（中文 regime 产物）已弃用，删除。

## 9. v1 范围（YAGNI）

- v1 = 管线跑通 + 造 1 个英文 case + `海+case` 出首个 Killer-Recall@10 / Δ / dense_full_rank vs ripple_rank + anchor/anchorless。
- 跨系统 adapter（mem0/Zep…）= 未来；corpus/qrels 格式已为其预留。
- 不做：多 embedder、多语言、LLM 端到端 QA。
