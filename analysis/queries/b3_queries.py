"""b3_queries.py — B3 批: Q2/PY2/Q3

Q2: 他家切 dora（数牌/赤牌/字牌）→ 切出者向听数
PY2: 赤牌持有数 vs 和牌率/收支 (is_aka)
Q3: 牌河特征 → 七对率（规律发掘, is_chiitoi 查询层判定）
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path

import polars as pl
from sample_load import scan_sample

from yaku import is_chiitoi_shape

V3 = Path(r"D:\tenhoulib\v3_200k_v2.parquet")


def pct(hit: int, n: int) -> float:
    return round(hit / n * 100, 2) if n else None


def load() -> pl.DataFrame:
    # 2026-08-04: v3_10k(标签互换) → v3_200k_v2(修复后). 1 亿行不能全载 → 前 500 万行
    # (500 万行 ≈ 10 万局, 统计足够; 避免 OOM)
    return scan_sample(str(V3), step=30)


def dora_of(marker: int) -> int:
    if marker < 0:
        return -1
    if marker < 27:
        return marker + 1 if marker % 9 != 8 else marker - 8
    if marker <= 30:
        return 27 + (marker - 27 + 1) % 4
    return 31 + (marker - 31 + 1) % 3


# ─── Q2: 切 dora 分类 → 向听数 ───

def q2(df: pl.DataFrame) -> dict:
    t0 = time.time()
    d = df.filter((pl.col("dora_marker") >= 0) & (pl.col("tile") >= 0))
    tiles = d["tile"].to_list()
    marks = d["dora_marker"].to_list()
    aka = d["is_aka"].to_list()
    sh = d["shanten"].to_list()
    groups = defaultdict(list)
    for t, m, a, s in zip(tiles, marks, aka, sh):
        dr = dora_of(int(m))
        if a == 1 and t == dr:  # 赤牌且是 dora (赤5 本身是 dora)
            groups["赤牌dora"].append(s)
        elif t == dr and t >= 27:
            groups["字牌dora"].append(s)
        elif t == dr:
            groups["数牌dora"].append(s)
        else:
            groups["非dora"].append(s)
    import statistics
    out = []
    for k, v in groups.items():
        if v:
            out.append({"切牌类": k, "n": len(v), "平均向听": round(statistics.mean(v), 2)})
    return {"id": "Q2", "问题": "切dora分类(数牌/赤/字牌)→切出者向听数", "状态": "OK",
            "data": out, "elapsed_s": round(time.time() - t0, 2)}


# ─── PY2: 赤牌持有数 vs 和牌率/收支 ───

def py2(df: pl.DataFrame) -> dict:
    t0 = time.time()
    # 赤牌持有数: 手牌中赤牌 = hand_34 无法区分 (归一化), 用行内 is_aka 不准确
    # 修正: 赤牌持有需单独统计 → 用"当前行切的是否赤牌"作为持有代理不准确
    # 改用: 该玩家本局切出赤牌数 (is_aka=1 的行数 per game/round/actor)
    aka_rows = df.filter(pl.col("is_aka") == 1)
    cnt = aka_rows.group_by(["game_id", "round_idx", "actor"]).len().rename({"len": "_aka_cnt"})
    d = df.join(cnt, on=["game_id", "round_idx", "actor"], how="left").with_columns(
        pl.col("_aka_cnt").fill_null(0))
    out = []
    for k in (0, 1, 2, 3):
        sub = d.filter(pl.col("_aka_cnt") == k)
        n = sub.height
        if n < 100:
            continue
        # 2026-08-04: 和率改局级 (行级重复虚高) — 每 (game,round,actor) 唯一结局
        uniq = sub.select("game_id", "round_idx", "actor", "kyoku_result", "kyoku_pt_delta").unique()
        kr = uniq["kyoku_result"]
        out.append({"本局切出赤牌数": k, "n": n, "局数": uniq.height,
                    "和率(局级)": pct(int(((kr == 0) | (kr == 1)).sum()), uniq.height),
                    "平均收支": round(float(uniq["kyoku_pt_delta"].mean()), 0)})
    return {"id": "PY2", "问题": "本局切出赤牌数→和率/收支", "状态": "OK",
            "data": out, "elapsed_s": round(time.time() - t0, 2)}


# ─── Q3: 牌河特征 → 七对率 ───

def q3(df: pl.DataFrame) -> dict:
    t0 = time.time()
    d = df.filter(pl.col("furo_count") == 0)
    c7 = []
    for h in d["hand_34"].to_list()[:1500000]:
        c7.append(int(is_chiitoi_shape(h, 0)))
    d = d.head(1500000).with_columns(pl.Series("_c7", c7, dtype=pl.Int8))
    print(f"  [Q3] 样本 {d.height:,} | 七对听牌: {int(d['_c7'].sum()):,}", flush=True)
    # 牌河特征 × 七对率: 字牌手切数 / 拆对 / 中张率
    # 特征1: 该行之前手切字牌数 (pair_broken_last? 用 tile 历史)
    # 简化: 字牌手切比例 (turn 前几打) → 用 is_tsumogiri=0 且 tile>=27 的行计数
    td = df.filter((pl.col("is_tsumogiri") == 0) & (pl.col("tile") >= 27))
    honor_cnt = td.group_by(["game_id", "round_idx", "actor"]).len().rename({"len": "_honor"})
    d = d.join(honor_cnt, on=["game_id", "round_idx", "actor"], how="left").with_columns(
        pl.col("_honor").fill_null(0))
    out = []
    for k in (0, 1, 2, 3, 4):
        sub = d.filter(pl.col("_honor") == k)
        n = sub.height
        if n < 100:
            continue
        out.append({"手切字牌数": k, "n": n, "七对听牌率": pct(int(sub["_c7"].sum()), n)})
    # 特征2: 拆对子 (pair_broken>0) vs 无
    for pb, label in ((0, "无拆对"), (1, "有拆对")):
        sub = d.filter(pl.col("pair_broken") == pb)
        n = sub.height
        if n < 100:
            continue
        out.append({"拆对": label, "n": n, "七对听牌率": pct(int(sub["_c7"].sum()), n)})
    return {"id": "Q3", "问题": "牌河特征(字牌手切/拆对)→七对听牌率", "状态": "OK",
            "data": out, "elapsed_s": round(time.time() - t0, 2)}


QUERIES = [q2, py2, q3]


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
    Path(r"D:\tenhoulib\b3_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nsaved b3_results.json")


if __name__ == "__main__":
    main()
