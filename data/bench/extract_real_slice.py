"""
本地运行：从真实 sessions.db 抽一段连续切片，脱敏，写成 slice JSON。
只用 sqlite+re，不依赖任何插件/框架。脱敏后的 JSON 才允许同步到远端 embed。

用法（本地）：
  python extract_real_slice.py --sessions ~/.akashic/workspace/sessions.db \
     --session telegram:7674283004 --cutoff 7440 --probe-seq 7442 \
     --out real_slice.json
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path

DESENS = [
    (r"花月哥哥", "哥哥"), (r"花月", "U"), (r"huashen258|huashen", "U"),
    (r"字节跳动|字节", "某大厂"), (r"shopee|Shopee", "某外企"),
    (r"北京工业大学|北工大", "某校"), (r"(?i)limboo", "L"),
    (r"(?i)akashic|akasic", "助手"), (r"奶农", "队友A"), (r"奶龙", "群友"),
    (r"(?i)terasumc", "网友T"), (r"7674283004", ""), (r"2236", "某作品"),
]


def desens(t: str) -> str:
    for pat, rep in DESENS:
        t = re.sub(pat, rep, t or "")
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions", default=str(Path.home() / ".akashic/workspace/sessions.db"))
    ap.add_argument("--session", default="telegram:7674283004")
    ap.add_argument("--cutoff", type=int, default=7440)
    ap.add_argument("--probe-seq", type=int, default=7442)
    ap.add_argument("--killer-seq", type=int, default=7276)  # 鱼石脂
    ap.add_argument("--finger-lo", type=int, default=7160)
    ap.add_argument("--episode-keywords", default="", help="逗号分隔；给定则按关键词标 signal 簇（散布型episode）")
    ap.add_argument("--signal-name", default="finger")
    _priv = Path(__file__).resolve().parent.parent.parent / "private" / "bench"
    _priv.mkdir(parents=True, exist_ok=True)
    ap.add_argument("--out", default=str(_priv / "real_slice.json"))
    args = ap.parse_args()
    kws = [k for k in args.episode_keywords.split(",") if k.strip()]

    db = sqlite3.connect(args.sessions)
    rows = db.execute(
        "SELECT seq,role,content,ts FROM messages WHERE session_key=? AND seq<=? ORDER BY seq",
        (args.session, args.cutoff)).fetchall()
    by = {s: (r, c, t) for s, r, c, t in rows}
    stream = []
    for s, (r, c, t) in sorted(by.items()):
        if r != "user" or not (c or "").strip():
            continue
        a = by.get(s + 1)
        asst = a[1] if (a and a[0] == "assistant") else ""
        du = desens(c)[:2000]
        if kws:
            is_sig = any(k in du for k in kws)
        else:
            is_sig = args.finger_lo <= s <= args.cutoff
        cluster = args.signal_name if is_sig else "bg"
        stream.append(dict(day=0, user=du, asst=desens(asst)[:2000],
                           kind=("signal" if is_sig else "bg"),
                           cluster=cluster, killer=(s == args.killer_seq), ts=t))
    prow = db.execute("SELECT content,ts FROM messages WHERE session_key=? AND seq=?",
                      (args.session, args.probe_seq)).fetchone()
    db.close()
    probe_text = desens(prow[0]) if prow else "但是拔出来引流条的时候出了好多血"
    probe_ts = prow[1] if prow else stream[-1]["ts"]
    stream.sort(key=lambda r: r["ts"])
    probes = [dict(pid="bleed", ts=probe_ts, text=probe_text),
              dict(pid="anchorless", ts=probe_ts, text="我现在状态怎么样")]

    n_finger = sum(1 for r in stream if r["cluster"] == args.signal_name)
    killer = [r for r in stream if r["killer"]]
    Path(args.out).write_text(json.dumps({"stream": stream, "probes": probes, "signal_name": args.signal_name}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"写出 {args.out}: turns={len(stream)} signal({args.signal_name})={n_finger} probes={len(probes)}")
    print(f"  probe='{probe_text[:34]}'  killer命中={len(killer)} ({killer[0]['user'][:24] if killer else '缺!'})")


if __name__ == "__main__":
    main()
