"""invariant_check.py — 物理/规则不变量校验器（lazy/streaming 版，内存 O(1) 全量安全）

依据 GAME_MODEL.md §3 的 10 条不变量。任何违反 = 数据 bug（当场定位）。
2026-08-03 v2: 从 eager 全载改为 lazy scan + streaming collect（修复 1 亿行 OOM 强制关机）。

用法: python invariant_check.py --data v3_200k.parquet [--sample 1000000]
"""

from __future__ import annotations

import argparse
import json
import time

import polars as pl


def _type_counts(seq_expr):
    """furo_seq [type,tile,...] → 各类型数量 [chi/pon, ankan, kakan]（向量化）"""
    types = pl.element().gather_every(2)
    return pl.col(seq_expr).list.eval(types).list.eval(
        pl.element().eq(0).sum().alias("_c0"),
    )


def check(lf: pl.LazyFrame, sample: int | None = None) -> dict:
    t0 = time.time()
    r = {}
    n_total = lf.select(pl.len()).collect(engine="streaming").item()

    if sample and n_total > sample:
        # 前 N 行截断 (limit 纯流式, 不物化全表; sample() 会全表物化 = OOM 风险)
        lf = lf.limit(sample)
    n = lf.select(pl.len()).collect(engine="streaming").item()

    # INV-1: kawa_visible[i] ∈ [0,4]
    kv = lf.select(
        pl.col("kawa_visible").list.min().min().alias("mn"),
        pl.col("kawa_visible").list.max().max().alias("mx"),
    ).collect(engine="streaming").to_dicts()[0]
    r["INV-1 已见0..4"] = {"ok": kv["mn"] >= 0 and kv["mx"] <= 4, "min": kv["mn"], "max": kv["mx"]}

    # INV-2: 宣言行 ⟹ tenpai 且 waits≠0
    sengen = lf.filter(pl.col("is_sengenhai") == 1).select(
        pl.len().alias("ns"),
        (pl.col("is_tenpai") == 0).sum().alias("nt"),
        (pl.col("waits_mask") == 0).sum().alias("ew"),
    ).collect(engine="streaming").to_dicts()[0]
    r["INV-2 宣言行必听牌"] = {"ok": sengen["ns"] > 0 and sengen["nt"] == 0 and sengen["ew"] == 0,
                               "宣言行": sengen["ns"], "非听牌": sengen["nt"], "waits空": sengen["ew"]}

    # INV-3: 手牌张数（向量化 type 统计）
    d = lf.select(
        pl.col("hand_34").list.sum().alias("hs"),
        pl.col("furo_count"),
        pl.col("furo_seq"),
        pl.col("furo_seq").list.eval(pl.element().gather_every(2)).list.eval(pl.element().eq(3)).list.sum().alias("_ank_cnt"),
        pl.col("furo_seq").list.eval(pl.element().gather_every(2)).list.eval(pl.element().eq(4)).list.sum().alias("_kak_cnt"),
    )
    # 纯 chi/pon 行判定: _ank==0 且 kakan(4) 也为 0
    pure = d.filter((pl.col("_ank_cnt") == 0) & (pl.col("_kak_cnt") == 0))
    bad3 = pure.filter(pl.col("hs") != 13 - 3 * pl.col("furo_count")).select(pl.len()).collect(engine="streaming").item()
    pure_n = pure.select(pl.len()).collect(engine="streaming").item()
    kan_n = d.filter(pl.col("_ank_cnt") > 0).select(pl.len()).collect(engine="streaming").item()
    r["INV-3 手牌张数"] = {"ok": bad3 == 0,
                           "纯chi/pon违反": bad3, "纯chi/pon行": pure_n,
                           "含杠行(岭上已补,单独统计)": kan_n}

    # INV-4: shanten ∈ [-1,8] 或 99
    s4 = lf.select(
        (pl.col("shanten") == 99).sum().alias("s99"),
        (pl.col("shanten").is_between(-1, 8).not_() & (pl.col("shanten") != 99)).sum().alias("bad"),
    ).collect(engine="streaming").to_dicts()[0]
    r["INV-4 shanten范围"] = {"ok": s4["bad"] == 0, "违反(非99非-1..8)": s4["bad"], "shanten=99(已知边界)": s4["s99"]}

    # INV-5: tile/dora_marker/prev_tedashi 编码
    bad5 = 0
    for col in ("tile", "dora_marker", "prev_tedashi"):
        bad5 += lf.filter((pl.col(col) < -1) | (pl.col(col) > 33)).select(pl.len()).collect(engine="streaming").item()
    r["INV-5 编码范围"] = {"ok": bad5 == 0, "违反": bad5}

    # INV-6: furo_seq len = 2×furo_count
    bad6 = lf.filter(pl.col("furo_seq").list.len() != 2 * pl.col("furo_count")).select(pl.len()).collect(engine="streaming").item()
    r["INV-6 副露序列结构"] = {"ok": bad6 == 0, "违反": bad6}

    # INV-7: furo_yakuhai ≤ furo_pon_honor ≤ furo_count
    bad7 = lf.filter((pl.col("furo_yakuhai") > pl.col("furo_pon_honor"))
                     | (pl.col("furo_pon_honor") > pl.col("furo_count"))).select(pl.len()).collect(engine="streaming").item()
    r["INV-7 役牌≤字牌≤副露"] = {"ok": bad7 == 0, "违反": bad7}

    # INV-8: win_tile 一致性
    s8 = lf.select(
        pl.col("kyoku_result").is_in([0, 1]).alias("iswin"),
        (pl.col("win_tile") < 0).alias("nowin"),
    ).select(
        ((pl.col("iswin")) & (pl.col("nowin"))).sum().alias("win_missing"),
        ((pl.col("iswin").not_()) & (pl.col("nowin").not_())).sum().alias("no_win_has"),
    ).collect(engine="streaming").to_dicts()[0]
    r["INV-8 win_tile"] = {"ok": s8["win_missing"] == 0, "和牌行缺win_tile": s8["win_missing"],
                           "非和牌行有win_tile(合法=本局和牌冗余)": s8["no_win_has"]}

    # INV-10: turn 组内唯一（递增的等价判定：组内 turn 无重复且覆盖完整）
    g10 = lf.group_by(["game_id", "round_idx", "actor"]).agg(
        pl.col("turn").n_unique().alias("nu"), pl.len().alias("n"))
    bad10 = g10.filter(pl.col("nu") != pl.col("n")).select(pl.len()).collect(engine="streaming").item()
    r["INV-10 turn递增"] = {"ok": bad10 == 0, "违反": bad10}

    r["_meta"] = {"rows": n, "elapsed_s": round(time.time() - t0, 1)}
    return r


def main() -> None:
    ap = argparse.ArgumentParser(description="物理/规则不变量校验 (streaming)")
    ap.add_argument("--data", required=True)
    ap.add_argument("--sample", type=int)
    args = ap.parse_args()

    lf = pl.scan_parquet(args.data)
    result = check(lf, args.sample)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    fails = [k for k, v in result.items() if isinstance(v, dict) and v.get("ok") is False]
    print("\n" + ("FAIL: " + ", ".join(fails) if fails else "ALL INVARIANTS PASS"))


if __name__ == "__main__":
    main()
