"""
graph_fast —— 消灭 graph_expand 的 O(E)/轮（in_strength 全边遍历）+ replay 每轮重建
edges_by_src/fan_counts。

做法（不改源文件，monkeypatch）：
  * core.graph_expand_candidates：函数体一字不改，只把 in_strength 的 O(E) 循环换成读
    ACTIVE.in_strength(dst, now_ts)（= e^{-(now-t0)/τ}·A_dec[dst]+A_const[dst]，增量维护）。
  * replay.edges_by_src / replay.fan_counts：返回 ACTIVE 的增量视图，免每轮 O(E) 重建。

等价：in_strength 因式分解后与原 Σ effective_edge_weight 数学恒等（仅浮点求和顺序差异，
不影响 rank/指标）。靠差分 parity test 对拍验证。
"""
from __future__ import annotations

import math

import plugins.akasha.core as _core
import plugins.akasha.replay as _replay
from plugins.akasha.core import (
    AkashaCandidate, _GraphPathAggregate, GRAPH_DIRECT_BIAS, GRAPH_EXPAND_LIMIT,
    STRENGTH_CAP, effective_edge_weight, has_user_turn as _orig_has_user_turn, recover_resource,
)

ACTIVE = None  # 当前 MemoryStore
_HUT_CACHE: dict[str, bool] = {}  # has_user_turn 记忆化（源库固定、纯可缓存）


def cached_has_user_turn(cursor, key):
    v = _HUT_CACHE.get(key)
    if v is None:
        v = _orig_has_user_turn(cursor, key)
        _HUT_CACHE[key] = v
    return v


def _fast_graph_expand_candidates(query_vec, nodes, direct_scores, fan, now_ts,
                                  source_cursor, edges_by_src, edges_meta, graph_seed_keys,
                                  *, max_waves=1, expand_limit=GRAPH_EXPAND_LIMIT):
    if edges_by_src is None or not graph_seed_keys:
        return []

    def _eff(src_key, dst_key, weight):
        if edges_meta is None or now_ts <= 0:
            return weight
        return effective_edge_weight(weight, edges_meta.get((src_key, dst_key), 0.0), now_ts)

    seed_set = {key for key in graph_seed_keys if key in nodes}
    store = ACTIVE  # in_strength 增量来源（替代 O(E) 全边遍历）

    aggregate: dict[str, _GraphPathAggregate] = {}
    frontier = {
        key: (key, max(GRAPH_DIRECT_BIAS, max(0.0, direct_scores.get(key, 0.0))))
        for key in graph_seed_keys
        if key in nodes
    }
    seen = set(seed_set)
    for wave in range(1, max(1, max_waves) + 1):
        next_frontier = {}
        wave_decay = math.pow(0.68, wave - 1)
        for frontier_key, (root_seed, root_energy) in frontier.items():
            raw_neighbors = edges_by_src.get(frontier_key, {})
            out_strength = sum(_eff(frontier_key, dst_key, w) for dst_key, w in raw_neighbors.items())
            if out_strength <= 0:
                continue
            scored_neighbors = []
            for key, edge_weight in raw_neighbors.items():
                if key not in nodes or key in seed_set or not cached_has_user_turn(source_cursor, key):
                    continue
                effective_weight = _eff(frontier_key, key, edge_weight)
                s = store.in_strength(key, now_ts)
                dst_strength = effective_weight if s is None else s
                edge_signal = effective_weight / math.sqrt(max(out_strength * dst_strength, 1e-9))
                direct = max(0.0, direct_scores.get(key, 0.0))
                candidate_signal = edge_signal * root_energy * wave_decay
                scored_neighbors.append((candidate_signal, edge_signal, direct, key, effective_weight))
            scored_neighbors.sort(reverse=True, key=lambda item: item[0])
            per_node_limit = max(GRAPH_EXPAND_LIMIT, min(16, expand_limit))
            for candidate_signal, edge_signal, direct, key, edge_weight in scored_neighbors[:per_node_limit]:
                item = aggregate.setdefault(key, _GraphPathAggregate(direct=direct, seed_key=root_seed))
                item.signal += candidate_signal
                item.paths += 1.0
                item.direct = max(item.direct, direct)
                if candidate_signal > item.best_signal:
                    item.best_signal = candidate_signal
                    item.best_edge = edge_signal
                    item.best_weight = edge_weight
                    item.seed_key = root_seed
                    item.best_wave = wave
                if key not in seen:
                    next_frontier[key] = (root_seed, max(candidate_signal, GRAPH_DIRECT_BIAS * wave_decay))
        if not next_frontier:
            break
        seen.update(next_frontier)
        frontier = next_frontier

    candidates = []
    for key, item in aggregate.items():
        node = nodes[key]
        resource = recover_resource(node, now_ts)
        long_score = min(1.0, node.strength / STRENGTH_CAP)
        direct = item.direct
        paths = max(1.0, item.paths)
        signal = item.signal * (1.0 + math.log(paths))
        score = 6.0 * signal * (GRAPH_DIRECT_BIAS + direct) * (1.0 + 0.15 * long_score)
        candidates.append(AkashaCandidate(
            key=key, source="Graph", ripple=item.best_weight, direct=direct, state=0.0,
            edge=signal, long=long_score, resource=resource, fan=max(0, fan.get(key, 0)),
            score=float(score * resource), path_type=f"{max(1, item.best_wave)}hop",
            seed_key=item.seed_key, path_value=item.best_edge))
    candidates.sort(key=lambda item: item.score, reverse=True)
    return candidates[:expand_limit]


_ORIG: dict = {}  # uninstall 还原用：首次 install 时存下被替换的原函数


def install(store):
    global ACTIVE
    ACTIVE = store
    _HUT_CACHE.clear()
    if not _ORIG:
        _ORIG.update(
            graph_expand_candidates=_core.graph_expand_candidates,
            has_user_turn=_core.has_user_turn,
            edges_by_src=_replay.edges_by_src,
            fan_counts=_replay.fan_counts,
        )
    _core.graph_expand_candidates = _fast_graph_expand_candidates
    _core.has_user_turn = cached_has_user_turn  # score_candidates 也走缓存
    _replay.edges_by_src = lambda edges: store.edges_by_src_view()
    _replay.fan_counts = lambda edges: store.fan_view()
    print("[graph_fast] installed (in_strength 增量 + has_user_turn 缓存 + edges_by_src/fan 视图)", flush=True)


def uninstall():
    """还原被 install 替换的全局函数（同进程测试/复用时必须调用，避免污染后续 replay）。"""
    global ACTIVE
    ACTIVE = None
    _HUT_CACHE.clear()
    if not _ORIG:
        return
    _core.graph_expand_candidates = _ORIG["graph_expand_candidates"]
    _core.has_user_turn = _ORIG["has_user_turn"]
    _replay.edges_by_src = _ORIG["edges_by_src"]
    _replay.fan_counts = _ORIG["fan_counts"]
    _ORIG.clear()
