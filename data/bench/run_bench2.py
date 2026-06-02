"""
Akasha benchmark v2 —— 直接驱动真实 AkashaReplayRuntime（plugins/akasha/replay.py）。

兼容办法：engine.py 顶部依赖 agent/bus/core.memory/memory2 框架，远端没有；
engine.py 用 `from __future__ import annotations`，方法签名不求值，只有类体
`DESCRIPTOR = MemoryEngineDescriptor(...)` 需要真对象 —— 故在 sys.modules 里桩掉
这几个模块（给足 EngineProfile/MemoryCapability/MemoryEngineDescriptor），即可导入真 replay。

因果由 store 增量提交保证（list_nodes 只含已提交节点）；probe 作为 user-only turn
按 ts 最后回放，写进 akasha_query_log，评测直接读该表（与真实库同格式）。

用法（远端，bge-m3 本地权重）：
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python run_bench2.py \
    --case cases/case01_cat_gastroenteritis.json --noise-dir noise \
    --inject-per-type 25 --model /home/huashen/models/bge-m3
"""
from __future__ import annotations

import argparse
import enum
import json
import random
import sqlite3
import struct
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # 让 `import plugins.akasha.*` 可解析

# ── 桩掉框架模块（必须在 import plugins.akasha.replay 之前）──────────────
def _mod(name: str) -> types.ModuleType:
    m = types.ModuleType(name)
    sys.modules[name] = m
    return m


for _pkg in ["agent", "bus", "core", "core.memory", "core.net", "memory2"]:
    _mod(_pkg)
_mod("agent.config_models").Config = type("Config", (), {})
_mod("bus.events_lifecycle").TurnCommitted = type("TurnCommitted", (), {})
_mod("bus.event_bus").EventBus = type("EventBus", (), {})
_mod("core.net.http").SharedHttpResources = type("SharedHttpResources", (), {})
_mod("memory2.embedder").Embedder = type("Embedder", (), {})
_cme = _mod("core.memory.engine")


class EngineProfile(enum.Enum):
    RICH_MEMORY_ENGINE = "rich_memory_engine"


class MemoryCapability(enum.Enum):
    INGEST_MESSAGES = "ingest_messages"
    RETRIEVE_SEMANTIC = "retrieve_semantic"
    RETRIEVE_CONTEXT_BLOCK = "retrieve_context_block"
    RETRIEVE_STRUCTURED_HITS = "retrieve_structured_hits"
    SEMANTICS_RICH_MEMORY = "semantics_rich_memory"


class MemoryEngineDescriptor:
    def __init__(self, *, name, profile, capabilities, notes=None):
        self.name = name
        self.profile = profile
        self.capabilities = capabilities
        self.notes = notes or {}


_cme.EngineProfile = EngineProfile
_cme.MemoryCapability = MemoryCapability
_cme.MemoryEngineDescriptor = MemoryEngineDescriptor
for _n in ["EvidenceRef", "MemoryIngestRequest", "MemoryIngestResult", "MemoryMutation",
           "MemoryMutationResult", "MemoryQuery", "MemoryQueryResult", "MemoryRecord",
           "MemoryScope", "MemoryToolProfile", "MemoryToolSpec"]:
    setattr(_cme, _n, type(_n, (), {}))

# ── 现在可安全导入真实 replay / store / core ────────────────────────────
from plugins.akasha.config import AkashaConfig  # noqa: E402
from plugins.akasha.core import SourceMessage, turn_key  # noqa: E402
from plugins.akasha.replay import AkashaReplayRuntime, ReplayMessage  # noqa: E402
from plugins.akasha.store import AkashaStore  # noqa: E402

BASE = datetime.fromisoformat("2026-05-01T09:00:00+08:00")


# ── 嵌入（远端 in-process bge-m3 + 本地 cache）──────────────────────────
def _pack(v):
    v = list(v)
    return struct.pack(f"{len(v)}f", *v)


def _vec(b):
    return np.array(struct.unpack(f"{len(b)//4}f", b), dtype=np.float32)


