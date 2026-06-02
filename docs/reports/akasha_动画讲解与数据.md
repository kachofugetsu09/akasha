# Akasha 四机制 · 三维动画讲解 + 真实数据

> 私有，含真实库脱敏 case。配套公开讲解：`算法边缘巧思与失败模式.md`。
> 数据源：只读快照 `private/experiments/akasha_ro_snapshot.db`（VACUUM INTO 自 `~/.akashic/workspace/memory/akasha.db`，2026-06-01 21:36）+ `sessions.db`（取原文做 label，脱敏后入图）。

## 工具链（可复跑）

```bash
# 1. 重做只读快照（如线上库更新）
.venv/bin/python -c "import sqlite3;c=sqlite3.connect('file:$HOME/.akashic/workspace/memory/akasha.db?mode=ro',uri=True);c.execute('VACUUM INTO ?',('private/experiments/akasha_ro_snapshot.db',))"
# 2. 导出 case JSON（cases/*.json）
.venv/bin/python private/viz/export_case.py            # 全部；或加 name 只跑某个
# 3. 打包自立 HTML（dist/*.html，JSON 内联，file:// 可开、可 iframe）
.venv/bin/python private/viz/build_html.py
# 4. 看：chromium private/viz/dist/index.html
```

- `export_case.py`：`build_case`（spread 模式，查询驱动）+ `build_pruning`/`build_resource`（timeline 模式）。坐标 = embedding PCA→3D，再做斥力松弛 `_force_spread` 把簇推开。脱敏表 `DESENS` 与 `run_real.py` 对齐。
- `akasha-replay.js`：零依赖 Canvas2D + 自前 3D 投影。两种模式：`spread`（种子脉冲→沿链流动→按 score 点亮）、`timeline`（按帧插值 bright/edge 权重）。拖拽旋转、双击恢复自转。
- `build_html.py`：引擎 + 单 case JSON → 自立 HTML + 画廊 `index.html`。

## 六段动画 · 看点与真实数字

### 真涌现（spread 模式）—— 系统存在的理由

**`emergence_bandage`** seq 7372「那还要搞绷带吗」：A 级真涌现。query 无医学语义，图扩散拽回整条就医链。
| 命中 | 源 | path | cos | fan | score |
|---|---|---|---:|---:|---:|
| 打麻药为什么也疼 | Graph | 1hop | 0.49 | 36 | 1.49 |
| 不是换新的引流条吗 | Graph | 1hop | 0.62 | 32 | 1.24 |
| 绷带裹着伸不直 | BlackHole | direct | 0.66 | 16 | 1.18 |
> 看点：top1「麻药」cos 仅 0.49（dense 排不上），靠 1hop 共现边拿到全场最高 score。

**`emergence_limboo`** seq 6922：一句近况 → 整张社交关系图（亡灵契约师·L战士·舍友联机·机器人梗·机宝过a10），全 Graph 命中，dense 给不出。

**`emergence_fitbit`** seq 1783「是 fitbit inspire3」：裸型号事实 → 挂回用途簇（睡眠表·表带·健康查询）。

### 失败面（spread 模式）

**`hubdrift_status`** seq 134「我现在状态怎么样」：无锚漂移的最干净坏例。
| 命中 | fan | cos | score |
|---|---:|---:|---:|
| 今天北京的天气怎么样 | 172 | 0.41 | 0.90 |
| 帮我查询墨尔本天气 | 174 | 0.30 | 0.65 |
| b站视频链接怎么做 | 110 | 0.36 | 0.60 |
> 看点：top 全是 fan 100~174 的 mega-hub，cos 0.3~0.4，纯靠 fan + cross_boost×36 的 edge 拿分。高激活 ≠ 推理。

### 自清洁（timeline 模式）

**`pruning_decay`** src = 天气 scheduler 节点：同一节点 10 条出边，按各自真实闲置时长正向衰减 raw→eff。
| 出边样本 | raw | 闲置 | eff |
|---|---:|---:|---:|
| 最近一起出现的 | 0.36 | 0.6d | 0.348 |
| 昨晚睡得怎么样 | **0.61** | 38d | **0.041** |
| 这个数据不正常吗 | 0.39 | 32d | 0.038 |
> 看点：raw 最高的边因 38 天没复习掉到 1/8；动画里没复习的边一条条变细断开，只剩骨架。用进废退。

### 短期抑制（timeline 模式）

**`resource_depression`** 「我现在健康状态怎么样呢」seq 138/140/142 连发：
| 帧 | 间隔 | 顶部节点 score | resource |
|---|---|---:|---:|
| 第1次 | — | 3.73 | 1.00 |
| 重发 | +204s | 1.57 | 0.69 |
| 再发 | +28s | 1.46 | 0.66 |
| +30min | 恢复 | （回到~3.7） | ~1.0 |
> 看点：同句连发，召回逐次变暗；30min 恢复帧重新亮起。防短期刷屏。

## 备注 / 诚实边界

- **PCA→3D 是展示性投影**，不是图的真实度量；斥力松弛进一步形变，只为可读，别当拓扑结论。
- `pruning_decay` 的语义不如设计场景（拉肚子→消防栓）干净——它是天气 scheduler 节点，邻居混健康/睡眠。但**时间不对称的数学**（raw 近似、eff 差 8~100×）是真实且忠实的，这才是要演示的点。
- `hubdrift` / 真涌现的对照，正是 `private/akasha_emergence_screening_20260531.md` 复筛结论的可视化：**好坏由簇强弱决定，不由扩散量决定**。
- 真实库 A 级真涌现样本稀少（~5 个：7372/6922/7374/7340/1783），dense 一直在兜底——动画选的就是这几条金标准。
