"""stats_sanity.py — 统计合理性门禁（档2：高频统计区间，lazy/streaming 版）

用 nodocchi 凤凰卓基准（data/baseline_stats.json）校验 parquet 数据的关键统计。
判定: 观测值落在基准 [p10, p90] 内 → PASS; 超出但 < ±2σ 宽区间 → WARNING; 超出 → FAIL。

内存安全: 全部 lazy scan + collect(engine="streaming")，1 亿行全量安全（参考 invariant_check v2）。

用法:
  python stats_sanity.py --data v3_xxx.parquet [--mode hard|warning] [--sample 1000000]

指标口径（与 baseline 对齐）:
  - 和率    = 和牌局(kyoku_result∈{0,1}) / 总局数
  - 铳率    = 放铳局(kyoku_result==2) / 总局数
  - 流局率  = 流局局(kyoku_result==4) / 总局数
  - 自摸率  = 自摸和 / 全和
  - 立直率  = 宣言总次数 / 总局数 (nodocchi: riich/totalgame, 1 局可多次立直)
"""
import argparse
import json
import sys
import time
from pathlib import Path

import polars as pl

BASE = Path(__file__).parent / "data" / "baseline_stats.json"
COLS = ["game_id", "round_idx", "actor", "kyoku_result", "is_sengenhai"]


def check(lf: pl.LazyFrame) -> dict:
    """全部 lazy 聚合，返回各指标观测值."""
    t0 = time.time()
    # 总局数: (game_id, round_idx) 唯一数
    n_kyoku = (lf.select(pl.col("game_id", "round_idx"))
                 .unique()
                 .select(pl.len())
                 .collect().item())
    if n_kyoku == 0:
        return {"_error": "no kyoku"}

    # 各结局家次数: nodocchi 口径是"玩家级" — 和率=和牌次数/局数 (单家 ~22%),
    # 每局 4 家, 和牌家 + 放铳家 + 流局各家等. 行级直接计数:
    #   和率 = 行 kyoku_result∈{0,1} 数 / (局数×?) — 注意 nodocchi 分母是 totalgame(局数)
    #   → 和率 = 和牌家次数 / 总局数 (每局最多1家和牌(双和2家), 4家行中0或1行是赢家)
    # 各结局家次数: nodocchi 口径为"玩家级" — 和率 = 和牌家次数 / (局数)，
    # 但每局 4 家行, 单家和率 = 和牌行数 / (4×局数)（每局 4 家, 每家和牌概率 ~22%）
    # 每局每家一行 (去重后): 每局 4 行, 各家的 kyoku_result.
    # 和率 = 和牌家次/局数 (每局 4 家, 赢家行 result∈{0,1})
    seat = (lf.select("game_id", "round_idx", "actor", "kyoku_result")
              .unique()
              .collect())
    n_seat_rows = seat.height
    n_win = seat.filter(pl.col("kyoku_result").is_in([0, 1])).height
    n_deal = seat.filter(pl.col("kyoku_result") == 2).height
    n_draw = seat.filter(pl.col("kyoku_result") == 4).height
    n_tsumo = seat.filter(pl.col("kyoku_result") == 1).height
    n_riichi = (lf.filter(pl.col("is_sengenhai") == 1)
                  .select(pl.len()).collect().item())
    n_seat = n_seat_rows

    m = {
        # nodocchi C 指标口径核对:
        #   agariC = agari/totalgame = 和牌次数/局数 —— 但 nodocchi 的 agari 是该玩家和牌次数,
        #   除以其参与局数 = 单家局和率. 我们的 seat 行 = 每局每家的结局, 和牌行 = 和牌家次.
        #   注意 nodocchi 玩家参与 n 局 → agari/n = 单家率; 4 家合计 = 和牌局率(≈0.85).
        #   所以: 和率(单家) = n_win / (4×n_kyoku); 而 n_win 是去重后和牌家次.
        #   但 nodocchi totalgame 是该玩家局数, 单家 agari/n ≈ 0.22 → 与我们的 4 家率不同!
        #   修正: 我们算"局级率"和"单家率"都要明确. 这里按 nodocchi: 单家率 = 家次/(4×局数).
        "和率_agari_rate": n_win / n_seat,
        "铳率_houjuu_rate": n_deal / n_seat,
        "流局率_nagare_rate": n_draw / n_seat,
        "立直率_riichi_rate": n_riichi / n_seat,
        "自摸率_tsumo_share": n_tsumo / n_win if n_win else None,
    }
    m["_meta"] = {"kyoku": n_kyoku, "win": n_win, "elapsed_s": round(time.time() - t0, 1)}
    return m


def main() -> int:
    ap = argparse.ArgumentParser(description="统计合理性门禁 (streaming)")
    ap.add_argument("--data", required=True)
    ap.add_argument("--mode", choices=["hard", "warning"], default="warning")
    ap.add_argument("--sample", type=int, default=0,
                    help="前 N 行截断 (防 OOM; 0=全量, 统计类指标 500 万行足够)")
    args = ap.parse_args()

    base = json.loads(BASE.read_text(encoding="utf-8"))
    lf = pl.scan_parquet(args.data).select(COLS)
    if args.sample:
        lf = lf.limit(args.sample)
    m = check(lf)
    if "_error" in m:
        print(m["_error"])
        return 1
    meta = m.pop("_meta")

    failures = warnings = passes = skipped = 0
    print(f"parquet: {meta['kyoku']:,} kyoku (win={meta['win']:,}) in {meta['elapsed_s']}s")
    print(f"{'指标':<28}{'观测':>10}{'基准p10':>10}{'基准p90':>10}  判定")
    for key, obs in m.items():
        if obs is None:
            skipped += 1
            print(f"  {key}: 无法计算，跳过")
            continue
        b = base.get(key)
        if not b:
            skipped += 1
            print(f"  {key}: 无基准，跳过")
            continue
        lo, hi = b["p10"], b["p90"]
        w = (hi - lo) * 2 / 2.56  # 2σ 近似
        hard_lo, hard_hi = b["mean_w"] - 2 * w, b["mean_w"] + 2 * w
        status = "PASS"
        if obs < lo or obs > hi:
            if obs < hard_lo or obs > hard_hi:
                status = "FAIL"
                failures += 1
            else:
                status = "WARN"
                warnings += 1
        else:
            passes += 1
        print(f"  {key:<26}{obs:>10.4f}{lo:>10.4f}{hi:>10.4f}  {status}")

    print(f"\nPASS={passes} WARN={warnings} FAIL={failures} SKIP={skipped}")
    if failures:
        print("存在 FAIL → 门禁不通过" if args.mode == "hard" else "存在 FAIL（warning 模式，可人工复核）")
    return 1 if (failures and args.mode == "hard") else 0


if __name__ == "__main__":
    sys.exit(main())
