# Akasha 长程记忆 Benchmark：LongMemEval 海 + 真实时序 + 自有 case

**日期**：2026-06-04
**状态**：设计已确认，进入 Phase 1
**目标**：可公开发布、可成论文的 benchmark，证明 ripple 相对 dense 的增量价值（概念救回）。

---

## 1. 动机

用真实库直接做 benchmark 无法脱敏、不可公开。核心切法是**把"内容"和"时间结构"解耦**：

- **内容** 用公开 benchmark（LongMemEval）→ 天生可分享、零脱敏。
- **时间结构** 只取真实库的**脱敏时序分布**（gap/昼夜/跨度，时间戳本身不涉密）→ 复刻让 ripple 发光的真实 regime。
- **锋芒** 在时间轴末尾追加我们自有的双 killer case → 扫优势区间。

方法学命中此前实测发现：主力 `graph_expand` 时间无关，但**拉长真实跨度会翻转低 cos killer 的命运**（strength τ 衰减），而这正是证明 ripple 价值的那个点。规整合成窗口给不出，真实时序给得出。

## 2. 关键决策（已确认）

| 项 | 决定 |
|---|---|
| 终极用途 | 可公开发布 / 论文 |
| 海内容源 | **LongMemEval**（ICLR 2025，haystack+gold evidence 范式天然对口）。PersonaMem 留作跨域 ablation（future，不进 v1） |
| 语言 | **译成中文**：海机翻、gold evidence 精翻+人核；复用已有中文 bge-m3 cos 标定；自有 case 不动。规避中英跨语言 cos 隔离的致命 confound |
| 切片方式 | **取连续切片**，不按 question 类型挑（避免选择偏差） |
| 产物形态 | **单个成品海 JSON**（`bench/sea/sea_zh.json`）；但生成脚本+种子+时序参数一并 commit，使构造可复现 |
| 节点粒度 | 一条 message/turn = 一个节点 |

## 3. 管线（7 段）

```
①抓取    LongMemEval → 取连续切片凑 ~3000 turn haystack + 其 gold evidence
②结构化  拍平成中性 JSON：{turn_id, session_id, role, text_en, text_zh, is_gold, evidence_for_q, ts}
③翻译    codex 填 text_zh（海机翻 / gold evidence 精翻人核）；text_en 永久保留作 provenance
④重定时  从真实库拟合脱敏时序模型 → 参数化 → 重采样时间戳，替换 LongMemEval 规整时间
⑤追加    时间轴末尾注入自有双 killer 中文 case（bench/cases/*）
⑥嵌入    远端 bge-m3（本地权重 + HF_HUB_OFFLINE=1）重嵌全部 turn
⑦重放+评测  replay_fast 因果重放 dense vs ripple → 指标 + 逐 killer rank 对照
```

## 4. 重定时模型（方法学 novelty）

数据源：`~/.akashic/workspace/sessions.db`（15 session / 8728 message，带 `ts`/`seq`/`role`）。

拟合并**只导出脱敏参数**：
- gap 分布（对数正态 + 重尾，长静默 p99 量级 ~10h）
- 昼夜活跃曲线（按小时直方）
- 总跨度（量级 ~80 天）
- 簇内连发节奏（中位 ~110s）

重采样：给每 session 排起始时间（尊重昼夜 + gap），session 内保连发节奏，替换 LongMemEval 规整时间戳。
**gold evidence 的时间位置受控记录**（教训：早期 + 低 cos + 衰减 = 丢；位置本身是变量，须可复盘）。

参数存 `bench/build/temporal_model.json`，真实库零原文外泄。

## 5. 自有 case（锋芒）

时间轴末尾（近期）注入双 killer 中文 case（`bench/cases/case01`）：
- 换猫粮（dense_ctrl，高 cos，dense 自己够得到）
- 打疫苗（ripple_target，低 cos，靠 callback 养边救回）
- anchorless probe 当负控（应漂移）

用于扫优势区间：killer cos ≈ 0.43~0.55 + 有边。

## 6. 评测

- 指标：**precision@10、denoise、概念救回**（任一低 cos 代理句进 ripple 即命中，符合算法哲学）
- 逐 killer/evidence 报 **dense_full_rank vs ripple_rank vs act_rank** + 优势区间判定
- 负控：LongMemEval abstention 问题 + 自有 anchorless probe，应如期漂移

## 7. 仓库落点（均在 `bench/` submodule）

```
bench/
  sea/            成品 sea_zh.json + provenance（含 text_en）
  build/          fetch / restructure / fit_temporal / assemble（全种子化）
                  + temporal_model.json（脱敏参数）
  run/            runner + eval
  cases/          自有 case（已存在）
  noise/          脱敏噪音（已存在）
```
复用父仓 `plugins/akasha`（算法核心）+ `replay_fast`（MemoryStore/graph_fast/fast_dense）。

## 8. 伦理 / License

- LongMemEval 研究 license：论文标注引用。
- 翻译方法（codex/模型 + gold evidence 人核）论文里声明，保可复现。
- 真实库**只贡献脱敏时序参数**，零原文进仓。

## 9. 范围（YAGNI）

v1 = LongMemEval 单源、单一真实时序模型、复用现有 replay_fast + eval。
不做：PersonaMem、多真实库、多语言、新评测指标。

## 10. 执行分期

- **Phase 1（当前）**：抓取 LongMemEval + 调研/拟合真实库时序 + 产出**成品英文 JSON**（①②④结构 + 重定时，text_zh 留空待译）+ 落到 `bench/` 合适位置。交付后用户用 codex 做翻译（③）。
- Phase 2：嵌入 + 重放 + 评测（⑥⑦），跑出首批 dense vs ripple 对照。
- Phase 3：追加自有 case 扫优势区间（⑤）、整理论文级结果。
