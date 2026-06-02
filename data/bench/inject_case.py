"""
本地：真实库切片当"海"(全 relabel bg) + 把 case01(猫 episode + 干扰 + ~200 噪音)
整段平移接到真实时间线之后,内部仍按 bursty 节奏散开。输出 combined_slice.json。

= Factory 核心试验：真实大海 + 末尾注入一个完整带噪音的合成 case,看 ripple 能否涌现。
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PRIV = ROOT.parent / "private" / "bench"  # 派生的真实切片只落 private（gitignore）
PRIV.mkdir(parents=True, exist_ok=True)
BASE = datetime.fromisoformat("2026-05-01T09:00:00+08:00")


def build_case_stream(case, noise_dir, inject_per_type, seed=0):
    """复制 run_bench2.build_stream 的 bursty 时间戳逻辑（独立、无插件依赖）。"""
    rng = random.Random(seed)
    raw, order = [], {}

    def add(turn, kind, cluster):
        r = dict(day=int(turn["day"]), user=turn.get("user", ""), asst=turn.get("assistant", ""),
                 kind=kind, cluster=cluster, killer=bool(turn.get("killer", False)))
        order[id(r)] = len(order); raw.append(r)

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
            order[id(r)] = len(order); raw.append(r)

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
    probes = []
    for j, p in enumerate(case.get("probes", [])):
        d = int(p.get("day", PROBE_DAY))
        ts = (BASE + timedelta(days=d - 1, hours=23, minutes=30 + j * 5)).isoformat()
        probes.append(dict(pid=p["probe_id"], ts=ts, text=p["query"]))
    return raw, probes


def main():
    sea = json.loads((PRIV / "real_slice.json").read_text(encoding="utf-8"))
    sea_stream = [dict(user=r["user"], asst=r["asst"], ts=r["ts"], kind="bg", cluster="bg", killer=False)
                  for r in sea["stream"]]
    real_max = max(datetime.fromisoformat(r["ts"]) for r in sea_stream)

    case = json.loads((ROOT / "cases" / "case01_cat_gastroenteritis.json").read_text(encoding="utf-8"))
    ipt = int(case.get("noise", {}).get("inject_per_type", 12))
    craw, cprobes = build_case_stream(case, ROOT / "noise", inject_per_type=ipt)

    # 整段平移到真实时间线之后（+1 天起），内部相对节奏不变（仍 bursty 散开）
    offset = (real_max - BASE) + timedelta(days=1)
    for r in craw:
        r["ts"] = (datetime.fromisoformat(r["ts"]) + offset).isoformat()
    for p in cprobes:
        p["ts"] = (datetime.fromisoformat(p["ts"]) + offset).isoformat()

    combined = sea_stream + [dict(user=r["user"], asst=r["asst"], ts=r["ts"],
                                  kind=r["kind"], cluster=r["cluster"], killer=r["killer"]) for r in craw]
    combined.sort(key=lambda r: r["ts"])

    out = PRIV / "combined_slice.json"
    out.write_text(json.dumps({"stream": combined, "probes": cprobes, "signal_name": "cat"},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    ncat = sum(1 for r in combined if r["cluster"] == "cat")
    nnoise = sum(1 for r in combined if r["kind"] == "noise")
    killer = [r for r in combined if r["killer"]]
    print(f"写出 {out.name}: 总 {len(combined)} turns (海 bg={len(sea_stream)}, 猫={ncat}, 噪音={nnoise}, 干扰={sum(1 for r in combined if r['kind']=='distractor')})")
    print(f"  killer: {killer[0]['user'][:24] if killer else '缺!'}")
    print(f"  probe: {cprobes[0]['text']}  @ {cprobes[0]['ts'][:10]}（真实海截止 {real_max.date()} 之后）")


if __name__ == "__main__":
    main()
