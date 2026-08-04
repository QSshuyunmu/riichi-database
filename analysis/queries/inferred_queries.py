"""inferred_queries.py — B1 批: 他家交互(DI) + 时机(TM) + 流局顺位(SK) 族

DI1: 他家立直后: 自己向听 → 放铳率 (押し引き)
DI2: 两家立直 vs 一家立直时剩余家行为 (和率/放铳/立直率)
DI3: 副露家追立风险 (副露后他家立直 → 副露家放铳率)
TM1: 第一副露巡目 → 手役/收支
TM2: 暗杠/加杠时机 → 听牌/和牌
SK1: 流局时听牌率 (副露+手切模式分层)
SK2: 点差 vs 立直期望值 (ptEV 类)
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
    # scan_sample 已含全局事件序号 _seq (turn 跨家不可比, 用行号判定时点)
    return scan_sample(str(V3), step=30)


# ─── DI1: 他家立直后押し引き ───

def di1(df: pl.DataFrame) -> dict:
    t0 = time.time()
    # 2026-08-04 修正: 一对一 — 放铳仅计"放铳给该立直家"(立直家荣和时 win_tile)
    # 行级重复: 放铳者所有行 kyoku_result==2 → 改为每行判定 tile == win_tile 且立直家荣和
    riichi_games = df.filter(pl.col("is_sengenhai") == 1).select(["game_id", "round_idx"]).unique()
    d = df.join(riichi_games, on=["game_id", "round_idx"], how="inner")
    first_turn = d.filter(pl.col("is_sengenhai") == 1).group_by(["game_id", "round_idx"]).agg(
        pl.col("turn").min().alias("_rt"))
    d = d.join(first_turn, on=["game_id", "round_idx"], how="left")
    after = d.filter((pl.col("turn") >= pl.col("_rt")) & (pl.col("is_sengenhai") == 0))
    # 立直家荣和的 win_tile (每局)
    ron_map = (d.filter((pl.col("is_sengenhai") == 1))
               .select(["game_id", "round_idx", "actor", "turn"])
               .rename({"actor": "_d_actor", "turn": "_d_turn"}))
    d2 = after.join(ron_map, on=["game_id", "round_idx"], how="left")
    d2 = d2.with_columns(
        pl.col("win_tile").alias("_wt"),
        pl.col("kyoku_result").eq(0).alias("_is_ron"),
    )
    # 立直家荣和局: win_tile 是放铳牌; 该行 tile == win_tile → 对立直家放铳
    out = []
    for sh in (0, 1, 2, 3):
        sub = d2.filter(pl.col("shanten") == sh)
        n = sub.height
        if n < 100:
            continue
        # 放铳给立直家: 该行切牌 == win_tile 且该局立直家荣和
        dealt = int(sub.filter(
            (pl.col("_wt") >= 0) & (pl.col("tile") == pl.col("_wt"))
        ).height)
        win = int(((sub["kyoku_result"] == 0) | (sub["kyoku_result"] == 1)).sum())
        out.append({"自己向听": sh, "n": n,
                    "放铳给立直家率": pct(dealt, n),
                    "和率": pct(win, n)})
    # 基线: 立直局中非宣言行的整体放铳给立直家率
    n_base = after.height
    dealt_base = int(after.filter(
        (pl.col("win_tile") >= 0) & (pl.col("tile") == pl.col("win_tile"))
    ).height)
    return {"id": "DI1", "问题": "他家立直后自己向听→放铳给立直家/和率(押し引き, 2026-08-04 修正)",
            "状态": "OK",
            "data": {"rows": out, "基线(立直局非宣言行)": {"n": n_base,
                     "放铳给立直家率": pct(dealt_base, n_base)}},
            "elapsed_s": round(time.time() - t0, 2)}


# ─── DI2: 立直家数 → 剩余家行为 ───

def di2(df: pl.DataFrame) -> dict:
    t0 = time.time()
    # 2026-08-04 修正: 放铳率 = 放铳给立直家 (一对一) — 每行 tile==win_tile 且该局立直家荣和
    cnt = df.filter(pl.col("is_sengenhai") == 1).group_by(["game_id", "round_idx"]).len().rename({"len": "_rc"})
    d = df.join(cnt, on=["game_id", "round_idx"], how="left").with_columns(pl.col("_rc").fill_null(0))
    # 立直家荣和的 win_tile (每局): 立直家(任一) kyoku_result==0 的 win_tile
    ron_map = (df.filter((pl.col("kyoku_result") == 0) & (pl.col("win_tile") >= 0))
               .group_by(["game_id", "round_idx"])
               .agg(pl.col("win_tile").first().alias("_rt_wt")))
    out = []
    for rc in (1, 2):
        sub = d.filter((pl.col("_rc") == rc) & (pl.col("is_sengenhai") == 0))
        sub = sub.join(ron_map, on=["game_id", "round_idx"], how="left")
        n = sub.height
        if n < 100:
            continue
        # 放铳给立直家: 该行 tile == 立直家荣和的 win_tile
        dealt = int(sub.filter(
            (pl.col("_rt_wt") >= 0) & (pl.col("tile") == pl.col("_rt_wt"))
        ).height)
        win = int(((sub["kyoku_result"] == 0) | (sub["kyoku_result"] == 1)).sum())
        out.append({"立直家数": rc, "n": n,
                    "和率": pct(win, n),
                    "放铳给立直家率": pct(dealt, n),
                    "副露率": pct(int((sub["furo_count"] > 0).sum()), n)})
    base = df.filter(pl.col("is_sengenhai") == 0).join(ron_map, on=["game_id", "round_idx"], how="left")
    n0 = base.height
    dealt0 = int(base.filter(
        (pl.col("_rt_wt") >= 0) & (pl.col("tile") == pl.col("_rt_wt"))
    ).height)
    return {"id": "DI2", "问题": "立直家数→剩余家和率/放铳给立直家/副露 (2026-08-04 修正)", "状态": "OK",
            "data": {"rows": out, "无立直局": {"n": n0,
                     "和率": pct(int(((base["kyoku_result"] == 0) | (base["kyoku_result"] == 1)).sum()), n0),
                     "放铳给立直家率": pct(dealt0, n0)}},
            "elapsed_s": round(time.time() - t0, 2)}


# ─── DI3: 副露家追立风险 ───

def di3(df: pl.DataFrame) -> dict:
    t0 = time.time()
    # 2026-08-04 修正: 一对一 — 放铳给立直家 (tile==win_tile 且立直家荣和)
    # 注意: turn 跨家不可比 (副露后不增) → 用行号 _seq 判定"立直后" (load 已加 _seq)
    furo_players = df.filter(pl.col("furo_count") >= 1).select(["game_id", "round_idx", "actor"]).unique()
    riichi_games = df.filter(pl.col("is_sengenhai") == 1).select(["game_id", "round_idx"]).unique()
    d = df.join(furo_players, on=["game_id", "round_idx", "actor"], how="inner").join(
        riichi_games, on=["game_id", "round_idx"], how="inner")
    # 立直家宣言行序号 (每局)
    d_seq = (df.filter(pl.col("is_sengenhai") == 1)
             .group_by(["game_id", "round_idx"])
             .agg(pl.col("_seq").min().alias("_d_seq")))
    ron_map = (df.filter((pl.col("kyoku_result") == 0) & (pl.col("win_tile") >= 0))
               .group_by(["game_id", "round_idx"])
               .agg(pl.col("win_tile").first().alias("_rt_wt")))
    d = d.join(d_seq, on=["game_id", "round_idx"], how="left").join(
        ron_map, on=["game_id", "round_idx"], how="left")
    after = d.filter((pl.col("_seq") >= pl.col("_d_seq")) & (pl.col("is_sengenhai") == 0))
    n = after.height
    dealt = int(after.filter(
        (pl.col("_rt_wt") >= 0) & (pl.col("tile") == pl.col("_rt_wt"))
    ).height)
    out = {"副露家在他家立直后": {"n": n,
           "放铳给立直家率": pct(dealt, n),
           "和率": pct(int(((after["kyoku_result"] == 0) | (after["kyoku_result"] == 1)).sum()), n)}}
    return {"id": "DI3", "问题": "副露家追立风险(他家立直后放铳给立直家/和率, 2026-08-04 修正)",
            "状态": "OK",
            "data": out, "elapsed_s": round(time.time() - t0, 2)}


# ─── TM1: 第一副露巡目 → 和率/收支 ───

def tm1(df: pl.DataFrame) -> dict:
    t0 = time.time()
    # 2026-08-04 修正: 放铳率 = 局级 (该玩家整局结局==2, 每局一次; 行级重复会虚增)
    d = df.with_columns(
        pl.col("furo_count").shift(1).over(["game_id", "round_idx", "actor"]).fill_null(0).alias("_pf"))
    first = d.filter(pl.col("furo_count") > pl.col("_pf"))
    # 每家每局唯一结局: 用 kyoku_result 去重 (backfill 冗余)
    out = []
    for lo, hi, label in ((1, 3, "早(1-3巡)"), (4, 6, "中(4-6巡)"), (7, 99, "晚(7+巡)")):
        sub = first.filter(pl.col("turn").is_between(lo, hi))
        n = sub.height
        if n < 100:
            continue
        # 局级: 每 (game,round,actor) 一行 → 该家结局
        uniq = sub.select("game_id", "round_idx", "actor", "kyoku_result").unique()
        n_uniq = uniq.height
        kr = uniq["kyoku_result"]
        out.append({"第一副露巡目": label, "n": n, "局数": n_uniq,
                    "和率": pct(int(((kr == 0) | (kr == 1)).sum()), n_uniq),
                    "放铳率(局级)": pct(int((kr == 2).sum()), n_uniq),
                    "平均收支": round(float(sub["kyoku_pt_delta"].mean()), 0)})
    return {"id": "TM1", "问题": "第一副露巡目→和率/放铳(局级)/收支 (2026-08-04 修正)", "状态": "OK",
            "data": out, "elapsed_s": round(time.time() - t0, 2)}


# ─── TM2: 杠时机 → 听牌/和牌 ───

def tm2(df: pl.DataFrame) -> dict:
    t0 = time.time()
    # 含暗杠(3)或加杠(4)的行: furo_seq 含 type 3/4
    def has_kan(seq: list) -> bool:
        return any(seq[i] in (3, 4) for i in range(0, len(seq), 2))
    d = df.filter(pl.col("furo_seq").list.len() > 0)
    out = []
    for label, cond in (("含暗/加杠", pl.col("furo_seq").map_elements(
            lambda s: has_kan(s), return_dtype=pl.Boolean)),
                        ("无暗/加杠", pl.col("furo_seq").map_elements(
                            lambda s: not has_kan(s), return_dtype=pl.Boolean))):
        sub = d.filter(cond)
        n = sub.height
        if n < 100:
            continue
        kr = sub["kyoku_result"]
        out.append({"副露类": label, "n": n,
                    "听牌率": pct(int(sub["is_tenpai"].sum()), n),
                    "和率": pct(int(((kr == 0) | (kr == 1)).sum()), n)})
    return {"id": "TM2", "问题": "暗/加杠 vs 无杠→听牌/和率", "状态": "OK",
            "data": out, "elapsed_s": round(time.time() - t0, 2)}


# ─── SK1: 流局听牌率 ───

def sk1(df: pl.DataFrame) -> dict:
    t0 = time.time()
    d = df.filter(pl.col("kyoku_result") == 4)  # draw
    out = []
    for m in (0, 1, 2, 3):
        sub = d.filter(pl.col("furo_count") == m)
        n = sub.height
        if n < 100:
            continue
        out.append({"副露数": m, "n": n,
                    "流局听牌率": pct(int(sub["is_tenpai"].sum()), n)})
    return {"id": "SK1", "问题": "流局时副露数→听牌率", "状态": "OK",
            "data": out, "elapsed_s": round(time.time() - t0, 2)}


# ─── SK2: 点差 vs 立直期望值 ───

def sk2(df: pl.DataFrame) -> dict:
    t0 = time.time()
    s = df.filter(pl.col("is_sengenhai") == 1)
    # 2026-08-04 修正: 放铳率 = 立直家整局结局==2 的局级比例 (行级会重复)
    # 点差 = actor_score - 局最高
    actor_s = s["actor_score"].to_list()
    scores = s["kyoku_scores"].to_list()
    gaps = []
    for a, sc in zip(s["actor"].to_list(), scores):
        gaps.append(a - max(sc) if sc else None)
    s = s.with_columns(pl.Series("_gap", gaps, dtype=pl.Int32))
    out = []
    for lo, hi, label in ((-30000, -5001, "大幅落后"), (-5000, -1, "落后"), (0, 4999, "领先"), (5000, 30000, "大幅领先")):
        sub = s.filter(pl.col("_gap").is_between(lo, hi))
        n = sub.height
        if n < 100:
            continue
        # 局级: 每 (game,round,actor=立直家) 一行 → 该立直家整局结局
        uniq = sub.select("game_id", "round_idx", "actor", "kyoku_result").unique()
        n_u = uniq.height
        kr = uniq["kyoku_result"]
        out.append({"点差": label, "n": n, "局数": n_u,
                    "立直和率": pct(int(((kr == 0) | (kr == 1)).sum()), n_u),
                    "立直被放铳率(局级)": pct(int((kr == 2).sum()), n_u),
                    "平均收支": round(float(sub["kyoku_pt_delta"].mean()), 0)})
    return {"id": "SK2", "问题": "点差→立直和率/被放铳(局级)/收支(EV, 2026-08-04 修正)", "状态": "OK",
            "data": out, "elapsed_s": round(time.time() - t0, 2)}


QUERIES = [di1, di2, di3, tm1, tm2, sk1, sk2]


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
    Path(r"D:\tenhoulib\inferred_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nsaved inferred_results.json")


if __name__ == "__main__":
    main()