def embed_all(texts, cache_path, model_name):
    cache = sqlite3.connect(cache_path)
    cache.execute("CREATE TABLE IF NOT EXISTS e(txt TEXT PRIMARY KEY, emb BLOB)")
    have = {r[0] for r in cache.execute("SELECT txt FROM e")}
    todo = [t for t in dict.fromkeys(texts) if t and t not in have]
    if todo:
        from sentence_transformers import SentenceTransformer
        print(f"[embed] 加载 {model_name}，待嵌入 {len(todo)} 条…", flush=True)
        model = SentenceTransformer(model_name)
        embs = model.encode(todo, normalize_embeddings=True, batch_size=32, show_progress_bar=True)
        for t, v in zip(todo, embs):
            cache.execute("INSERT OR REPLACE INTO e VALUES (?,?)", (t, _pack(v)))
        cache.commit()
    out = {t: _vec(e) for t, e in cache.execute("SELECT txt,emb FROM e")}
    cache.close()
    return out


# ── 构流：派突发式时间戳 + 注入噪音（标签仅评测用）──────────────────────
def build_stream(case, noise_dir, inject_per_type, seed=0):
    rng = random.Random(seed)
    raw = []
    order = {}

    def add(turn, kind, cluster):
        r = dict(day=int(turn["day"]), user=turn.get("user", ""), asst=turn.get("assistant", ""),
                 kind=kind, cluster=cluster, killer=bool(turn.get("killer", False)))
        order[id(r)] = len(order)
        raw.append(r)

    for cl in case.get("signal_clusters", []):
        for t in cl.get("turns", []) + cl.get("callbacks", []):
            add(t, "signal", cl["cluster_id"])
    for cl in case.get("distractor_clusters", []):
        for t in cl.get("turns", []):
            add(t, "distractor", cl["cluster_id"])

    PROBE_DAY = int(case.get("noise", {}).get("probe_day", 13))
    for ntype in case.get("noise", {}).get("types", []):
        f = noise_dir / f"{ntype}.json"
        if not f.exists():
            continue
        pairs = json.loads(f.read_text(encoding="utf-8"))["pairs"]
        rng.shuffle(pairs)
        for p in pairs[:inject_per_type]:
            r = dict(day=rng.randint(1, PROBE_DAY), user=p["user"], asst=p["assistant"],
                     kind="noise", cluster=ntype, killer=False)
            order[id(r)] = len(order)
            raw.append(r)

    # 突发式 session：同簇同天聚一段；不同段隔数小时 → 跨段不进彼此 30min 微图
    NOISE_SLOTS = 6
    sess = {}
    for r in raw:
        sid = ("sig", r["cluster"], r["day"]) if r["kind"] != "noise" else ("noise", r["day"], rng.randint(0, NOISE_SLOTS - 1))
        sess.setdefault(sid, []).append(r)
    for sid, turns in sess.items():
        if sid[0] == "sig":
            day, hour = sid[2], 9 + (abs(hash(sid[1])) % 6) * 2
        else:
            day, hour = sid[1], 8 + sid[2] * 2 + rng.uniform(0, 1.2)
        t = BASE + timedelta(days=day - 1, hours=hour, minutes=rng.uniform(0, 20))
        for r in sorted(turns, key=lambda x: order[id(x)]):
            r["_ts"] = t
            t = t + timedelta(seconds=min(1500, max(15, rng.lognormvariate(4.7, 1.0))))
    for r in raw:
        r["ts"] = r["_ts"].isoformat()
    raw.sort(key=lambda r: r["ts"])

    probes = []
    for j, p in enumerate(case.get("probes", [])):
        d = int(p.get("day", PROBE_DAY))
        ts = (BASE + timedelta(days=d - 1, hours=23, minutes=30 + j * 5)).isoformat()
        probes.append(dict(pid=p["probe_id"], ts=ts, text=p["query"]))
    return raw, probes


