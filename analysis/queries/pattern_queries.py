"""pattern_queries.py — 新族基准查询：手切骨架模式(G1) + 变则副露读牌(V)

基于 grill-me 定案的需求（BASELINE_QUERIES.md 五章）:
  G1a: 手切骨架 2 连 → 立直听牌形（含间隔巡数）
  G1b: 相邻手切 vs 间隔手切的信号对比（验证: 间隔 ≥ 相邻）
  G1c: 手切骨架花色集中度 → 染手倾向
  V1:  副露组合(副露数×役牌×中张花色) → 听牌率映射表
  V2:  染手代理色(手牌花色集中) × 溢出状态(手切/摸切/无) → 听牌率
  V3:  溢出状态 × 最终和率（溢出判断有效性验证）

全部基于 v3 现有列，代理法，不加 ETL。
"""

from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from pathlib import Path

import polars as pl

V3 = Path(r"D:\tenhoulib\v3_200k_v2.parquet")

WAIT_BITS = {"两面": 1, "坎张": 2, "边张": 4, "单骑": 8, "双碰": 16}


def pct(hit: int, n: int) -> float:
    return round(hit / n * 100, 2) if n else None


def load() -> pl.DataFrame:
    """加载 + 计算手切骨架（同玩家内前 2 次手切 + 间隔巡数）。"""
    from sample_load import scan_sample
    df = scan_sample(str(V3), step=30)
    df = df.with_columns(
        pl.col("furo_count").shift(1).over(["game_id", "round_idx", "actor"]).alias("_prev_furo"),
        pl.col("turn").shift(1).over(["game_id", "round_idx", "actor"]).alias("_prev_turn"),
    ).with_columns(
        (pl.col("furo_count") - pl.col("_prev_furo").fill_null(0)).alias("_furo_delta")
    )
    # 手切骨架: 仅手切行，取该行之前最近 2 次手切 (tile + 巡目)
    td = df.filter(pl.col("is_tsumogiri") == 0)
    td = td.with_columns(
        pl.col("tile").shift(1).over(["game_id", "round_idx", "actor"]).alias("_td1"),
        pl.col("turn").shift(1).over(["game_id", "round_idx", "actor"]).alias("_td1_turn"),
        pl.col("tile").shift(2).over(["game_id", "round_idx", "actor"]).alias("_td2"),
        pl.col("turn").shift(2).over(["game_id", "round_idx", "actor"]).alias("_td2_turn"),
    )
    return df, td


# ─── G1a: 手切骨架 → 立直听牌形（含间隔巡数）───

