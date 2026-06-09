# Akasha 快速重建 + 确定性修复 · 同步进真实项目 设计

日期：2026-06-09
开发库：`/mnt/data/coding/akasha`（含 `replay_fast/`，本设计在此编写）
目标库：`/mnt/data/coding/akasic-agent`（真实项目，编写后同步过去）

## 1. 背景与目标

本次会话产出两项可同步的成果：

1. **确定性修复**：`plugins/akasha/core.py:1244` 把 `micro_keys = set(seed_sources)` → `dict.fromkeys`。原 `set` 迭代序随 `PYTHONHASHSEED` 漂移，经增量自反馈建图级联放大，导致**同一份 sessions 每次重建图都不一样**。改成保序集合后，重建与 hash 种子无关、逐位可复现。已验证：3 进程×3 seed 重建 3540 节点/135604 边逐位一致。
2. **快速离线重建**：现 `scripts/build_akasha_db.py` 走 sqlite `AkashaStore`，每轮 `list_nodes()`+`load_edges_with_meta()`+O(E) `graph_expand` 重算，整库 O(turns×E)，约十几分钟。改用内存 `MemoryStore`（增量 `in_strength`/`edges_by_src`/`fan` 视图）+ 向量化 dense，整库内存重放约 3 分钟，末尾一次性批量落库。

**范围**：只动**离线重建**这一条路。真实项目的**在线 engine 本就是内存增量**（`engine.py` 有 `_edges_by_src`/`_fan`/`_load_graph_cache`/`_graph_snapshot`），不慢、不碰。

**保真度**：快速重建产出**全保真**新库——nodes + edges + salience_state + query_log + activation_events 全部落库，复用既有 embedding_cache。

## 2. 现状确认（host）

- `plugins/akasha/core.py:1244` 仍是 buggy 的 `set`；host 与开发库的 core.py **仅差这一处修复**。
- `plugins/akasha/replay.py` / `store.py` / `scripts/build_akasha_db.py` 与开发库**逐字一致**。
- host **无 `replay_fast/`**；fast 三件套只在开发库。
- host `store.py` 无 `edges_by_src_view`/`fan_view`/`in_strength`（fast 路不依赖 host store，自带内存 store）。

## 3. 设计

### 3.1 模块边界 `plugins/akasha/fast/`（新增包，纯加性）

| 文件 | 职责 | 依赖 |
|---|---|---|
| `mem_store.py` | `MemoryStore`：内存 nodes/edges + 增量 `edges_by_src_view`/`fan_view`/`in_strength`（exp 衰减因式分解）。含子类 `CapturingMemoryStore`：override `insert_query_log`/`insert_activation_events` → append 到内存 list。 | `plugins.akasha.core`（只读纯函数） |
| `graph_fast.py` | `install(store)`：monkeypatch `core.graph_expand_candidates`（O(E)→读 store.in_strength）+ `replay.edges_by_src`/`fan_counts` 为增量视图 + `has_user_turn` 记忆化。 | core, replay |
| `fast_dense.py` | `install()`：向量化 `dense_message_candidates`（matmul + 缓存归一矩阵）。等价性由 `test_akasha_edge_decay_parity` 的 loop==indexed 断言保证。 | core, replay |
| `dump.py` | `dump_to_db(akasha_db_path, store)`：开 `AkashaStore`→`reset_schema()`（保留 embedding_cache）→ 单事务 `executemany` 批量写 nodes/edges/salience_state/query_log/activation_events。`*_json` kwargs 映射到表列名。 | sqlite3, AkashaStore（仅用 reset_schema + 连接） |

**关键约束（做干净）**：fast/ 靠 `install()` 注入，**不改 core/replay/store/engine 任何一行**。dump 自带落库逻辑，**不改 store.py**。

### 3.2 数据流（`--fast`）

```
sessions.db ──load──> source_messages + replay_turns
                          │  embedding 复用既有 akasha.db 的 embedding_cache
                          ▼
   CapturingMemoryStore + graph_fast.install + fast_dense.install
                          │  逐 turn replay_turn()（全程内存，零 sqlite 往返）
                          │     ├─ 图增量维护在 MemoryStore
                          │     └─ query_log/activation_events append 到内存 list
                          ▼
            dump_to_db(akasha.db, store)  ← 末尾单事务批量 executemany
```

内存占用：query_log ~3500 条×~15KB ≈ 数十 MB，可接受。

### 3.3 `build_akasha_db.py` 改动（加性分支）

- 新增 `--fast`。为真时：构造 `CapturingMemoryStore`、`graph_fast.install`/`fast_dense.install`、`replay_turn` 整库重放、末尾 `dump_to_db`。
- 不带 `--fast`：原 `AkashaStore` 慢路**原样保留**，作 ground-truth / 回退。
- 其余参数（--config/--workspace/--sessions-db/--db-path）共用。

### 3.4 确定性修复（独立）

`core.py:1244-1253`：`set`→`dict.fromkeys`（保序集合，成员判断仍 O(1)，迭代序由确定的 seed→邻居遍历定）。与快速重建解耦，可单独先合。

## 4. 验证

1. **fast vs slow 对拍**（信任新库的关键）：同一 sessions.db 跑 `--fast` 与慢路，比 nodes.strength + edges.weight 的 md5。预期通过（本会话已验 graph_fast==canonical graph_expand、fast_dense==loop dense 整库逐位一致；二者仅浮点求和顺序差异）。
2. **确定性回归测试**：双 `PYTHONHASHSEED` 重建，nodes/edges hash 必相等。
3. 复用既有 `tests/test_akasha_edge_decay_parity.py`（online==replay、vectorized==loop）。
4. **验证在 host 原生跑**（开发库跑 build 需 stub `agent/bus/core.memory`，只能开发不算真验证）。

## 5. 落地与同步顺序

**两件事解耦，分两个 PR：**

1. **PR-1 确定性修复**：`core.py` 1 行（4 行带注释）+ 确定性回归测试。先合，零风险，先吃确定性。
2. **PR-2 快速重建**：新增 `plugins/akasha/fast/` 包 + `build_akasha_db.py --fast` 分支 + 对拍/parity 测试。加性，不动线上。

**同步方式（开发库 → host）：**
- 同步面 = 拷 `plugins/akasha/fast/` 整个新目录 + 两个加性小 diff（`core.py` 1 行、`build_akasha_db.py` --fast 分支）+ 测试文件。
- 同步后在 host **原生跑对拍 + 重建**确认。
- **长期干净的前提**：`plugins/akasha/*` 两边以镜像对待，不在 host 单独分叉 core/replay/store；否则"子库→host"方向会打架。

## 6. 风险

| 风险 | 缓解 |
|---|---|
| dump 列映射 / schema 对齐出错（query_log 字段名 `*_json`→列名） | 对拍 + 读回校验；schema 以 `store.py` 的 CREATE TABLE 为准 |
| fast vs slow 浮点序差异被 knife-edge 放大成图不同 | 本会话已整库验逐位一致；对拍兜底，不一致即 block 合入 |
| 两库 plugins/akasha 分叉 | 约定镜像、同步后 diff 共享文件 |
| 线上 engine 受影响 | 不碰：fast 只在离线 `--fast` 分支，install 不触发于 engine 路径 |

## 7. 非目标（YAGNI）

- 不改在线 engine 的 per-query in_strength（收益小、碰生产路）。
- 不把 AkashaStore 改成增量（动生产 store，风险高）。
- 不替换慢路（保留作参照/回退）。