# ── 构 source sessions.db（messages + FTS trigram）──────────────────────
def build_source_db(path: Path, stream, probes):
    if path.exists():
        path.unlink()
    db = sqlite3.connect(str(path))
    db.executescript(
        "CREATE TABLE messages(id TEXT,session_key TEXT,seq INTEGER,role TEXT,content TEXT,ts TEXT);"
        "CREATE VIRTUAL TABLE messages_fts USING fts5(content,content='messages',content_rowid='rowid',tokenize='trigram');"
        "CREATE TRIGGER ai AFTER INSERT ON messages BEGIN INSERT INTO messages_fts(rowid,content) VALUES(new.rowid,new.content); END;"
    )
    rows = []  # (msg_id, seq, role, content, ts, turn_index_meta)
    label_by_key = {}
    killer_key = None
    seq = 0
    for i, r in enumerate(stream):
        ukey = turn_key("bench", seq, "user")[2]
        label_by_key[ukey] = dict(kind=r["kind"], cluster=r["cluster"], killer=r["killer"])
        if r["killer"]:
            killer_key = ukey
        rows.append((f"bench:{seq}:u", seq, "user", r["user"], r["ts"]))
        if r["asst"]:
            rows.append((f"bench:{seq+1}:a", seq + 1, "assistant", r["asst"], r["ts"]))
        seq += 2
    probe_meta = []
    for p in probes:
        rows.append((f"bench:{seq}:u", seq, "user", p["text"], p["ts"]))
        probe_meta.append(dict(pid=p["pid"], seq=seq, text=p["text"], ts=p["ts"]))
        seq += 2
    for mid, s, role, content, ts in rows:
        db.execute("INSERT INTO messages(id,session_key,seq,role,content,ts) VALUES(?,?,?,?,?,?)",
                   (mid, "bench", s, role, content, ts))
    db.commit()
    db.close()
    return label_by_key, killer_key, probe_meta


def _src_messages(stream, probes):
    """生成 (turn_items) 序列：每个元素是该 turn 的 SourceMessage 列表（user[+asst]）。"""
    items = []
    seq = 0
    for r in stream:
        msgs = [SourceMessage(id=f"bench:{seq}:u", session_key="bench", seq=seq, role="user", content=r["user"], ts=r["ts"])]
        if r["asst"]:
            msgs.append(SourceMessage(id=f"bench:{seq+1}:a", session_key="bench", seq=seq + 1, role="assistant", content=r["asst"], ts=r["ts"]))
        items.append((r["ts"], msgs))
        seq += 2
    for p in probes:
        items.append((p["ts"], [SourceMessage(id=f"bench:{seq}:u", session_key="bench", seq=seq, role="user", content=p["text"], ts=p["ts"])]))
        seq += 2
    items.sort(key=lambda x: x[0])
    return items


