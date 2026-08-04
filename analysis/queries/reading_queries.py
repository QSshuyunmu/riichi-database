"""reading_queries.py — 读牌式查询族（Q1-Q3 示例实现）

Q1: 他人在 x 巡目碰役牌的 2 副露，手切中张(3-7)花色=2 时听牌率
Q2: 早巡切 dora 邻牌，持有 dora 概率/平均数量 vs 基线
Q3: 立直前连续手切拆对子，听牌形分布 vs 平均，按对子类别细分
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import polars as pl
from sample_load import scan_sample

V3 = Path(r"D:\tenhoulib\v3_200k_v2.parquet")

TILE_NAMES = ['1m','2m','3m','4m','5m','6m','7m','8m','9m',
              '1p','2p','3p','4p','5p','6p','7p','8p','9p',
              '1s','2s','3s','4s','5s','6s','7s','8s','9s',
              'E','S','W','N','P','F','C']

W = 1 << 0
RY = 1 << 1
PE = 1 << 2
TA = 1 << 3
SH = 1 << 4
WT_NAME = {W: "两面", RY: "坎张", PE: "边张", TA: "单骑", SH: "双碰"}


def tile_name(i: int) -> str:
    return TILE_NAMES[i] if 0 <= i < 34 else "?"


def dora_from_marker(m: int) -> int:
    """指示牌 → 宝牌（同色后继，风/箭循环）。"""
    if m < 0:
        return -1
    if m < 27:
        if m % 9 == 8:
            return m - 8
        return m + 1
    if m <= 30:
        return 27 + (m - 27 + 1) % 4
    return 31 + (m - 31 + 1) % 3


def wait_type_label(mask: int) -> str:
    labels = []
    for bit, name in ((SH, "双碰"), (TA, "单骑"), (PE, "边张"), (RY, "坎张"), (W, "两面")):
        if mask & bit:
            labels.append(name)
    return "+".join(labels) if labels else "无"


# ─── Q1: 副露听牌率 ───

def q1(df: pl.DataFrame, turn_x: int = 8) -> dict:
    t0 = time.time()
    # 条件: 副露=2 且碰役牌>=1 且 巡目=x 且 中张花色=2
    cond = (
        (pl.col("furo_count") == 2)
        & (pl.col("furo_pon_honor") >= 1)
        & (pl.col("turn") == turn_x)
        & (pl.col("middle_suit_variety") == 2)
    )
    sub = df.filter(cond)
    n = sub.height
    tp = float(sub["is_tenpai"].mean()) if n else None
    # 基线: 同巡目+同副露数（无花色条件）
    base = df.filter((pl.col("furo_count") == 2) & (pl.col("turn") == turn_x))
    nb = base.height
    tpb = float(base["is_tenpai"].mean()) if nb else None
    # 更宽基线: 全部 2 副露
    base2 = df.filter(pl.col("furo_count") == 2)
    nb2 = base2.height
    tpb2 = float(base2["is_tenpai"].mean()) if nb2 else None
    return {"Q": "Q1", "turn": turn_x, "n": n, "tenpai_rate": tp,
            "base_same_turn_n": nb, "base_same_turn_tenpai": tpb,
            "base_all_2furo_n": nb2, "base_all_2furo_tenpai": tpb2,
            "elapsed_s": round(time.time() - t0, 3)}


def q1_turns(df: pl.DataFrame) -> dict:
    """Q1 巡目 4-14 全景。"""
    t0 = time.time()
    rows = []
    for x in range(4, 15):
        r = q1(df, x)
        rows.append(r)
    return {"Q": "Q1_turns", "rows": rows, "elapsed_s": round(time.time() - t0, 3)}


# ─── Q2: dora 邻牌 ───

def _dora_adjacent(marker: int) -> set[int]:
    """dora 的邻牌集合: dora±1（同花色内）。"""
    d = dora_from_marker(marker)
    if d < 0 or d >= 27:
        return set()
    base = (d // 9) * 9
    out = set()
    if d - 1 >= base:
        out.add(d - 1)
    if d + 1 < base + 9:
        out.add(d + 1)
    return out


def q2(df: pl.DataFrame, early_turn: int = 4) -> dict:
    t0 = time.time()
    # 每行: 该局 dora 邻牌 = 依据 dora_marker
    # 早巡(turn<=early)手切 且 切的牌是 dora 邻牌
    d = df.filter(pl.col("turn") <= early_turn).filter(pl.col("dora_marker") >= 0)
    # 向量化: 逐行计算切牌是否 dora 邻牌
    tiles = d["tile"].to_list()
    markers = d["dora_marker"].to_list()
    is_adj = [1 if _dora_adjacent(m) and t in _dora_adjacent(m) else 0
              for t, m in zip(tiles, markers)]
    d = d.with_columns(pl.Series("is_dora_adj", is_adj, dtype=pl.Int8))
    # 条件组: 切 dora 邻牌
    cond = d.filter(pl.col("is_dora_adj") == 1)
    n = cond.height
    dora_gt0 = float((cond["dora_count"] > 0).mean()) if n else None
    avg_dora = float(cond["dora_count"].mean()) if n else None
    # 基线: 早巡切非邻牌
    base = d.filter(pl.col("is_dora_adj") == 0)
    nb = base.height
    base_gt0 = float((base["dora_count"] > 0).mean()) if nb else None
    base_avg = float(base["dora_count"].mean()) if nb else None
    return {"Q": "Q2", "n_adj": n, "hold_dora_rate": dora_gt0, "avg_dora": avg_dora,
            "n_base": nb, "base_hold_rate": base_gt0, "base_avg_dora": base_avg,
            "elapsed_s": round(time.time() - t0, 3)}


def q2_by_tile(df: pl.DataFrame, early_turn: int = 4) -> dict:
    """Q2 按具体牌细分（如切 5m 且 dora=6m 的情况）。"""
    t0 = time.time()
    d = df.filter(pl.col("turn") <= early_turn).filter(pl.col("dora_marker") >= 0)
    tiles = d["tile"].to_list()
    markers = d["dora_marker"].to_list()
    is_adj = [1 if _dora_adjacent(m) and t in _dora_adjacent(m) else 0
              for t, m in zip(tiles, markers)]
    d = d.with_columns(pl.Series("is_dora_adj", is_adj, dtype=pl.Int8))
    cond = d.filter(pl.col("is_dora_adj") == 1)
    # 细分: dora 邻牌的具体牌面 (dora -> 切牌)
    out = []
    for t, m in zip(cond["tile"].to_list(), cond["dora_marker"].to_list()):
        pass
    grp = cond.with_columns(
        (pl.col("dora_marker").map_elements(lambda m: dora_from_marker(int(m)), return_dtype=pl.Int8)).alias("dora_tile")
    ).group_by(["tile", "dora_tile"]).agg(
        pl.len().alias("n"),
        (pl.col("dora_count") > 0).mean().alias("hold_rate"),
        pl.col("dora_count").mean().alias("avg_dora"),
    ).filter(pl.col("n") >= 20).sort("n", descending=True)
    rows = [{"cut": tile_name(r["tile"]), "dora": tile_name(r["dora_tile"]),
             "n": int(r["n"]), "hold_rate": round(float(r["hold_rate"]), 4),
             "avg_dora": round(float(r["avg_dora"]), 3)} for r in grp.to_dicts()]
    return {"Q": "Q2_by_tile", "rows": rows, "elapsed_s": round(time.time() - t0, 3)}


# ─── Q3: 拆对立直 ───

def q3(df: pl.DataFrame) -> dict:
    t0 = time.time()
    s = df.filter(pl.col("is_sengenhai") == 1)
    # 拆对组: 立直前拆过对子
    broken = s.filter(pl.col("pair_broken") >= 1)
    not_broken = s.filter(pl.col("pair_broken") == 0)

    def wait_dist(sub):
        n = sub.height
        out = {}
        for bit, name in ((W, "两面"), (RY, "坎张"), (PE, "边张"), (TA, "单骑"), (SH, "双碰")):
            out[name] = float(((sub["wait_type_mask"] & bit) > 0).mean()) if n else None
        return out

    # 按对子类别细分
    by_class = []
    for cls, label in ((1, "字牌对"), (2, "幺九对"), (3, "中张对")):
        sub = broken.filter(pl.col("pair_broken_last") == cls)
        n = sub.height
        if n < 10:
            continue
        by_class.append({"class": label, "n": int(n), **wait_dist(sub)})

    return {"Q": "Q3", "n_all": int(s.height), "n_broken": int(broken.height),
            "n_not_broken": int(not_broken.height),
            "broken_wait_dist": wait_dist(broken),
            "base_wait_dist": wait_dist(not_broken),
            "by_class": by_class,
            "elapsed_s": round(time.time() - t0, 3)}


def main() -> None:
    df = scan_sample(str(V3), step=30)
    print(f"loaded {df.height:,} rows")
    results = [q1(df, 8), q1_turns(df), q2(df, 4), q2_by_tile(df, 4), q3(df)]
    for r in results:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    Path(r"D:\tenhoulib\reading_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