def g1a(df: pl.DataFrame, td: pl.DataFrame) -> dict:
    t0 = time.time()
    s = td.filter(pl.col("is_sengenhai") == 1)
    s = s.filter((pl.col("_td1") >= 0) & (pl.col("_td1") < 27) & (pl.col("tile") < 27))
    n = s.height
    # 手切骨架 2 连: 宣言牌 tile, 前一手切 _td1
    same_suit = s.filter(pl.col("_td1") // 9 == pl.col("tile") // 9)
    gap = same_suit.with_columns(
        (pl.col("turn") - pl.col("_td1_turn")).alias("_gap")
    )
    out = []
    # 按间隔巡数分组: 0=相邻(连切), 1, 2-3, 4+
    for lo, hi, label in ((0, 0, "相邻连切"), (1, 1, "隔1巡"), (2, 3, "隔2-3巡"), (4, 99, "隔4巡+")):
        sub = gap.filter(pl.col("_gap").is_between(lo, hi))
        nn = sub.height
        if nn < 10:
            continue
        dist = {}
        for name, bit in WAIT_BITS.items():
            dist[name] = pct(int(((sub["wait_type_mask"] & bit) > 0).sum()), nn)
        out.append({"间隔": label, "n": nn, "听牌形": dist})
    # 基线: 所有立直前手切(同花色不要求)
    base = s
    nb = base.height
    return {"id": "G1a", "问题": "手切骨架2连(同花色)→立直听牌形, 按间隔分组", "状态": "OK",
            "data": {"立直前手切总数": nb, "同花色2连": int(same_suit.height), "分组": out},
            "elapsed_s": round(time.time() - t0, 2)}


# ─── G1b: 相邻 vs 间隔手切的信号对比 ───

def g1b(df: pl.DataFrame, td: pl.DataFrame) -> dict:
    t0 = time.time()
    s = td.filter(pl.col("is_sengenhai") == 1)
    s = s.filter((pl.col("_td1") >= 0) & (pl.col("_td1") < 27) & (pl.col("tile") < 27))
    s = s.with_columns((pl.col("turn") - pl.col("_td1_turn")).alias("_gap"))
    same = s.filter(pl.col("_td1") // 9 == pl.col("tile") // 9)
    # 相邻(同花色, gap<=1) vs 间隔(同花色, gap>=2)
    adj = same.filter(pl.col("_gap") <= 1)
    gap = same.filter(pl.col("_gap") >= 2)
    out = []
    for label, sub in (("相邻(gap<=1)", adj), ("间隔(gap>=2)", gap)):
        nn = sub.height
        out.append({
            "组": label, "n": nn,
            "跨筋率": pct(_cross_count(sub), nn),
            "双碰率": pct(int(((sub["wait_type_mask"] & 16) > 0).sum()), nn),
            "和率": pct(int(((sub["kyoku_result"] == 0) | (sub["kyoku_result"] == 1)).sum()), nn),
        })
    return {"id": "G1b", "问题": "相邻vs间隔手切信号对比(跨筋/双碰/和率)", "状态": "OK",
            "data": out, "elapsed_s": round(time.time() - t0, 2)}


def _cross_count(sub: pl.DataFrame) -> int:
    """宣言牌 x, 听 x-2 与 x+1 (跨筋)。"""
    cross = 0
    for tile, mask in zip(sub["tile"].to_list(), sub["waits_mask"].to_list()):
        num = tile % 9
        suit = tile // 9
        low, high = num - 2, num + 1
        if 0 <= low and high <= 8:
            if (mask >> (suit * 9 + low)) & 1 and (mask >> (suit * 9 + high)) & 1:
                cross += 1
    return cross


# ─── G1c: 手切骨架花色集中度 → 染手倾向 ───

def g1c(df: pl.DataFrame, td: pl.DataFrame) -> dict:
    t0 = time.time()
    s = td.filter(pl.col("is_sengenhai") == 1)
    # 手切骨架花色集中: 宣言行之前的手切(前2次)花色 vs 手牌
    d = s.filter((pl.col("_td1") >= 0) & (pl.col("_td1") < 27))
    out = []
    for suit in range(3):
        # 骨架集中于该花色 (前2手切都是该花色)
        sub = d.filter((pl.col("_td1") // 9 == suit) & (pl.col("_td2") // 9 == suit))
        n = sub.height
        if n < 10:
            continue
        # 手牌该花色密度
        dens = []
        for h in sub["hand_34"].to_list():
            dens.append(sum(h[suit * 9:(suit + 1) * 9]))
        out.append({"骨架花色": ["万", "筒", "索"][suit], "n": n,
                    "手牌该花色均值": round(sum(dens) / n, 2),
                    "和率": pct(int(((sub["kyoku_result"] == 0) | (sub["kyoku_result"] == 1)).sum()), n)})
    return {"id": "G1c", "问题": "手切骨架花色集中→手牌密度/和率", "状态": "OK",
            "data": out, "elapsed_s": round(time.time() - t0, 2)}


# ─── V1: 副露组合 → 听牌率映射表 ───

def v1(df: pl.DataFrame) -> dict:
    t0 = time.time()
    # 映射表: 副露数(1-3) × 役牌碰数(0-2) × 中张花色种类(0-3) → 听牌率
    d = df.filter(pl.col("furo_count").is_between(1, 3))
    rows = []
    for fc in (1, 2, 3):
        for yk in (0, 1, 2):
            for mv in (0, 1, 2, 3):
                sub = d.filter((pl.col("furo_count") == fc) & (pl.col("furo_yakuhai") >= yk)
                               & (pl.col("furo_yakuhai") < yk + 1 if yk < 2 else pl.col("furo_yakuhai") >= 2)
                               & (pl.col("middle_suit_variety") == mv))
                # 修正条件: yk 精确匹配
                if yk < 2:
                    sub = d.filter((pl.col("furo_count") == fc) & (pl.col("furo_yakuhai") == yk)
                                   & (pl.col("middle_suit_variety") == mv))
                n = sub.height
                if n < 50:
                    continue
                rows.append({"副露数": fc, "役牌碰": yk, "中张花色": mv, "n": n,
                             "听牌率": pct(int(sub["is_tenpai"].sum()), n)})
    # 信号提炼: 听牌率最高的 5 个单元格
    rows_sorted = sorted(rows, key=lambda r: -(r["听牌率"] or 0))
    return {"id": "V1", "问题": "副露组合→听牌率映射表", "状态": "OK",
            "data": {"单元格数": len(rows), "top5高听牌": rows_sorted[:5],
                     "bottom5低听牌": rows_sorted[-5:]},
            "elapsed_s": round(time.time() - t0, 2)}


# ─── V2: 染手代理色 × 溢出状态 → 听牌率 ───

def v2(df: pl.DataFrame) -> dict:
    t0 = time.time()
    # 染手代理: 副露>0 且手牌某花色 >=5 张（染手倾向强）
    d = df.filter(pl.col("furo_count") >= 1)
    # 对每行计算: 染手代理色 + 该色溢出状态
    # 手牌花色计数
    hand_suits = d["hand_34"].to_list()
    tiles = d["tile"].to_list()
    tsumo = d["is_tsumogiri"].to_list()
    # 染色代理: 手牌中数量最多的花色(>=5)
    proxy = []
    for h in hand_suits:
        cnts = [sum(h[0:9]), sum(h[9:18]), sum(h[18:27])]
        mx = max(cnts)
        proxy.append(mx)  # 最大花色密度
    d = d.with_columns(pl.Series("_max_suit_density", proxy, dtype=pl.Int8))
    dye = d.filter(pl.col("_max_suit_density") >= 5)
    n_dye = dye.height
    # 溢出状态: 当前切的牌是否是"最大密度花色"的数牌
    overflow = defaultdict(lambda: [0, 0])  # status -> [n, tenpai]
    for h, t, tg, den in zip(dye["hand_34"].to_list(), dye["tile"].to_list(),
                              dye["is_tsumogiri"].to_list(), dye["_max_suit_density"].to_list()):
        # 找最大花色
        cnts = [sum(h[0:9]), sum(h[9:18]), sum(h[18:27])]
        mx_suit = cnts.index(max(cnts))
        is_ov = 0 <= t < 27 and t // 9 == mx_suit
        if not is_ov:
            status = "无溢出"
        elif tg == 0:
            status = "手切溢出"
        else:
            status = "摸切溢出"
        overflow[status][0] += 1
        overflow[status][1] += int(dye["is_tenpai"][0]) if False else 0
    # 用位置索引重算 tenpai
    tp_list = dye["is_tenpai"].to_list()
    out = []
    for status, (n, _) in overflow.items():
        out.append({"状态": status, "n": n, "听牌率": None})
    # 精确重算
    out2 = []
    idx = 0
    for h, t, tg, den, tp in zip(dye["hand_34"].to_list(), dye["tile"].to_list(),
                                 dye["is_tsumogiri"].to_list(), dye["_max_suit_density"].to_list(),
                                 tp_list):
        cnts = [sum(h[0:9]), sum(h[9:18]), sum(h[18:27])]
        mx_suit = cnts.index(max(cnts))
        is_ov = 0 <= t < 27 and t // 9 == mx_suit
        if not is_ov:
            status = "无溢出"
        elif tg == 0:
            status = "手切溢出"
        else:
            status = "摸切溢出"
        rec = out2[0] if False else None
    # 简化重算
    stat = defaultdict(lambda: [0, 0])
    for h, t, tg, tp in zip(dye["hand_34"].to_list(), dye["tile"].to_list(),
                            dye["is_tsumogiri"].to_list(), tp_list):
        cnts = [sum(h[0:9]), sum(h[9:18]), sum(h[18:27])]
        mx_suit = cnts.index(max(cnts))
        is_ov = 0 <= t < 27 and t // 9 == mx_suit
        if not is_ov:
            status = "无溢出"
        elif tg == 0:
            status = "手切溢出"
        else:
            status = "摸切溢出"
        stat[status][0] += 1
        stat[status][1] += int(tp)
    out_final = [{"状态": k, "n": v[0], "听牌率": pct(v[1], v[0])} for k, v in stat.items()]
    return {"id": "V2", "问题": "染手代理(手牌花色>=5)×溢出状态→听牌率", "状态": "OK",
            "data": {"染手代理行数": n_dye, "分组": out_final},
            "elapsed_s": round(time.time() - t0, 2)}


# ─── V3: 溢出状态 × 最终和率 ───

def v3(df: pl.DataFrame) -> dict:
    t0 = time.time()
    d = df.filter(pl.col("furo_count") >= 1)
    tp_list = d["is_tenpai"].to_list()
    kr_list = d["kyoku_result"].to_list()
    stat = defaultdict(lambda: [0, 0])  # status -> [n, win]
    seen = set()  # (game,round,actor,status) 结局已计 (局级, 2026-08-04)
    for h, t, tg, tp, kr, gid, rid, act in zip(
            d["hand_34"].to_list(), d["tile"].to_list(),
            d["is_tsumogiri"].to_list(), tp_list, kr_list,
            d["game_id"].to_list(), d["round_idx"].to_list(), d["actor"].to_list()):
        cnts = [sum(h[0:9]), sum(h[9:18]), sum(h[18:27])]
        if max(cnts) < 5:
            continue  # 仅染手代理
        mx_suit = cnts.index(max(cnts))
        is_ov = 0 <= t < 27 and t // 9 == mx_suit
        if not is_ov:
            status = "无溢出"
        elif tg == 0:
            status = "手切溢出"
        else:
            status = "摸切溢出"
        stat[status][0] += 1
        key = (gid, rid, act, status)
        if key not in seen:
            seen.add(key)
            stat[status][1] += int(kr in (0, 1))
    out = [{"状态": k, "n": v[0], "和率(局级)": pct(v[1], v[0])} for k, v in stat.items()]
    return {"id": "V3", "问题": "溢出状态×最终和率(判断有效性, 2026-08-04 和率改局级)", "状态": "OK",
            "data": out, "elapsed_s": round(time.time() - t0, 2)}


QUERIES = [g1a, g1b, g1c, v1, v2, v3]


def main() -> None:
    df, td = load()
    print(f"loaded {df.height:,} rows", flush=True)
    results = []
    for fn in QUERIES:
        try:
            r = fn(df, td) if fn in (g1a, g1b, g1c) else fn(df)
        except Exception as exc:
            import traceback
            r = {"id": fn.__name__, "状态": "ERROR", "error": repr(exc),
                 "trace": traceback.format_exc()[-500:]}
        results.append(r)
        print(json.dumps(r, ensure_ascii=False, indent=2))
    Path(r"D:\tenhoulib\pattern_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nsaved pattern_results.json")


if __name__ == "__main__":
    main()
