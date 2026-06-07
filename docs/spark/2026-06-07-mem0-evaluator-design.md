# mem0 对比评估器设计(检索层·复用 run_bench ★标尺)

日期:2026-06-07
状态:设计已批准,待实现

## 1. 目标与范围

给现有 benchmark 加一条 **mem0 lane**,让 akasha 的 dense / ripple 和 mem0 在**同一个 case + 同一片海 + 同一把检索层★标尺**下并排对比,回答:"那些 akasha 靠共激活边救回的低 cos 情景(尤其 D 类情感绑定),mem0 提炼成 fact 后还召得回吗?"

**范围内**
- 复用我们 `bench/cases/*` 的 case(带 `sub_clusters`/`relevant_sub_clusters` 标注)。
- mem0 的 ingest/search 步骤**模仿其官方 benchmark repo**(`mem0ai/memory-benchmarks`)的调用姿势,保证 mem0 用法不被质疑。
- 只测**检索层**:复用 `run_bench.py` 的 `score_probe`(情景簇命中 + dense@2k vs ripple@k 的 ★情景增量),给 mem0 加一列 rank。
- embedder 两边统一 bge-m3。

**范围外(YAGNI)**
- 不做 mem0 框架的 **LLM-judge / 回复层 QA 评测**(用户明确只测检索层)。
- 不接他们的 Next.js 结果可视化前端、不跑 LoCoMo/LongMemEval/BEAM 公开数据集。
- 不在本期接 zep(但 lane 适配器模式要为之留口)。

## 2. 架构与数据流

```
                  同一个 case.json + 同一片海(sea_anon1000)
                                  │
              ┌───────────────────┴───────────────────┐
              ▼                                         ▼
     【akasha lane】(已有 run_bench)            【mem0 lane】(新 mem0_lane.py)
     bge-m3 嵌入 → 因果重放                     bge-m3 embedder(同款) → mem0 ingest
     → dense / ripple 召回                       每对 add + metadata 标 sub_cluster + timestamp
              │                                  → search(query, top_k=20)
              │                                  → 溯源 fact → 源 turn → sub_cluster
              └───────────────────┬───────────────────┘
                                  ▼
                   同一把 ★标尺 (复用 score_probe)
        dense / ripple / mem0 三列 rank + 情景簇覆盖@20 + ★情景增量
```

三条 lane 同源同尺;mem0 的评判从"LLM-judge"换成我们的 sub_cluster 命中。

## 3. mem0 lane 机制(`bench/run/mem0_lane.py`)

### 3.1 Ingest(每对一次入库,对齐官方姿势)
- 遍历 case+海的 turn 流,**每个 user+assistant 对调一次 `add`**(对齐官方 ingest 与用户要求)。
- `add(messages=[{role,content}...], user_id=<本次run固定id>, timestamp=<turn 的 day→unix>, metadata={"turn_id":..., "sub_cluster":..., "origin":"case|sea"})`。
  - **timestamp 喂 case 的 day**:mem0 OSS 支持,保证 mem0 也拿到时间信息(公平,不让 akasha 独享时序)。
  - **metadata 标 sub_cluster/turn_id**:这是命中溯源的基础(见 3.3)。
- 调用参数(messages 结构、metadata、timestamp、user_id、retry)严格照搬 `benchmarks/common/mem0_client.py` 的姿势。

### 3.2 Search(top20)
- 对每个 probe:`search(query=probe_text, user_id=<同上>, top_k=20)`。
- 取返回的 memory 列表(每条=一条提炼 fact + 它的 metadata + score),保序为 mem0 的 rank。

### 3.3 命中判定(fact 溯源)
- 每条召回 fact 的 metadata 里带着它来源那一对 turn 的 `sub_cluster`。
- top20 fact → 收集去重后的 `sub_cluster` 集合 = "mem0@20 覆盖了哪些情景簇"。
- 喂给 `score_probe` 的判定:某 gold sub_cluster 若出现在该集合 → mem0 命中;否则 miss。
- **这是关键设计点**:若 mem0 提炼时把"那次饭局"丢了(没生成对应 fact),其 turn 的 metadata 永远不会被任何 fact 携带回来 → mem0 结构性 miss。这正是要测的"提炼丢信息的代价",非 bug。
- 注:一条 fact 可能融合多对 turn(mem0 会合并),metadata 取该 fact 实际 add 时所属的那一对;mem0 UPDATE 合并产生的 fact 以最后写入的 metadata 为准。该口径在 spec 落地时以 mem0 返回结构为准微调。