# ── 评测：读 akasha_query_log（与真实库同格式）──────────────────────────
def score(akasha_db: Path, probe_meta, label_by_key, killer_key, signal_cluster):
    db = sqlite3.connect(str(akasha_db))
    db.row_factory = sqlite3.Row
    out = []
    for pm in probe_meta:
        row = db.execute("SELECT * FROM akasha_query_log WHERE seq=? AND query_text=?",
                         (pm["seq"], pm["text"])).fetchone()
        if row is None:
            out.append({"pid": pm["pid"], "query": pm["text"], "error": "no query_log"})
            continue
        dense = json.loads(row["dense_items"] or "[]")
        ripple = json.loads(row["ripple_items"] or "[]")
        act = json.loads(row["activation_items"] or "[]")

        def lab(k):
            return label_by_key.get(k, {})

        rip10 = ripple[:10]
        n = max(1, len(rip10))
        sig = sum(1 for c in rip10 if lab(c.get("key")).get("cluster") == signal_cluster)
        noise = sum(1 for c in rip10 if lab(c.get("key")).get("kind") == "noise")
        leak = sum(1 for c in rip10 if lab(c.get("key")).get("kind") == "distractor")

        def rank(items):
            for i, c in enumerate(items):
                if c.get("key") == killer_key:
                    return i + 1
            return -1

        out.append({
            "pid": pm["pid"], "query": pm["text"],
            "seed_count": row["seed_count"], "pool_count": row["pool_count"],
            "episode_precision@10": round(sig / n, 3),
            "denoise(noise in ripple10)": noise,
            "cluster_leak(distractor)": leak,
            "killer_dense_rank": rank(dense),
            "killer_ripple_rank": rank(ripple),
            "killer_act_rank": rank(act),
            "dense_top5": [(round(c.get("direct", 0), 2), (c.get("user_message") or "")[:30]) for c in dense[:5]],
            "ripple_top8": [(round(c.get("score", 0), 2), round(c.get("direct", 0), 2), c.get("source", ""),
                             lab(c.get("key")).get("cluster"), lab(c.get("key")).get("kind"),
                             (c.get("user_message") or "")[:26]) for c in rip10[:8]],
        })
    db.close()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", required=True)
    ap.add_argument("--noise-dir", required=True)
    ap.add_argument("--inject-per-type", type=int, default=25)
    ap.add_argument("--cache", default=str(HERE / "emb_cache.db"))
    ap.add_argument("--model", default="/home/huashen/models/bge-m3")
    ap.add_argument("--out", default=str(HERE / "bench2_result.json"))
    args = ap.parse_args()

    case = json.loads(Path(args.case).read_text(encoding="utf-8"))
    stream, probes = build_stream(case, Path(args.noise_dir), args.inject_per_type)
    print(f"[build] stream={len(stream)} turns, probes={len(probes)}", flush=True)

    src_db = HERE / "_bench_sessions.db"
    label_by_key, killer_key, probe_meta = build_source_db(src_db, stream, probes)
    signal_cluster = (case.get("signal_clusters") or [{}])[0].get("cluster_id")

    texts = []
    for r in stream:
        texts.append(r["user"])
        if r["asst"]:
            texts.append(r["asst"])
    texts += [p["text"] for p in probes]
    emb = embed_all(texts, args.cache, args.model)
    dim = len(next(iter(emb.values())))
    print(f"[embed] done dim={dim}", flush=True)

    turn_items = _src_messages(stream, probes)
    message_embeddings = {}
    message_turn_keys = {}
    for _, msgs in turn_items:
        for m in msgs:
            message_embeddings[m.id] = emb[m.content]
            message_turn_keys[m.id] = turn_key(m.session_key, m.seq, m.role)[2]

    akasha_db = HERE / "_bench_akasha.db"
    if akasha_db.exists():
        akasha_db.unlink()
    store = AkashaStore(akasha_db)
    cfg = AkashaConfig()
    src_conn = sqlite3.connect(str(src_db))
    runtime = AkashaReplayRuntime(
        store=store, config=cfg, source_db_path=src_db, source_cursor=src_conn.cursor(),
        message_embeddings=message_embeddings, message_turn_keys=message_turn_keys,
    )
    for _, msgs in turn_items:
        items = [ReplayMessage(message=m, embedding=list(map(float, emb[m.content]))) for m in msgs]
        runtime.replay_turn(items)
    src_conn.close()

    edges = store._db.execute("SELECT COUNT(*) FROM akasha_edges").fetchone()[0]
    nodes = store._db.execute("SELECT COUNT(*) FROM akasha_nodes").fetchone()[0]
    fan = {}
    for s, d in store._db.execute("SELECT src_key,dst_key FROM akasha_edges"):
        fan[s] = fan.get(s, 0) + 1
        fan[d] = fan.get(d, 0) + 1
    top_fan = sorted(fan.items(), key=lambda x: -x[1])[:6]
    print(f"[replay] nodes={nodes} edges={edges}", flush=True)
    print("[replay] fan top6:", [(label_by_key.get(k, {}).get("cluster"), f) for k, f in top_fan], flush=True)
    store.close()

    results = score(akasha_db, probe_meta, label_by_key, killer_key, signal_cluster)
    report = {"case": case.get("case_id"), "dim": dim, "nodes": nodes, "edges": edges,
              "signal_cluster": signal_cluster, "killer_key": killer_key, "probes": results}
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[done] {args.out}", flush=True)
    for r in results:
        if "error" in r:
            print(f"\n── [{r['pid']}] {r['query']}  ERROR={r['error']}")
            continue
        print(f"\n── [{r['pid']}] {r['query']}  (seed={r['seed_count']} pool={r['pool_count']})")
        print(f"   episode_precision@10={r['episode_precision@10']}  denoise={r['denoise(noise in ripple10)']}  leak={r['cluster_leak(distractor)']}")
        print(f"   killer  dense_rank={r['killer_dense_rank']}  ripple_rank={r['killer_ripple_rank']}  act_rank={r['killer_act_rank']}")
        print(f"   dense_top5: {r['dense_top5']}")
        print("   ripple_top8:")
        for s_, cos, src, cl, kd, tx in r["ripple_top8"]:
            print(f"     s={s_:5.2f} cos={cos:.2f} {str(src)[:9]:<9} [{cl}/{kd}] {tx}")


if __name__ == "__main__":
    main()
