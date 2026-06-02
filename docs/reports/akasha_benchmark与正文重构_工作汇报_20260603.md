# Akasha 工作汇报：正文重构 + benchmark/case-factory 设施

> 日期：2026-06-03 ｜ 范围：算法核心再认识、正文重构、可批量评测设施、真实数据验证

## 一、这次想解决的问题

1. 把 Akasha 算法**真正吃透**，并诚实评估它相对"非本范式（普通向量库）"到底强在哪、强多少。
2. 给它建一套**可批量、可复用、忠实于线上**的评测设施（benchmark / case factory）。
3. 据此**重构正文**的中心论述。

## 二、核心再认识（结论先行）

- **正文原中心"核心是一行 noisy-OR"放错了位置。** noisy-OR 只是两个标量的融合，平庸，是机制不是灵魂。
- **真正的内核是一条原理：重要性是"租来的"——靠持续被需要来续租，遗忘是交不起租金时的到期。** 由一个量（召回时的 `score`）同时驱动"读"（注入）和"写"（加固）；每个增长都配一个衰减反作用力，于是"好的复利"与"坏的自净化"是**同一条原理的两个方向**，自组织/自净化/自复利全是涌现，没人单独写。这是一个寻找平衡态的**活的动力系统**，不是被查询的数据库。
- **它最被低估的一层：内容级闭环 + 共同演化。** 召回 → 塑造 LLM 回答 → 塑造新记忆内容 → 塑造未来召回。普通向量库是只读快照；Akasha 在长 session 里和用户**共同演化**，"背景慢慢被它完全掌握"。
- **客观价值边界**：作为通用检索它不是处处天壤之别（真涌现约 0.15%，dense 兜底大头）；但有一个**不可替代的内核**——把"语义不像、却被你个人共现历史绑在一起"的记忆从 dense 任意深处召回（鱼石脂：cos 0.52、dense 排 1199、ripple #1）。**它的家是"超长 session + 个人陪伴 + 助手"**：长历史必须结构化召回、无法预判重要性故召回时涌现、关联越攒越准、闭环越用越懂你、坏召回自净化使长跑稳定。
- **"宁滥勿缺"是对的**（LLM 是前额叶）：四重锚定让它安全——dense 地板保准确、有界+衰减自清错误、反 hub 压虚假复现、LLM 定夺。门控应按**质量**而非按意图硬关右脑。

## 三、做了什么

### A. 正文重构（`docs/正文.md`）
- 中心从 noisy-OR 换成"租金原理 / 自稳定动力系统 / 共同演化"；noisy-OR 降为 Part 4 结算机制。
- 六章标题重挂新中心；Part 5 升格为"内容级闭环 + 共同演化 + 自净化免疫系统 + 宁滥为何安全"；Part 6 重定位为"它的家在哪"。
- 完整保留所有支流（公式、真实例子、五道反 hub、三条衰减、STDP、诚实局限），每个概念的是什么/为什么/怎么做揉进行文。
- 自审修正：Step 编号断档已重排；自净化数字 provenance 改诚实（用真实库 `pruning_decay` 0.61→0.041/38 天，而非实验数）。

### B. 评测设施（`data/bench/`，复用真实 `plugins/akasha/replay.py`）
- **忠实**：在 sys.modules 桩掉框架依赖后，直接驱动真实 `AkashaReplayRuntime`（因果、滞后一轮、salience 因果重心、probe 只读冻结、标签仅评测用零泄漏）。
- **快**：`MemoryStore`（内存增量图，替代每轮 sqlite 全表重载）+ `fast_dense`（dense 向量化+缓存矩阵）+ `graph_fast`（in_strength 用 e^{-(t-t0)/τ}·A[d] 因式分解增量、has_user_turn 记忆化）。**~3000 turn 从 678s → 64.6s（~10.5×），且线性扩展**；parity 对拍与未优化版**逐项 0 差异**。
- bge-m3 在带 GPU 的远端 in-process 加载（本地权重 `/home/huashen/models/bge-m3` + `HF_HUB_OFFLINE=1`），向量 build 时现嵌带 cache。

