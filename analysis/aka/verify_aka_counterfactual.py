"""verify_aka_counterfactual.py — 赤牌反事实验证 (v3_200k_v2)

牌理: 手里同时有可切的 0x(赤) 和 5x(普通) 时必切普通留赤 → 切赤宣言者手牌普通 5x 应显著少于切普通者.
修复前: 切赤 49.8% vs 切普通 30.8% (反牌理, 标签互换 bug)
修复后: 切赤 < 切普通 (符合牌理)
"""
import sys
sys.path.insert(0, r"D:\tenhoulib")
import polars as pl

DATA = r"D:\tenhoulib\v3_200k_v2.parquet"
AKA_CAT = {4: "5m", 13: "5p", 22: "5s"}  # is_aka=1 的 tile 类别

lf = pl.scan_parquet(DATA).select(
    "game_id", "round_idx", "actor", "turn", "tile", "is_aka", "is_sengenhai", "hand_34"
)
sengen = lf.filter(pl.col("is_sengenhai") == 1).collect()
print(f"宣言行总数: {sengen.height}")

for tile_cat, name in AKA_CAT.items():
    # 切赤宣言: is_aka=1 & tile=该类别
    aka_s = sengen.filter((pl.col("is_aka") == 1) & (pl.col("tile") == tile_cat))
    # 切普通宣言: is_aka=0 & tile=该类别
    plain_s = sengen.filter((pl.col("is_aka") == 0) & (pl.col("tile") == tile_cat))

    def hand5_count(df):
        """手牌中该类别 5x 的数量 (hand_34[tile_cat])."""
        if df.height == 0:
            return None, None
        h5 = df.select(pl.col("hand_34").list.get(tile_cat).alias("h5"))
        n = h5.height
        ge1 = h5.filter(pl.col("h5") >= 1).height
        return n, ge1 / n

    n_aka, r_aka = hand5_count(aka_s)
    n_plain, r_plain = hand5_count(plain_s)
    print(f"\n=== {name} 切赤宣言 vs 切普通宣言 ===")
    if n_aka is None:
        print(f"  切赤: n=0")
    else:
        print(f"  切赤宣言: n={n_aka:,} 手牌{name}≥1 = {r_aka:.4f} ({r_aka*100:.1f}%)")
    if n_plain is None:
        print(f"  切普通: n=0")
    else:
        print(f"  切普通宣言: n={n_plain:,} 手牌{name}≥1 = {r_plain:.4f} ({r_plain*100:.1f}%)")
    if n_aka and n_plain:
        ok = r_aka < r_plain
        print(f"  牌理判定 (切赤 < 切普通): {'✅ 符合' if ok else '❌ 反牌理!'}")
