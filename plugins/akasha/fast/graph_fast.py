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
                                  source_cursor, edges_by_src, edges_meta, graph_seed_keys):
    if edges_by_src is None or not graph_seed_keys:
        return []

    def _eff(src_key, dst_key, weight):
        if edges_meta is None or now_ts <= 0:
            return weight
        return effective_edge_weight(weight, edges_meta.get((src_key, dst_key), 0.0), now_ts)

    topk_cache: dict = {}

    def _topk(key):
        if key not in topk_cache:
            nbrs = edges_by_src.get(key, {})
            if nbrs:
                scored = sorted(nbrs.items(), key=lambda x: -_eff(key, x[0], x[1]))[:3]
                topk_cache[key] = {k for k, _ in scored}
            else:
                topk_cache[key] = set()
        return topk_cache[key]

    seed_set = {key for key in graph_seed_keys if key in nodes}
    visited = set(seed_set)
    frontier = list(seed_set)
    while frontier:
        node = frontier.pop()
        for nbr in _topk(node):
            if nbr in nodes and nbr not in visited and node in _topk(nbr):
                visited.add(nbr)
                frontier.append(nbr)

    candidates = []
    for key in visited:
        if key in seed_set or not cached_has_user_turn(source_cursor, key):
            continue
        node = nodes[key]
        resource = recover_resource(node, now_ts)
        long_score = min(1.0, node.strength / STRENGTH_CAP)
        direct = max(0.0, direct_scores.get(key, 0.0))
        best_w = 0.0
        for nbr in _topk(key):
            if nbr in visited:
                w = _eff(key, nbr, edges_by_src.get(key, {}).get(nbr, 0.0))
                best_w = max(best_w, w)
        signal = best_w
        score = 6.0 * signal * (GRAPH_DIRECT_BIAS + direct) * (1.0 + 0.15 * long_score)
        candidates.append(AkashaCandidate(
            key=key, source="Graph", ripple=signal,
            direct=direct, state=0.0, edge=signal,
            long=long_score, resource=resource, fan=max(0, fan.get(key, 0)),
            score=float(score * resource), path_type="bfs",
            seed_key=graph_seed_keys[0] if graph_seed_keys else "",
            path_value=best_w))
    candidates.sort(key=lambda item: item.score, reverse=True)
    return candidates


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