### C. 真实数据验证
- **真实手指 episode 切片（bge-m3 重嵌，2914 turn）**：probe「引流条出血」ripple precision@10=**1.0**、denoise=0；鱼石脂 dense 够不到 → ripple 召回。**价值在大稀疏真实内容里复现，bge-m3 没问题。**
- **注入合成 case**：薄版猫 episode（17 轮）失败（漂到真实健康闲聊）；**加厚版（33 轮 + killer 绑定 callback）成功**——precision 0.8、bg 仅漏 2、深层项「领养」dense#79 /「怕生」dense#114 被 ripple 拉回（dense@10 永远给不到）。
- **limboo case 失败**（教训）：只取单会话把游戏簇切碎 + 锚词脱敏成废字符（limboo→L 废了 FTS）。
- **自净化实测**：相关边反复加固（co=26 → 有效权 1.6），无关巧合边（co=1、闲置 14 天 → ~0.005），坏边自己枯死。
- **dense-impossible 诊断**：线上配置 dense_top_k=10 固定，"不在 dense top10"即真·漏掉；按全库 dense 排名区分"擦肩(11-30)"与"深度联想(>50)"。

## 四、Case Factory 配方（已验证）

注入合成 episode 要稳定涌现，需满足：① 够厚（~30+ 轮）+ 强 callback 自引用（养粗 killer↔probe 边）；② 话题与海半正交（否则被海的同类内容污染）；③ 合理 SNR（信号占窗口约 1/3）；④ killer 真低 cos + 深排。**不是每个都成 → grader 过产 + 自动筛是刚需。** 别切碎簇、别把稀有锚词脱敏成废字符。

## 五、文件清单

**入库（无 PII，可复用）**
- `docs/正文.md`（重构）
- `data/noise/*.json`（8 类脱敏合成噪音库，各 60 对）+ `README.md`
- `data/cases/case01_cat_gastroenteritis.json`（猫肠胃炎情景重建，加厚版）
- `data/bench/*.py`（scaffold：run_bench2 / run_bench_real / mem_store / fast_dense / graph_fast / extract_real_slice / inject_case）+ `README.md`
- 本汇报

**不入库（→ `private/bench/`，gitignore）**
- `real_slice.json` / `limboo_slice.json` / `combined_slice.json`（派生自真实对话，脱敏后仍属个人内容）
- embedding 缓存 / 中间库（只存在于远端 `~/akasha_bench/`）

**已删**：`data/bench/run_bench.py`（早期 Sim 版死代码，被 replay 版取代）

## 六、下一步

1. **基建**：`MemoryStore.clone()`（海建一次 + 每 case fork 秒级）；graph_expand/edges_by_src/fan 的增量已就绪。
2. **Factory**：episode 生成器（按上述配方，模板族 + LLM 改写）→ injector → grader（按"killer dense 深排 + ripple 召回 + 相关项 denseFullRank>10 计数 + 去噪/不串簇"自动判废）。
3. **造海**：LLM 合成多领域大海（脱敏天然），噪音按真实 fan 分布"复现调度"撒入，海验收器对标真实库统计指纹。
4. **意图门控**：事实/任务类 query 给 ripple 降权（非硬关）——token 效率优化，正确性已由 dense 地板兜底。

## 七、诚实的待解（长跑前沿，均为工程可解）

- **hub 累积**：跑越久泛化句 fan 越涨，drift 风险随时间上升（衰减 + 反 hub 压制，需长跑验证）。
- **规模/延迟**：节点到 10 万级时 dense O(N)/graph_expand O(E) 变重（增量优化已铺路，后续或需剪枝/分片）。
- **雪球方向**：闭环放大一切，坏召回会复利——dense 地板 + 质量门控是方向盘，长跑要持续守住。
- 真涌现频率（0.15%）能否靠意图门控/质量提升做到有意义占比，仍待验证。
