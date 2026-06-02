# Akasha benchmark / case factory 设施

因果重放 + 评测管线：复用真实 `plugins/akasha/replay.py`（`AkashaReplayRuntime`），
内存图 + 增量优化让 ~3000 turn 的重放从 ~11 分钟降到 ~1 分钟，数字与落库版完全等价（parity 对拍 0 差异）。

## 文件

| 文件 | 作用 |
|---|---|
| `run_bench2.py` | 框架桩（sys.modules 桩掉 agent/bus/core.memory/memory2 → 导入真 replay）+ 合成 case 构流/source-db/embed/score 工具；被 `run_bench_real` 复用 |
| `run_bench_real.py` | 主入口：内存图因果重放 + probe 只读评测（含 dense 全库排名诊断、边自净化检验）|
| `mem_store.py` | 纯内存版 AkashaStore（duck-type），增量维护 nodes/edges/fan/edges_by_src/in_strength(A 因式分解)；替代每轮 sqlite 全表重载 O(N²) |
| `fast_dense.py` | dense_message_candidates 向量化 + 缓存归一矩阵（monkeypatch，数字一致）|
| `graph_fast.py` | graph_expand in_strength 增量（e^{-(t-t0)/τ}·A[d]）+ has_user_turn 记忆化（monkeypatch，数字一致）|
| `extract_real_slice.py` | **本地**：从真实 sessions.db 抽连续切片、脱敏 → slice JSON（只用 sqlite，无插件依赖）|
| `inject_case.py` | **本地**：真实库切片当"海" + 末尾平移注入合成 case（内部 bursty 散开）→ combined slice |
| `../noise/*.json` | 8 类脱敏合成噪音库（各 60 对），按真实库 fan 分布注入当背景 |
| `../cases/*.json` | 合成 episode（如 case01 猫肠胃炎），signal_cluster + distractor + 噪音配比 + probe + killer |

## 派生的真实数据 → `private/bench/`（不入库）

`extract_real_slice.py` / `inject_case.py` 默认把切片写到 `private/bench/`（`private/` 已 gitignore）：
- `real_slice.json` / `limboo_slice.json` / `combined_slice.json` —— 派生自真实对话，脱敏后仍属个人内容
- embedding 缓存 / 中间库（`*.db`、`emb_cache*`）只存在于带 bge-m3 的远端 `~/akasha_bench/`，不回传

仓库里只放**无 PII 的可复用资产**：scaffold 代码、合成噪音库（`../noise/`）、合成 case（`../cases/`）。

## 流程

```
extract_real_slice.py（本地脱敏）→ slice JSON
  └─ inject_case.py 注入合成 case → combined slice
       └─ 同步到带 bge-m3 的远端 → run_bench_real.py（内存重放 + probe + 评测）
```

bge-m3 在远端 in-process 加载（本地权重路径 + `HF_HUB_OFFLINE=1`）。向量 build 时现嵌、带 cache。

## 已验证的结论（见项目记忆 akasha-benchmark）

- 真实手指 episode 切片（bge-m3 重嵌）：bleed probe ripple precision@10=1.0、鱼石脂 dense 够不到→ripple 召回。
- 注入合成 case：薄 episode 失败（漂移），加厚 + killer 绑定 callback 成功（precision 0.8、深层项 dense#79/#114 被 ripple 拉回）。
- 性能优化前后 parity 0 差异、~10× 提速、线性扩展。
- Factory 配方：episode 够厚 + 强自引用 + 话题半正交 + 合理 SNR + killer 真低 cos；不达标由 grader 过产自动筛。