### 3.4 海复用(省 token 核心)
- **海 add 一次,persist 后所有 case 复用**:mem0 OSS 用 qdrant 持久化,海 ingest 完落盘成 `mem0_sea/` 快照。
- **每个 case:clone 海快照副本** → add 该 case 的 turn → search probes → 丢弃副本。
  - 用 clone 副本而非"测完删 case memory":因 case 的 add 可能 UPDATE 掉海的 fact,删不干净;copy 才能完美回滚到纯海。
- 海一次性成本付一遍,之后每 case 仅增量 ~40 条。

## 4. 公平对齐口径(写进 README,防质疑)

| 维度 | akasha | mem0 | 对齐 |
|---|---|---|---|
| embedder | bge-m3 | bge-m3(同款) | ✅ 比架构非 embedding |
| 检索预算 | dense@20 / ripple@20 | search top_k=20 | ✅ 取20公平 |
| 时间信息 | day→因果重放 | day→timestamp | ✅ 都拿到时序 |
| 入库单位 | 每 turn 一 node | 每对一次 add | 官方姿势 |
| 命中判定 | sub_cluster(turn) | sub_cluster(fact 溯源) | 同一 gold |

**固有差异(如实说明,不强行抹平)**:akasha 检索单位是 turn-node,mem0 是提炼 fact;mem0 的 20 条 fact 可能来自 <20 个 turn。我们比的是"各自 top20 检索结果覆盖了哪些 gold 情景簇",不强行对齐到"20 个 turn"。

## 5. 输出形态
- 在 run_bench 现有逐 case 输出的子簇表里**加一列 `mem0` rank** 和 `mem0@20 覆盖`,与 dense/ripple 并排。
- 汇总:每 case 的 `dense@20 / ripple@20 / mem0@20` 情景簇覆盖率 + ★(ripple 独家、mem0 是否也够不到)。
- 负控 probe 同样跑三列。

## 6. 配置与成本
- **LLM**(mem0 提炼用):NVIDIA `deepseek-ai/deepseek-v4-flash`,base_url `https://integrate.api.nvidia.com/v1`,**关 thinking**(提取 fact 不需推理,省时省 token),OpenAI 兼容。
  - 实测:20 并发无 429(没探到上限),但延迟抖(avg 16–21s,尾部 60–120s)→ 开 **20–30 并发**摊平。
- **embedder**:远端本地 bge-m3(`/home/huashen/models/bge-m3`,HF_HUB_OFFLINE),0 token。
- **vector store**:qdrant 本地持久化(海快照 `mem0_sea/`)。
- **token 估算**:海 1000 轮 × (extract+update) ≈ 300 万 in + 30 万 out;海**只付一次**(~$0.6 gpt-4o-mini 量级 / NVIDIA 免费端点 0 元,仅耗时);每 case 增量 ~6 万 token。**结论:成本可忽略,瓶颈是海 ingest 那一次的时间(~30–60 min)。**
- 部署:优先 mem0 Python SDK 直连本地 qdrant(轻);如需最忠实可起官方 docker OSS server,add/search 参数姿势一致。

## 7. 实现要点(供后续 plan 阶段)
- 新文件 `bench/run/mem0_lane.py`:`ingest_sea()`(一次,persist)、`clone_sea()`、`ingest_case()`、`search_probe(top_k=20)`、`fact_to_subclusters()`。
- `run_bench.py`:`--with-mem0` 开关;开则加载 mem0 lane,把 mem0 召回的 sub_cluster 集合并入 `score_probe` 的判定与打印。不开则零影响现有行为。
- mem0 调用封装单独成一个薄 client,姿势对照官方 `mem0_client.py`(messages/metadata/timestamp/top_k/retry)。
- 远端跑(mem0+qdrant+bge-m3+NVIDIA LLM 都在远端),沿用现有 rsync 同步。

## 8. 开放风险
- mem0 OSS 是否稳定支持 metadata 透传到 search 返回(溯源依赖此)——实现前需用最小 demo 验证一次。
- NVIDIA 端点延迟抖,海 ingest 可能拖到 1 小时;若太慢可切本地 maas deepseek。
- mem0 UPDATE 合并 fact 时 metadata 归属的精确口径,落地时按返回结构微调(见 3.3 注)。

## 9. 成功标准
- 能对任意一个我们的 case,一条命令输出 dense/ripple/**mem0** 三列在 top20 下的情景簇覆盖与 ★。
- 在 D1(情感绑定)上跑出预期对照:akasha ripple 救回 g_dinner,**mem0@20 是否召回**——若 miss,即"提炼丢绑定"的硬证据;若命中,则诚实记录 mem0 也能做。
- 海 ingest 一次、多 case 复用,单 case 增量秒级。
