"""赤牌宣言立直分析: 宣言牌为赤牌时的听牌分布 + 最危险牌。"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import polars as pl
from collections import Counter

# 列白名单: 避免 1 亿行全载 OOM (7 列 ≈ 1GB)
df = pl.read_parquet(r"D:\tenhoulib\v3_200k_v2.parquet", columns=[
    "is_sengenhai", "is_aka", "tile", "wait_type_mask", "waits_mask",
    "kyoku_result", "kyoku_pt_delta",
])
print("rows:", f"{df.height:,}")

TILE_NAMES = ['1m','2m','3m','4m','5m','6m','7m','8m','9m',
              '1p','2p','3p','4p','5p','6p','7p','8p','9p',
              '1s','2s','3s','4s','5s','6s','7s','8s','9s',
              'E','S','W','N','P','F','C']

aka = df.filter((pl.col("is_sengenhai") == 1) & (pl.col("is_aka") == 1))
normal = df.filter((pl.col("is_sengenhai") == 1) & (pl.col("is_aka") == 0))
print(f"赤牌宣言立直: {aka.height:,} | 普通宣言立直: {normal.height:,}")
print(f"赤牌宣言占比: {aka.height/(aka.height+normal.height)*100:.3f}%")
print(f"赤牌宣言分布: ", aka["tile"].value_counts().sort("tile").to_dicts())

# ── 听牌形分布对比 ──
print("\n=== 听牌形分布 (waits_mask 中有该类型听牌的比例) ===")
wt = {"两面": 1, "坎张": 2, "边张": 4, "单骑": 8, "双碰": 16}
for label, sub in (("赤牌宣言", aka), ("普通宣言", normal)):
    n = sub.height
    dist = {}
    for name, bit in wt.items():
        dist[name] = round(float(((sub["wait_type_mask"] & bit) > 0).mean()) * 100, 2)
    print(f"{label}: n={n} | {dist}")

# 听牌数
print(f"\n赤牌宣言平均听牌数: {aka['wait_type_mask'].map_elements(lambda m: bin(m).count('1') if m else 0, return_dtype=pl.Int32).mean():.2f}")
print(f"普通宣言平均听牌数: {normal['wait_type_mask'].map_elements(lambda m: bin(m).count('1') if m else 0, return_dtype=pl.Int32).mean():.2f}")

# ── 最危险牌: 赤牌宣言听牌中出现频率最高的牌 (waits_mask 位) ──
print("\n=== 赤牌宣言听牌中最常出现的牌 (waits 频率) ===")
def waits_freq(sub, label, top_n=10):
    cnt = Counter()
    n = sub.height
    for mask in sub["waits_mask"].to_list():
        m = mask
        i = 0
        while m:
            if m & 1:
                cnt[i] += 1
            m >>= 1
            i += 1
    rows = []
    for idx, c in cnt.most_common(top_n):
        rows.append({"牌": TILE_NAMES[idx], "听牌局面数": c, "占比%": round(c / n * 100, 2)})
    return rows

aka_freq = waits_freq(aka, "赤牌宣言")
print("赤牌宣言 TOP10 危险牌:")
for r in aka_freq:
    print(f"  {r['牌']}: {r['听牌局面数']} 局面 ({r['占比%']}%)")

# 普通宣言对比 (同位置)
norm_freq = waits_freq(normal, "普通宣言")
print("\n普通宣言 TOP10:")
for r in norm_freq:
    print(f"  {r['牌']}: {r['听牌局面数']} 局面 ({r['占比%']}%)")

# 相对差异: 赤牌宣言 vs 普通宣言 中频率升高的牌
cnt_aka = Counter()
for mask in aka["waits_mask"].to_list():
    m, i = mask, 0
    while m:
        if m & 1: cnt_aka[i] += 1
        m >>= 1; i += 1
cnt_norm = Counter()
for mask in normal["waits_mask"].to_list():
    m, i = mask, 0
    while m:
        if m & 1: cnt_norm[i] += 1
        m >>= 1; i += 1
na, nn = len(aka), len(normal)
print("\n=== 赤牌宣言相对升幅最大的牌 (占比差) ===")
diffs = []
for i in range(34):
    ra = cnt_aka.get(i, 0) / na
    rn = cnt_norm.get(i, 0) / nn
    diffs.append((TILE_NAMES[i], ra, rn, ra - rn))
for name, ra, rn, d in sorted(diffs, key=lambda x: -x[3])[:8]:
    print(f"  {name}: 赤牌宣言听牌占 {ra*100:.2f}% vs 普通 {rn*100:.2f}% (Δ{d*100:+.2f}pp)")

# 和率/收支对比
print("\n=== 赤牌宣言 vs 普通宣言 结果 ===")
for label, sub in (("赤牌宣言", aka), ("普通宣言", normal)):
    n = sub.height
    kr = sub["kyoku_result"]
    win = int(((kr == 0) | (kr == 1)).sum())
    tsumo = int((kr == 1).sum())
    print(f"{label}: 和率 {win/n*100:.1f}% | 自摸占比 {tsumo/max(win,1)*100:.1f}% | 平均收支 {sub['kyoku_pt_delta'].mean():.0f}")
