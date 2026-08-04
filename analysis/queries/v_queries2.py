"""v_queries2.py — V族深化：副露大类识别(V4) + 后附验证(V5/V6)

基于用户领域知识（BASELINE_QUERIES.md）:
  副露四类: 食断/役牌/染手/对对
  后附强特征: ①第一副露客风字牌/带幺九→否定先付和断幺 ②牌河或第二副露→否定染手/对对

现有列可识别:
  - 役牌流:  furo_yakuhai >= 1
  - 客风流:  furo_pon_honor - furo_yakuhai >= 1 且 yakuhai == 0  (碰非役字牌)
  - 食断流:  furo_yakuhai == 0 且 furo_pon_honor == 0           (全数牌副露)
  - 染手代理: 手牌某花色 >= 5
  - 对对近似: furo_pon_honor >= 2 (至少2个碰, 字牌碰多)
无法识别(需副露序列列): 副露牌面幺九、第一/第二副露的精确内容
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path

import polars as pl

V3 = Path(r"D:\tenhoulib\v3_200k_v2.parquet")

V_COLS = ["game_id", "round_idx", "actor", "furo_count", "furo_yakuhai", "furo_pon_honor",
          "hand_34", "is_tenpai", "kyoku_result", "kyoku_pt_delta", "kawa_visible",
          "furo_seq", "tile", "is_tsumogiri"]


def pct(hit: int, n: int) -> float:
    return round(hit / n * 100, 2) if n else None


def load() -> pl.DataFrame:
    # 2026-08-04: 半庄级均匀抽样 (全年分布) + 列白名单 — 见 sample_load.py
    from sample_load import scan_sample
    return scan_sample(str(V3), cols=V_COLS, step=30)


# ─── V4: 副露大类识别 → 听牌率/和率/收支 映射表 ───

def v4(df: pl.DataFrame) -> dict:
    t0 = time.time()
    d = df.filter(pl.col("furo_count") >= 1)
    hands = d["hand_34"].to_list()
    tp = d["is_tenpai"].to_list()
    kr = d["kyoku_result"].to_list()
    fpt = d["kyoku_pt_delta"].to_list()
    yk = d["furo_yakuhai"].to_list()
    ph = d["furo_pon_honor"].to_list()
    gids = d["game_id"].to_list()
    rids = d["round_idx"].to_list()
    actors = d["actor"].to_list()

    classes = defaultdict(lambda: [0, 0, 0, 0, 0.0])  # cls -> [n, tenpai, win, dealt, pt_sum]
    seen_res = set()  # (game,round,actor) 结局已计 (局级去重, 2026-08-04)
    for i, (h, t, k, p, y, pn) in enumerate(zip(hands, tp, kr, fpt, yk, ph)):
        cnts = [sum(h[0:9]), sum(h[9:18]), sum(h[18:27])]
        mx = max(cnts)
        if y >= 1:
            cls = "役牌流"
        elif pn - y >= 1:
            cls = "客风流(后附特征)"
        elif mx >= 5:
            cls = "染手代理"
        elif pn >= 2:
            cls = "对对近似"
        else:
            cls = "食断流"
        classes[cls][0] += 1
        classes[cls][1] += int(t)
        key = (gids[i], rids[i], actors[i])
        if key not in seen_res:
            seen_res.add(key)
            classes[cls][2] += int(k in (0, 1))
            classes[cls][3] += int(k == 2)
        if p is not None:
            classes[cls][4] += p

    out = []
    for cls, (n, tenpai, win, dealt, pts) in sorted(classes.items(), key=lambda x: -x[1][0]):
        out.append({"副露类": cls, "n": n, "听牌率": pct(tenpai, n),
                    "和率": pct(win, n), "放铳率": pct(dealt, n),
                    "平均局收支": round(pts / n, 1) if n else None})
    return {"id": "V4", "问题": "副露大类识别→听牌率/和率/收支映射", "状态": "OK",
            "data": out, "elapsed_s": round(time.time() - t0, 2)}


# ─── V5: 客风碰(后附特征①) → 手牌幺九含量/花色密度(否定断幺/染手验证) ───

def v5(df: pl.DataFrame) -> dict:
    t0 = time.time()
    d = df.filter((pl.col("furo_count") >= 1) & (pl.col("furo_yakuhai") == 0)
                  & (pl.col("furo_pon_honor") >= 1))  # 客风碰: 碰字牌但非役牌
    n = d.height
    hands = d["hand_34"].to_list()
    tp = d["is_tenpai"].to_list()

    # 手牌幺九含量 (否定断幺?): 幺九 = 1/9/字牌
    yaochu_mean = 0.0
    pair_yaochu = 0
    dye_rate = 0
    for h in hands:
        yaochu = (h[0] + h[8] + h[9] + h[17] + h[18] + h[26] + sum(h[27:34]))
        yaochu_mean += yaochu
        pair_yaochu += sum(1 for i in (0, 8, 9, 17, 18, 26) if h[i] >= 2)
        cnts = [sum(h[0:9]), sum(h[9:18]), sum(h[18:27])]
        if max(cnts) >= 5:
            dye_rate += 1

    # 对比: 役牌碰玩家的手牌
    d2 = df.filter((pl.col("furo_count") >= 1) & (pl.col("furo_yakuhai") >= 1))
    h2 = d2["hand_34"].to_list()
    y2 = 0.0
    for h in h2:
        y2 += h[0] + h[8] + h[9] + h[17] + h[18] + h[26] + sum(h[27:34])
    tp2 = d2["is_tenpai"].to_list()

    return {"id": "V5", "问题": "客风碰(后附特征①)→手牌幺九含量/染手率", "状态": "OK",
            "data": {
                "客风碰": {"n": n, "平均手牌幺九数": round(yaochu_mean / n, 2) if n else None,
                         "含幺九对率": pct(pair_yaochu, n), "染手代理率": pct(dye_rate, n),
                         "听牌率": pct(int(sum(tp)), n)},
                "役牌碰对比": {"n": d2.height, "平均手牌幺九数": round(y2 / d2.height, 2) if d2.height else None,
                            "听牌率": pct(int(sum(tp2)), d2.height)},
                "解读": "客风碰=后附特征: 若手牌幺九多→否定断幺(符合); 染手率低→客风碰玩家多非染手(待第二副露/牌河再判)",
            }, "elapsed_s": round(time.time() - t0, 2)}


# ─── V6: 客风碰 + 溢出(牌河) → 染手排除验证 (后附特征②的牌河部分) ───

def v6(df: pl.DataFrame) -> dict:
    t0 = time.time()
    d = df.filter((pl.col("furo_count") >= 1) & (pl.col("furo_yakuhai") == 0)
                  & (pl.col("furo_pon_honor") >= 1) & (pl.col("tile") >= 0))
    hands = d["hand_34"].to_list()
    tiles = d["tile"].to_list()
    tg = d["is_tsumogiri"].to_list()
    tp = d["is_tenpai"].to_list()

    # 染手代理色(手牌最大花色) 与 溢出(切过该色数牌) 的关系
    stat = defaultdict(lambda: [0, 0])
    for h, t, g, tenpai in zip(hands, tiles, tg, tp):
        cnts = [sum(h[0:9]), sum(h[9:18]), sum(h[18:27])]
        mx = max(cnts)
        if mx < 4:
            continue  # 无染手倾向
        mx_suit = cnts.index(mx)
        is_ov = 0 <= t < 27 and t // 9 == mx_suit
        if is_ov:
            status = "切出染手代理色(溢出)"
        else:
            status = "未切染手代理色"
        stat[status][0] += 1
        stat[status][1] += int(tenpai)

    out = [{"状态": k, "n": v[0], "听牌率": pct(v[1], v[0])} for k, v in stat.items()]
    return {"id": "V6", "问题": "客风碰玩家: 染手代理色溢出 vs 未溢出→听牌率", "状态": "OK",
            "data": out,
            "解读": "后附特征②: 客风碰+牌河切出染手色→否定染手; 此处用代理色溢出近似",
            "elapsed_s": round(time.time() - t0, 2)}


QUERIES = [v4, v5, v6]


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
    Path(r"D:\tenhoulib\v_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nsaved v_results.json")


if __name__ == "__main__":
    main()
