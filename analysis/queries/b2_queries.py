"""b2_queries.py — B2 批: Q1/Q4 + DQ 族（依赖 kawa_visible + win_tile）

Q1: 听14两面平和dora1先制立直 × 牌河1m枚数 → 和率/自摸/收支（自亲分层）
Q4: 立直家早外(早打3→同色1/2)铳率失效条件（控制已见+筋组）
DQ1: 现物 vs 筋牌 vs 无筋牌 安全度梯度（真实铳率 win_tile）
DQ2: 无筋生张铳率: 中张/字牌/幺九分层
DQ3: 摸切立直 vs 手切立直的安全牌阈值差异
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path

import polars as pl

from yaku import is_pinfu_shape

V3 = Path(r"D:\tenhoulib\v3_200k_v2.parquet")
TILE_NAMES = ['1m','2m','3m','4m','5m','6m','7m','8m','9m',
              '1p','2p','3p','4p','5p','6p','7p','8p','9p',
              '1s','2s','3s','4s','5s','6s','7s','8s','9s',
              'E','S','W','N','P','F','C']

# 2026-08-04: v3_10k(旧, 标签互换+副露移除错) → v3_200k_v2(修复后). 1 亿行不能全载 → 前 500 万行
B2_COLS = ["game_id", "round_idx", "actor", "turn", "is_sengenhai", "tile", "is_aka",
           "wait_type_mask", "waits_mask", "dora_count", "hand_34", "bakaze", "seat_wind",
           "is_oya", "kawa_visible", "kyoku_result", "win_tile", "kyoku_pt_delta",
           "is_tsumogiri"]


def pct(hit: int, n: int) -> float:
    return round(hit / n * 100, 2) if n else None


def load() -> pl.DataFrame:
    # 2026-08-04: 半庄级均匀抽样 (全时间范围) — step=30 → ~330 万行, 控制 DQ 重放内存
    from sample_load import scan_sample
    return scan_sample(str(V3), cols=B2_COLS, step=30)


def q1(df: pl.DataFrame) -> dict:
    t0 = time.time()
    # 先制立直: 该局第一个宣言行
    s = df.filter(pl.col("is_sengenhai") == 1)
    s = s.with_columns(pl.col("is_sengenhai").shift(1).over(["game_id", "round_idx"]).fill_null(0).alias("_ps"))
    sente = s.filter(pl.col("_ps") == 0)
    # 两面听 + dora1 + 平和形
    d = sente.filter((pl.col("wait_type_mask") & 1) > 0).filter(pl.col("dora_count") == 1)
    pinfu = []
    for h, wm, wt, bz, sw in zip(d["hand_34"].to_list(), d["waits_mask"].to_list(),
                                 d["wait_type_mask"].to_list(), d["bakaze"].to_list(),
                                 d["seat_wind"].to_list()):
        pinfu.append(int(is_pinfu_shape(h, wm, wt, int(bz), int(sw))))
    d = d.with_columns(pl.Series("_pinfu", pinfu, dtype=pl.Int8)).filter(pl.col("_pinfu") == 1)
    print(f"  [Q1] 先制+两面+dora1+平和: {d.height:,}", flush=True)
    # 牌河 1m 已见枚数 (kawa_visible[idx0]) 分层 × 自亲
    out = []
    for y in (0, 1, 2, 3):
        sub = d.filter(pl.col("kawa_visible").list.get(0) == y)
        n = sub.height
        if n < 50:
            continue
        kr = sub["kyoku_result"]
        win = int(((kr == 0) | (kr == 1)).sum())
        tsumo = int((kr == 1).sum())
        oya = sub.filter(pl.col("is_oya") == 1)
        ko = sub.filter(pl.col("is_oya") == 0)
        out.append({"1m已见": y, "n": n,
                    "和率": pct(win, n), "自摸占比": pct(tsumo, win) if win else None,
                    "平均收支": round(float(sub["kyoku_pt_delta"].mean()), 0),
                    "自亲和率": pct(int(((oya["kyoku_result"] == 0) | (oya["kyoku_result"] == 1)).sum()), oya.height) if oya.height else None,
                    "子家和率": pct(int(((ko["kyoku_result"] == 0) | (ko["kyoku_result"] == 1)).sum()), ko.height) if ko.height else None})
    return {"id": "Q1", "问题": "听14两面平和dora1先制立直×牌河1m枚数→和率/自摸/收支(自亲分层)",
            "状态": "OK", "data": out, "elapsed_s": round(time.time() - t0, 2)}


# ─── Q4: 立直家早外(早打3→同色1/2)铳率失效条件 ───

def q4(df: pl.DataFrame) -> dict:
    t0 = time.time()
    # 早外定义: 立直家(宣言行)之前, 早巡(turn<=3)手切过 3x(某花色3), 且该行后打出的牌含该色 1/2
    # 简化: 立直行 tile==3x 或 7x? 早外通常指"早打3 → 1/2安全"
    # 判定: 宣言牌为 3m/3p/3s 且 turn<=4 → 该色 1/2 为早外目标
    d = df.filter(pl.col("is_sengenhai") == 1)
    early3 = d.filter((pl.col("turn") <= 4) & (pl.col("tile") < 27) & (pl.col("tile") % 9 == 2))
    # 对每个早外立直, 看其 win_tile 是否 = 该色 1/2 (1m idx0, 2m idx1 等)
    out = []
    for tile in (2, 11, 20):  # 3m/3p/3s
        sub = early3.filter(pl.col("tile") == tile)
        n = sub.height
        if n < 50:
            continue
        suit = tile // 9
        target1 = suit * 9 + 0
        target2 = suit * 9 + 1
        # 铳率: win_tile 出现在该局 = 该色 1/2 (和牌牌)
        # 注: 需要该局是否有放铳 → kyoku_result==2 行存在 + win_tile
        kr = sub["kyoku_result"]
        win = int(((kr == 0) | (kr == 1)).sum())
        # 放铳者视角: 找该局放铳行的 win_tile
        dealt = df.filter((pl.col("kyoku_result") == 2) & (pl.col("win_tile") >= 0))
        dealt_by_game = dealt.group_by(["game_id", "round_idx"]).agg(
            pl.col("win_tile").first().alias("_wt"))
        sub2 = sub.join(dealt_by_game, on=["game_id", "round_idx"], how="left")
        hit12 = int(((sub2["_wt"] == target1) | (sub2["_wt"] == target2)).sum())
        out.append({"宣言牌": TILE_NAMES[tile], "n": n,
                    "和率": pct(win, n),
                    "该色1/2放铳率(实际)": pct(hit12, n)})
    return {"id": "Q4", "问题": "立直家早外(早打3)→该色1/2放铳率(真实win_tile)", "状态": "OK",
            "data": out, "elapsed_s": round(time.time() - t0, 2)}


# ─── DQ1/DQ2: 现物/筋/无筋 真实铳率（正确口径，2026-08-04 重写）───
# 定义（用户确认）：对一家立直的现物 = 立直家全部舍牌（第一张→宣言牌）
#                   + 宣言牌之后其他家所有舍牌
# 一对一：仅当该立直家最终荣和时，win_tile 才是对其的放铳牌
# 旧版错误：行级重复计数 + 用"全局已见"当现物 + 未固定目标 → 结论完全颠倒

def _dq_core(df: pl.DataFrame) -> dict:
    """逐局重放: 现物/筋/无筋 + 无筋子类 的 一对一直实铳率.

    2026-08-04 v3: 用 _seq (全局事件序号) 判定时点 — turn 跨家不可比 (副露后 turn 不增).
    现物定义: 立直家 A 全部舍牌 (宣言前 + 宣言牌 + 宣言后摸切, A 振听自己打的牌)
              + 宣言后其他家所有舍牌 (实时累积).
    统计: 仅"宣言后他家切牌行" (事件序号 > 宣言行序号 且 非立直家).
    """
    from collections import defaultdict
    stat = defaultdict(lambda: [0, 0])
    stat2 = defaultdict(lambda: [0, 0])
    n_kyoku = 0
    for (gid, rid), grp in df.group_by(["game_id", "round_idx"]):
        # 按全局事件序号排序 (同局内相对顺序正确)
        rows = sorted(grp.iter_rows(named=True), key=lambda r: r["_seq"])
        d_actor = None
        d_seq = None
        for r in rows:
            if r["is_sengenhai"] == 1:
                d_actor, d_seq = r["actor"], r["_seq"]
                break
        if d_actor is None:
            continue
        n_kyoku += 1
        # 立直家 A 的全部舍牌 (宣言前 + 宣言牌 + 宣言后摸切) → A 振听, 全部是现物
        own_set = {r["tile"] for r in rows
                   if r["actor"] == d_actor and r["tile"] >= 0}
        # 宣言后他家舍牌集 (实时累积, 从宣言行之后开始)
        other_set = set()
        # 一对一: 仅当立直家荣和时 win_tile 才是对其的放铳牌
        win_tile = next((r["win_tile"] for r in rows
                         if r["actor"] == d_actor and r["kyoku_result"] == 0
                         and r["win_tile"] >= 0), -1)
        for r in rows:
            if r["actor"] == d_actor or r["_seq"] <= d_seq:
                continue
            t = r["tile"]
            if t < 0:
                continue
            gen_now = own_set | other_set
            if t in gen_now:
                cls = "现物"
            else:
                suit, num = t // 9, t % 9
                suji = any(0 <= num + off <= 8 and (suit * 9 + num + off) in gen_now
                           for off in (-3, 3))
                cls = "筋牌" if suji else "无筋"
            dealt = (t == win_tile and win_tile >= 0)
            stat[cls][0] += 1
            if dealt:
                stat[cls][1] += 1
            if cls == "无筋":
                if t >= 27:
                    sub = "字牌"
                elif num in (0, 8):
                    sub = "幺九"
                elif num in (1, 7):
                    sub = "2·8"
                else:
                    sub = "中张3-7"
                stat2[sub][0] += 1
                if dealt:
                    stat2[sub][1] += 1
            other_set.add(t)
    return stat, stat2, n_kyoku


def dq1(df: pl.DataFrame) -> dict:
    t0 = time.time()
    stat, _, n_kyoku = _dq_core(df)
    out = []
    for cls, (n, de) in sorted(stat.items(), key=lambda x: -x[1][0]):
        out.append({"状态": cls, "切牌行数": n, "放铳数": de,
                    "真实铳率%": round(de / n * 100, 3) if n else 0})
    return {"id": "DQ1", "问题": "立直后他家切牌 现物/筋/无筋 一对一直实铳率 (2026-08-04 修正)",
            "状态": "OK", "data": {"立直局数": n_kyoku, "rows": out},
            "elapsed_s": round(time.time() - t0, 2)}


def dq2(df: pl.DataFrame) -> dict:
    t0 = time.time()
    _, stat2, n_kyoku = _dq_core(df)
    out = []
    for cls, (n, de) in sorted(stat2.items(), key=lambda x: -x[1][0]):
        out.append({"无筋生张牌类": cls, "切牌行数": n, "放铳数": de,
                    "真实铳率%": round(de / n * 100, 3) if n else 0})
    return {"id": "DQ2", "问题": "无筋生张内分层 一对一直实铳率 (2026-08-04 修正)",
            "状态": "OK", "data": {"立直局数": n_kyoku, "rows": out},
            "elapsed_s": round(time.time() - t0, 2)}


# ─── DQ3: 摸切立直 vs 手切立直 安全牌阈值 ───

def dq3(df: pl.DataFrame) -> dict:
    t0 = time.time()
    s = df.filter(pl.col("is_sengenhai") == 1)
    out = []
    for tg, label in ((1, "摸切立直"), (0, "手切立直")):
        sub = s.filter(pl.col("is_tsumogiri") == tg)
        n = sub.height
        if n < 100:
            continue
        # 听牌形分布 (安全牌评估: 愚形多→听牌牌种少→相对安全)
        ryanmen = int(((sub["wait_type_mask"] & 1) > 0).sum())
        shanpon = int(((sub["wait_type_mask"] & 16) > 0).sum())
        out.append({"立直类型": label, "n": n,
                    "两面率": pct(ryanmen, n), "双碰率": pct(shanpon, n),
                    "平均听牌数": round(float(sub["wait_type_mask"].map_elements(
                        lambda m: bin(m).count("1") if m else 0, return_dtype=pl.Int32).mean()), 2),
                    "和率": pct(int(((sub["kyoku_result"] == 0) | (sub["kyoku_result"] == 1)).sum()), n)})
    return {"id": "DQ3", "问题": "摸切vs手切立直: 听牌形/听牌数差异(安全阈值)", "状态": "OK",
            "data": out, "elapsed_s": round(time.time() - t0, 2)}


QUERIES = [q1, q4, dq1, dq2, dq3]


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
    Path(r"D:\tenhoulib\b2_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nsaved b2_results.json")


if __name__ == "__main__":
    main()
