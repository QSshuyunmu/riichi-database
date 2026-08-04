"""furo_seq 验证: 真染手 vs 伪染手 + 后附第一副露 + 全带系

利用新列 furo_seq (副露序列 [type,tile,...]):
  V7  真染手(副露全同色) vs 伪染手(副露杂色但手牌集中) → 听牌率/和率
  V8  后附第一副露: 客风字牌 → 手役方向 (后续副露/手牌)
  V9  全带系: 副露含幺九 (副露牌面 1/9/字)
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
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


def furo_pairs(seq: list) -> list:
    """furo_seq -> [(type, tile), ...]"""
    return [(seq[i], seq[i + 1]) for i in range(0, len(seq), 2)]


def v7(df: pl.DataFrame) -> dict:
    """真染手 vs 伪染手: 副露花色 vs 手牌花色。"""
    t0 = time.time()
    d = df.filter(pl.col("furo_count") >= 2)
    stat = defaultdict(lambda: [0, 0, 0])  # cls -> [n, tenpai, win]
    seen = set()  # (game,round,actor) 结局已计 (局级, 2026-08-04)
    for seq, h, tp, kr, gid, rid, act in zip(d["furo_seq"].to_list(), d["hand_34"].to_list(),
                              d["is_tenpai"].to_list(), d["kyoku_result"].to_list(),
                              d["game_id"].to_list(), d["round_idx"].to_list(), d["actor"].to_list()):
        pairs = furo_pairs(seq)
        suits = set()
        for typ, tile in pairs:
            if 0 <= tile < 27:
                suits.add(tile // 9)
        if len(suits) == 1:
            cls = "真染手(副露全同色)"
        elif len(suits) >= 2:
            # 伪染手: 副露杂色但手牌集中
            cnts = [sum(h[0:9]), sum(h[9:18]), sum(h[18:27])]
            if max(cnts) >= 5:
                cls = "伪染手(副露杂色但手牌集中)"
            else:
                cls = "普通副露"
        else:
            cls = "字牌副露"
        stat[cls][0] += 1
        stat[cls][1] += int(tp)
        key = (gid, rid, act, cls)
        if key not in seen:
            seen.add(key)
            stat[cls][2] += int(kr in (0, 1))
    out = [{"类": k, "n": v[0], "听牌率": pct(v[1], v[0]), "和率(局级)": pct(v[2], v[0])}
           for k, v in stat.items()]
    return {"id": "V7", "问题": "真染手 vs 伪染手(精确副露花色) → 听牌率/和率", "状态": "OK",
            "data": out, "elapsed_s": round(time.time() - t0, 2)}


def v8(df: pl.DataFrame) -> dict:
    """后附第一副露: 客风字牌碰 → 后续方向。"""
    t0 = time.time()
    d = df.filter(pl.col("furo_count") >= 2)
    # 第一副露 = 客风字牌碰 (type=1, tile>=27, 非役牌)
    stat = defaultdict(lambda: [0, 0, 0])
    seen = set()
    for seq, h, tp, kr, gid, rid, act in zip(d["furo_seq"].to_list(), d["hand_34"].to_list(),
                              d["is_tenpai"].to_list(), d["kyoku_result"].to_list(),
                              d["game_id"].to_list(), d["round_idx"].to_list(), d["actor"].to_list()):
        pairs = furo_pairs(seq)
        t0t, t0i = pairs[0]
        t1t, t1i = pairs[1]
        if not (t0t == 1 and t0i >= 27):
            continue
        # 第二副露类型决定方向
        if t1t == 1:
            cls = "第二副露也是碰(对对倾向)"
        elif t1t == 0:
            cls = "第二副露是吃(染手/食断倾向)"
        else:
            cls = "第二副露是杠"
        stat[cls][0] += 1
        stat[cls][1] += int(tp)
        key = (gid, rid, act, cls)
        if key not in seen:
            seen.add(key)
            stat[cls][2] += int(kr in (0, 1))
    out = [{"类": k, "n": v[0], "听牌率": pct(v[1], v[0]), "和率(局级)": pct(v[2], v[0])}
           for k, v in stat.items()]
    return {"id": "V8", "问题": "后附: 第一副露客风碰 → 第二副露类型 → 听牌率", "状态": "OK",
            "data": out, "elapsed_s": round(time.time() - t0, 2)}


def v9(df: pl.DataFrame) -> dict:
    """全带系: 副露含幺九(1/9/字)。"""
    t0 = time.time()
    d = df.filter(pl.col("furo_count") >= 1)
    stat = defaultdict(lambda: [0, 0, 0])
    seen = set()  # (game,round,actor,cls) 结局已计 — cls 随行变, 需按 cls 去重 (2026-08-04)
    for seq, tp, kr, gid, rid, act in zip(d["furo_seq"].to_list(), d["is_tenpai"].to_list(),
                           d["kyoku_result"].to_list(),
                           d["game_id"].to_list(), d["round_idx"].to_list(), d["actor"].to_list()):
        pairs = furo_pairs(seq)
        has_yaochu = False
        has_mid = False
        for typ, tile in pairs:
            if 0 <= tile < 27:
                num = tile % 9
                if num in (0, 8):
                    has_yaochu = True
                else:
                    has_mid = True
            else:
                has_yaochu = True
        if has_yaochu and has_mid:
            cls = "副露混幺九+中张"
        elif has_yaochu:
            cls = "副露全幺九/字"
        elif has_mid:
            cls = "副露全中张(断幺倾向)"
        else:
            cls = "仅字牌"
        stat[cls][0] += 1
        stat[cls][1] += int(tp)
        key = (gid, rid, act, cls)
        if key not in seen:
            seen.add(key)
            stat[cls][2] += int(kr in (0, 1))
    out = [{"类": k, "n": v[0], "听牌率": pct(v[1], v[0]), "和率(局级)": pct(v[2], v[0])}
           for k, v in stat.items()]
    return {"id": "V9", "问题": "全带系: 副露幺九含量 → 听牌率/和率", "状态": "OK",
            "data": out, "elapsed_s": round(time.time() - t0, 2)}


QUERIES = [v7, v8, v9]


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
    Path(r"D:\tenhoulib\furo_seq_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nsaved furo_seq_results.json")


if __name__ == "__main__":
    main()
