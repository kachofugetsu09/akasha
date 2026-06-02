"""
Akasha benchmark —— 真实库切片 + bge-m3 重嵌 + 真 replay（内存图，贴合线上 engine.py）。

数据访问改成内存（MemoryStore），与线上 engine.py 一致：召回逻辑仍由真实
AkashaReplayRuntime 驱动（activate_before_turn / commit_turn 原样调用），数字一致、去掉 O(N²) 重载。

corpus：activate_before_turn(检索+状态更新) + commit_turn(建节点/边)，跳过 query_log 卡片构建。
probe：_activate_before_turn 取完整 ReplayActivation（dense/ripple/activation），store 冻结只读。

用法（远端）：
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python run_bench_real.py --slice-json real_slice.json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import numpy as np

import run_bench2 as B  # 装好框架桩 + 导入真 replay/store/core
from mem_store import MemoryStore
import fast_dense  # 向量化 dense（monkeypatch，数字一致）
import graph_fast  # graph_expand in_strength 增量 + edges_by_src/fan 视图（数字一致）
from plugins.akasha.core import normalize as _normalize

HERE = Path(__file__).resolve().parent


def edge_self_clean_report(store, label_by_key, signal_name, probe_ts):
    """自净化检验：猫簇节点的出边，按'目标是不是猫'分组，看有效权/co_count/闲置天数。
    时序巧合连上的无关边(co_count=1、久不复现)应被 14 天衰减饿到近静音。"""
    import math
    from plugins.akasha.core import EDGE_DECAY_TAU

    def lab(k):
        return label_by_key.get(k, {}).get("cluster")

    cat_keys = {k for k in store._nodes if lab(k) == signal_name}
    same, cross = [], []
    for (src, dst), raw in store._edges.items():
        if src not in cat_keys:
            continue
        lu = store._meta.get((src, dst), 0.0)
        co = store._cocount.get((src, dst), 1)
        gap_days = max(0.0, (probe_ts - lu)) / 86400.0
        eff = raw * math.exp(-(probe_ts - lu) / EDGE_DECAY_TAU) if lu > 0 else raw
        rec = (eff, raw, co, gap_days, dst)
        (same if lab(dst) == signal_name else cross).append(rec)

    def stats(rows):
        if not rows:
            return "(无)"
        effs = sorted(r[0] for r in rows)
        cos = sorted(r[2] for r in rows)
        med = lambda a: a[len(a) // 2]
        return f"n={len(rows)} 有效权中位={med(effs):.4f} co_count中位={med(cos)} 静音(<0.03)占比={100*sum(1 for e in effs if e<0.03)/len(effs):.0f}%"

    print("\n========== 边自净化检验（猫簇出边）==========")
    print(f"  猫→猫(相关,会被callback复现):   {stats(same)}")
    print(f"  猫→非猫(时序巧合/无关):          {stats(cross)}")
    print("  --- 猫→非猫 里最弱的5条(被衰减饿死的巧合边) ---")
    for eff, raw, co, gap, dst in sorted(cross)[:5]:
        print(f"    有效权={eff:.4f} raw={raw:.3f} co={co} 闲置{gap:.0f}天 → [{label_by_key.get(dst,{}).get('cluster')}]")
    print("  --- 猫→猫 里最强的5条(反复加固) ---")
    for eff, raw, co, gap, dst in sorted(same, reverse=True)[:5]:
        print(f"    有效权={eff:.4f} raw={raw:.3f} co={co} 闲置{gap:.0f}天")


def full_dense_ranking(store, qv):
    """全库 turn 级 dense 排名（turn embedding · query），返回 {key: rank(1-based)}。"""
    keys = list(store._nodes.keys())
    mat = np.vstack([store._nodes[k].embedding for k in keys])
    scores = mat @ _normalize(qv)
    order = np.argsort(-scores)
    rank = {keys[idx]: i + 1 for i, idx in enumerate(order)}
    return rank


def score_ra(pid, text, ra, label_by_key, text_by_key, killer_key, signal_cluster, dense_rank=None):
    dense, ripple, act = ra.dense_items, ra.ripple_items, ra.activation_items
    dk = {c.key for c in dense[:10]}
    rip_only = [c for c in ripple if c.key not in dk][:10]
    dr = dense_rank or {}

    def lab(k):
        return label_by_key.get(k, {})

    def txt(k):
        return (text_by_key.get(k, k) or "")[:30]

    n = max(1, len(rip_only))
    sig = sum(1 for c in rip_only if lab(c.key).get("cluster") == signal_cluster)
    bg = sum(1 for c in rip_only if lab(c.key).get("cluster") == "bg")
    # 真增量价值：ripple-only 里 signal 簇、且全库 dense 排名 >10（dense top10 没给）；深度看 dense rank
    deep = [c for c in rip_only if lab(c.key).get("cluster") == signal_cluster and dr.get(c.key, 99999) > 10]

    def rank(items):
        for i, c in enumerate(items):
            if c.key == killer_key:
                return i + 1
        return -1

    return {
        "pid": pid, "query": text,
        "episode_precision@10": round(sig / n, 3),
        "bg_in_ripple10": bg,
        "dense_missed_signal_in_ripple10": len(deep),  # dense top10 没给、ripple 补上的相关项数
        "killer_dense_rank(top10)": rank(dense), "killer_dense_full_rank": dr.get(killer_key, -1),
        "killer_ripple_rank": rank(ripple), "killer_act_rank": rank(act),
        "dense_top5": [(round(c.direct, 3), txt(c.key)) for c in dense[:5]],
        "ripple_only_top10": [
            (round(c.score, 2), round(c.direct, 2), dr.get(c.key, -1), c.source,
             lab(c.key).get("cluster"), txt(c.key))
            for c in rip_only],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice-json", required=True)
    ap.add_argument("--model", default="/home/huashen/models/bge-m3")
    ap.add_argument("--cache", default=str(HERE / "emb_cache_real.db"))
    ap.add_argument("--out", default=str(HERE / "bench_real_result.json"))
    args = ap.parse_args()
    fast_dense.install()

    payload = json.loads(Path(args.slice_json).read_text(encoding="utf-8"))
    stream, probes = payload["stream"], payload["probes"]
    signal_name = payload.get("signal_name", "finger")
    for r in stream:
        r["user"] = (r["user"] or "").strip()
        r["asst"] = (r["asst"] or "").strip()
    for p in probes:
        p["text"] = (p["text"] or "").strip()
    n_finger = sum(1 for r in stream if r["cluster"] == "finger")
    print(f"[build] 真实切片 turns={len(stream)} (finger={n_finger}) probes={len(probes)}", flush=True)
    print(f"[build] probe='{probes[0]['text'][:30]}'  killer=鱼石脂(seq7276)", flush=True)

    src_db = HERE / "_real_sessions.db"
    label_by_key, killer_key, probe_meta = B.build_source_db(src_db, stream, probes)
    # key→user 文本（turn i → bench:{2i}）
    text_by_key = {f"bench:{2*i}": r["user"] for i, r in enumerate(stream)}

    texts = []
    for r in stream:
        texts.append(r["user"])
        if r["asst"]:
            texts.append(r["asst"])
    texts += [p["text"] for p in probes]
    emb = B.embed_all(texts, args.cache, args.model)
    print(f"[embed] done dim={len(next(iter(emb.values())))}", flush=True)

    turn_items = B._src_messages(stream, probes)
    n_corpus_seq = 2 * len(stream)
    corpus_items = [it for it in turn_items if it[1][0].seq < n_corpus_seq]
    probe_items = [it for it in turn_items if it[1][0].seq >= n_corpus_seq]

    message_embeddings, message_turn_keys = {}, {}
    for _, msgs in corpus_items:
        for m in msgs:
            message_embeddings[m.id] = emb[m.content]
            message_turn_keys[m.id] = B.turn_key(m.session_key, m.seq, m.role)[2]

    store = MemoryStore()
    graph_fast.install(store)  # 用增量 in_strength / edges_by_src / fan
    src_conn = sqlite3.connect(str(src_db))
    runtime = B.AkashaReplayRuntime(
        store=store, config=B.AkashaConfig(), source_db_path=src_db, source_cursor=src_conn.cursor(),
        message_embeddings=message_embeddings, message_turn_keys=message_turn_keys)

    done = 0
    for _, msgs in corpus_items:
        items = [B.ReplayMessage(message=m, embedding=list(map(float, emb[m.content]))) for m in msgs]
        user = next((m for m in msgs if m.role == "user"), msgs[0])
        act = runtime.activate_before_turn(user, list(map(float, emb[user.content])))
        runtime.commit_turn(items, act)
        done += 1
        if done % 500 == 0:
            print(f"  replay {done}/{len(corpus_items)} nodes={len(store._nodes)} edges={len(store._edges)}", flush=True)

    print(f"[replay] nodes={len(store._nodes)} edges={len(store._edges)}", flush=True)
    fan = store.fan()
    top = sorted(fan.items(), key=lambda x: -x[1])[:6]
    print("[replay] fan top6:", [(label_by_key.get(k, {}).get("cluster"), f) for k, f in top], flush=True)

    # probe：冻结状态，只读
    store._frozen = True
    results = []
    pmeta = {p["text"]: p["pid"] for p in probes}
    for _, msgs in probe_items:
        m = msgs[0]
        drank = full_dense_ranking(store, np.array(emb[m.content], dtype=np.float32))
        ra = runtime._activate_before_turn(m, list(map(float, emb[m.content])))
        pid = pmeta.get(m.content, m.id)
        results.append(score_ra(pid, m.content, ra, label_by_key, text_by_key, killer_key, signal_name, drank))
    src_conn.close()

    from datetime import datetime as _dt
    edge_self_clean_report(store, label_by_key, signal_name, _dt.fromisoformat(probes[0]["ts"]).timestamp())

    report = {"slice": payload.get("meta", "real"), "nodes": len(store._nodes), "edges": len(store._edges),
              "killer_key": killer_key, "probes": results}
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[done] {args.out}", flush=True)
    for r in results:
        print(f"\n── [{r['pid']}] {r['query']}")
        print(f"   precision@10={r['episode_precision@10']}  bg_leak={r['bg_in_ripple10']}  "
              f"★dense漏掉但ripple补上的相关项={r['dense_missed_signal_in_ripple10']}")
        print(f"   killer: dense_top10={r['killer_dense_rank(top10)']}  dense_full_rank={r['killer_dense_full_rank']}  "
              f"ripple_rank={r['killer_ripple_rank']}")
        print("   ripple_only_top10  (denseFullRank = 该条在全库 dense 的真实排名，>10 才是 dense 没给的)：")
        for s_, cos, drk, src, cl, tx in r["ripple_only_top10"]:
            flag = "  ←dense够不到" if (drk > 10 or drk == -1) else ""
            print(f"     s={s_:5.2f} cos={cos:.2f} denseRank={drk:<5} {str(src)[:9]:<9} [{cl}] {tx}{flag}")


if __name__ == "__main__":
    main()
