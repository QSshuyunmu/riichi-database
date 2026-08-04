"""sample_load.py — 查询公共 load 工具：半庄级均匀抽样（局内完整 + 时间代表）

问题: 行级 limit(5M) 只覆盖前 17 天; 行级取模抽样破坏局内完整性
方案: 半庄级均匀抽样 — 按每个半庄的起始行号取模 (step), 选中的半庄取全部行
      → 局内事件完整 (DQ/DI 等按局聚合查询可用) + 覆盖全年半庄
"""
from __future__ import annotations

import polars as pl


def scan_sample(path: str, cols: list[str] | None = None, step: int = 20,
                max_rows: int | None = None) -> pl.DataFrame:
    """半庄级均匀抽样: 按半庄起始 _seq 取模, 选中的半庄取全部行.

    step=20 → 约 1/20 半庄 ≈ 500 万行 (200K 数据). 含全局序号 _seq (单调, 供时点判定).
    """
    lf = pl.scan_parquet(path)
    if cols:
        lf = lf.select(cols)
    lf = lf.with_row_index("_seq")
    # 每个半庄的起始行号
    first = (lf.group_by("game_id")
               .agg(pl.col("_seq").min().alias("_first"))
               .filter(pl.col("_first") % step == 0))
    # 选中半庄的全部行
    df = lf.join(first, on="game_id", how="inner").collect(engine="streaming")
    if max_rows and df.height > max_rows:
        # 兜底: 若超过目标行数 (step 偏小), 用行级截断 (仅极端情况)
        df = df.head(max_rows)
    return df
