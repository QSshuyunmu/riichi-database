"""hata_queries.py — H 族基准查询（借鉴畠「麻雀統計データベース」问题设计）

H1: 初打 X → 34 牌持有率全表（含手出し/ツモ切り分层）
H2: 第 N 打时点平均向听表（排除立直/副露）
H3: 牌河 3-7 切出种类数 → 向听/一向听率（畠的招牌 L3 查询）
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


def pct(hit: int, n: int) -> float:
    return round(hit / n * 100, 2) if n else None


def load() -> pl.DataFrame:
    return scan_sample(str(V3), step=30)


def h1(df: pl.DataFrame, first_tile: int = 0) -> dict:
    """初打 X → 34 牌持有率全表（hand_34），分手出し/ツモ切り。"""
    t0 = time.time()
    d = df.filter((pl.col("turn") == 1) & (pl.col("tile") == first_tile))
    n = d.height
    if n == 0:
        return {"id": "H1", "状态": "EMPTY", "data": {"n": 0}}
    td = d.filter(pl.col("is_tsumogiri") == 0)
    tg = d.filter(pl.col("is_tsumogiri") == 1)
    rows = []
    for i in range(34):
        h_td = sum(1 for h in td["hand_34"].to_list() if h[i] > 0)
        h_tg = sum(1 for h in tg["hand_34"].to_list() if h[i] > 0)
        rows.append({"牌": TILE_NAMES[i],
                     "手出し持有率": pct(h_td, td.height) if td.height else None,
                     "ツモ切り持有率": pct(h_tg, tg.height) if tg.height else None})
    # 信号提炼: 与 4m(3) 对 1m(0) 的典型对照 (盐泽文章核心发现: 1m→4m 持有率 50%+)
    return {"id": "H1", "问题": f"初打{TILE_NAMES[first_tile]}→34牌持有率全表(手出し/ツモ切り分层)",
            "状态": "OK",
            "data": {"n": n, "手出しn": td.height, "ツモ切りn": tg.height,
                     "rows": rows,
                     "关键": {f"持有{TILE_NAMES[i]}": r["手出し持有率"]
                              for i, r in enumerate(rows) if i in (3, 4, 5, 8)}},
            "elapsed_s": round(time.time() - t0, 2)}


def h2(df: pl.DataFrame, at_turn: int = 6) -> dict:
    """第 N 打时点平均向听表（排除已立直/副露者）。"""
    t0 = time.time()
    # 第 N 打 = turn == at_turn；排除该时点已立直(is_sengenhai)或副露(furo_count>0)
    d = df.filter((pl.col("turn") == at_turn) & (pl.col("is_sengenhai") == 0)
                  & (pl.col("furo_count") == 0) & (pl.col("shanten") >= -1) & (pl.col("shanten") <= 8))
    n = d.height
    rows = []
    for ft in (27, 28, 29, 30, 31, 32, 33,  # 字牌
               0, 8, 9, 17, 18, 26,          # 幺九
               1, 7, 10, 16, 19, 25,         # 2·8
               4, 13, 22):                   # 3-7 (5)
        # 初打牌种: 用第一打 = 该行所在局该玩家 turn==1 的 tile
        pass
    # 简化: 直接用当前行的 tile 作为"初打牌种"的代理不可靠, 改为按第一打分组
    # 需要 join 第一打信息: turn==1 的 tile
    first = df.filter(pl.col("turn") == 1).select(["game_id", "round_idx", "actor", "tile"]).rename({"tile": "_ft"})
    d2 = d.join(first, on=["game_id", "round_idx", "actor"], how="left")
    groups = {}
    for ft in range(34):
        sub = d2.filter(pl.col("_ft") == ft)
        nn = sub.height
        if nn < 100:
            continue
        if ft >= 27:
            label = "字牌"
        elif ft % 9 in (0, 8):
            label = "幺九"
        elif ft % 9 in (1, 7):
            label = "2·8"
        else:
            label = "3-7"
        groups.setdefault(label, [0, 0.0])
        groups[label][0] += nn
        groups[label][1] += float(sub["shanten"].mean()) * nn
    out = [{"初打牌种": k, "n": v[0], "第6打时点平均向听": round(v[1] / v[0], 2)} for k, v in groups.items()]
    return {"id": "H2", "问题": f"初打牌种×第{at_turn}打时点平均向听(排除立直副露)",
            "状态": "OK", "data": {"n": n, "rows": out},
            "elapsed_s": round(time.time() - t0, 2)}


def h3(df: pl.DataFrame) -> dict:
    """牌河 3-7 切出种类数 → 向听/一向听率（初打为幺九或字牌者）。"""
    t0 = time.time()
    # 6打目时点, 初打为幺九/字牌, 无立直副露
    first = df.filter(pl.col("turn") == 1).select(["game_id", "round_idx", "actor", "tile"]).rename({"tile": "_ft"})
    d = df.filter((pl.col("turn") == 6) & (pl.col("is_sengenhai") == 0)
                  & (pl.col("furo_count") == 0) & (pl.col("shanten") >= -1) & (pl.col("shanten") <= 8))
    d = d.join(first, on=["game_id", "round_idx", "actor"], how="left")
    # 限初打幺九/字牌
    d = d.filter((pl.col("_ft") >= 27) | (pl.col("_ft") % 9).is_in([0, 8]))
    # 该玩家 1-6 打切出的 3-7 种类数: 从手切记录重建 -> 需要该局前6打的 tile
    # 简化: 用"当前行之前"的 3-7 中张手切种类数, 通过 shift 近似不可行;
    # 直接统计 turn<=6 该玩家切出的中张种类 -> join 聚合
    cuts = df.filter((pl.col("turn") <= 6) & (pl.col("tile") >= 0) & (pl.col("tile") < 27)
                     & (pl.col("tile") % 9 >= 2) & (pl.col("tile") % 9 <= 6))
    agg = cuts.group_by(["game_id", "round_idx", "actor"]).agg(
        pl.col("tile").n_unique().alias("_mid_kinds"))
    d = d.join(agg, on=["game_id", "round_idx", "actor"], how="left").with_columns(
        pl.col("_mid_kinds").fill_null(0))
    out = []
    for k in (0, 1, 2, 3):
        sub = d.filter(pl.col("_mid_kinds") == k)
        nn = sub.height
        if nn < 50:
            continue
        out.append({"切出3-7种类数": k, "n": nn,
                    "平均向听": round(float(sub["shanten"].mean()), 2),
                    "一向听率": pct(int((sub["shanten"] <= 1).sum()), nn)})
    return {"id": "H3", "问题": "6打前切出3-7种类数→向听/一向听率(初打幺九或字牌)",
            "状态": "OK", "data": {"rows": out},
            "elapsed_s": round(time.time() - t0, 2)}


QUERIES = [lambda df: h1(df, 0), lambda df: h2(df), h3]


def main() -> None:
    df = load()
    print(f"loaded {df.height:,} rows", flush=True)
    results = []
    for fn in QUERIES:
        try:
            r = fn(df)
        except Exception as exc:
            import traceback
            r = {"id": getattr(fn, "__name__", "?"), "状态": "ERROR", "error": repr(exc),
                 "trace": traceback.format_exc()[-400:]}
        results.append(r)
        print(json.dumps(r, ensure_ascii=False, indent=2))
    Path(r"D:\tenhoulib\hata_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nsaved hata_results.json")


if __name__ == "__main__":
    main()
