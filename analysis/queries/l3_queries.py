"""l3_queries.py — 变则副露 L3: 听牌范围判断（研究验证形态）

用 furo_seq 判定手役，对照 waits_mask/wait_type_mask 验证听牌范围约束:
  L3a: 染手系(副露全同色) → 听牌是否集中在染手色
  L3b: 全带系(副露含幺九) → 听牌是否受幺九约束
  L3c: 对对系(全碰) → 听牌形状(单骑/双碰占比)
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path

import polars as pl
from sample_load import scan_sample

V3 = Path(r"D:\tenhoulib\v3_200k_v2.parquet")


def pct(hit: int, n: int) -> float:
    return round(hit / n * 100, 2) if n else None


def load() -> pl.DataFrame:
    return scan_sample(str(V3), step=30)


def furo_pairs(seq: list) -> list:
    return [(seq[i], seq[i + 1]) for i in range(0, len(seq), 2)]


def l3a(df: pl.DataFrame) -> dict:
    """染手系: 副露全同色 → 听牌集中在染手色? (waits_mask 验证)"""
    t0 = time.time()
    d = df.filter((pl.col("furo_count") >= 2) & (pl.col("is_tenpai") == 1))
    total = 0
    in_color = 0  # 听牌全在染手色
    partial = 0   # 部分在染手色
    for seq, mask in zip(d["furo_seq"].to_list(), d["waits_mask"].to_list()):
        pairs = furo_pairs(seq)
        suits = {t // 9 for typ, t in pairs if 0 <= t < 27}
        if len(suits) != 1:
            continue
        suit = suits.pop()
        total += 1
        waits = [i for i in range(34) if (mask >> i) & 1]
        if not waits:
            continue
        in_c = sum(1 for i in waits if i // 9 == suit)
        if in_c == len(waits):
            in_color += 1
        elif in_c > 0:
            partial += 1
    return {"id": "L3a", "问题": "染手系→听牌集中在染手色? (研究验证)",
            "状态": "OK",
            "data": {"染手听牌局面": total,
                     "听牌全在染手色": pct(in_color, total),
                     "部分在染手色": pct(partial, total),
                     "听牌含染手色(全+部)": pct(in_color + partial, total)},
            "elapsed_s": round(time.time() - t0, 2)}


def l3b(df: pl.DataFrame) -> dict:
    """全带系: 副露含幺九 → 听牌受幺九约束? (waits_mask 验证)"""
    t0 = time.time()
    d = df.filter((pl.col("furo_count") >= 1) & (pl.col("is_tenpai") == 1))
    stat = defaultdict(lambda: [0, 0])  # cls -> [n, waits_all_yaochu]
    for seq, mask in zip(d["furo_seq"].to_list(), d["waits_mask"].to_list()):
        pairs = furo_pairs(seq)
        has_yaochu = False
        has_mid = False
        for typ, t in pairs:
            if 0 <= t < 27:
                if t % 9 in (0, 8):
                    has_yaochu = True
                else:
                    has_mid = True
            else:
                has_yaochu = True
        if has_yaochu and has_mid:
            cls = "混幺九+中张"
        elif has_yaochu:
            cls = "全幺九/字"
        else:
            cls = "全中张"
        waits = [i for i in range(34) if (mask >> i) & 1]
        if not waits:
            continue
        all_yaochu = all(i >= 27 or i % 9 in (0, 8) for i in waits)
        stat[cls][0] += 1
        stat[cls][1] += int(all_yaochu)
    out = [{"类": k, "n": v[0], "听牌全为幺九/字率": pct(v[1], v[0])} for k, v in stat.items()]
    return {"id": "L3b", "问题": "全带系→听牌受幺九约束? (研究验证)",
            "状态": "OK", "data": out, "elapsed_s": round(time.time() - t0, 2)}


def l3c(df: pl.DataFrame) -> dict:
    """对对系: 全碰 → 听牌形状(单骑/双碰占比) vs 基线"""
    t0 = time.time()
    d = df.filter((pl.col("furo_count") >= 2) & (pl.col("is_tenpai") == 1))
    stat = defaultdict(lambda: [0, 0, 0, 0])  # cls -> [n, shanpon, tanki, ryanmen]
    for seq, wm in zip(d["furo_seq"].to_list(), d["wait_type_mask"].to_list()):
        pairs = furo_pairs(seq)
        types = [typ for typ, _ in pairs]
        if all(t == 1 for t in types):
            cls = "全碰(对对系)"
        elif any(t == 1 for t in types):
            cls = "含碰"
        else:
            cls = "全吃"
        stat[cls][0] += 1
        stat[cls][1] += int((wm & 16) > 0)   # 双碰
        stat[cls][2] += int((wm & 8) > 0)    # 单骑
        stat[cls][3] += int((wm & 1) > 0)    # 两面
    out = [{"类": k, "n": v[0], "双碰率": pct(v[1], v[0]),
            "单骑率": pct(v[2], v[0]), "两面率": pct(v[3], v[0])} for k, v in stat.items()]
    return {"id": "L3c", "问题": "对对系→听牌形状(单骑/双碰) (研究验证)",
            "状态": "OK", "data": out, "elapsed_s": round(time.time() - t0, 2)}


QUERIES = [l3a, l3b, l3c]


def main() -> None:
    df = load()
    print(f"loaded {df.height:,} rows", flush=True)
    results = []
    for fn in QUERIES:
        try:
            r = fn(df)
        except Exception as exc:
            import traceback
            r = {"id": fn.__name__, "状态": "ERROR", "error": repr(exc),
                 "trace": traceback.format_exc()[-400:]}
        results.append(r)
        print(json.dumps(r, ensure_ascii=False, indent=2))
    Path(r"D:\tenhoulib\l3_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nsaved l3_results.json")


if __name__ == "__main__":
    main()
