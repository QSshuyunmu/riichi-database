"""赤牌宣言立直: 按赤5m/5p/5s分别分析同色听牌危险度。"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import polars as pl
from collections import Counter

# 列白名单: 避免 1 亿行全载 OOM
df = pl.read_parquet(r"D:\tenhoulib\v3_200k_v2.parquet", columns=[
    "is_sengenhai", "is_aka", "tile", "waits_mask",
])

TILE_NAMES = ['1m','2m','3m','4m','5m','6m','7m','8m','9m',
              '1p','2p','3p','4p','5p','6p','7p','8p','9p',
              '1s','2s','3s','4s','5s','6s','7s','8s','9s',
              'E','S','W','N','P','F','C']

# 赤牌 tile idx: 5mr=4, 5pr=13, 5sr=22
AKA_GROUPS = {4: ("赤5m", 0, "m"), 13: ("赤5p", 9, "p"), 22: ("赤5s", 18, "s")}
# 普通宣言同色基准
normal = df.filter((pl.col("is_sengenhai") == 1) & (pl.col("is_aka") == 0))
n_normal = normal.height

def suit_waits_freq(sub, suit_base):
    """统计该花色内每个牌的听牌局面占比。"""
    cnt = Counter()
    n = sub.height
    for mask in sub["waits_mask"].to_list():
        m = mask >> suit_base
        i = 0
        while m:
            if m & 1:
                cnt[i] += 1
            m >>= 1
            i += 1
    return cnt, n

def fmt(tile_idx):
    return TILE_NAMES[tile_idx]

# 普通宣言各花色基准
norm_by_suit = {}
for base, label in ((0, "m"), (9, "p"), (18, "s")):
    cnt, n = suit_waits_freq(normal, base)
    norm_by_suit[base] = {i: cnt.get(i, 0) / n for i in range(9)}

print(f"普通宣言立直: {n_normal:,}\n")
for tile_idx, (label, suit_base, suit) in AKA_GROUPS.items():
    sub = df.filter((pl.col("is_sengenhai") == 1) & (pl.col("is_aka") == 1) & (pl.col("tile") == tile_idx))
    n = sub.height
    if n == 0:
        continue
    cnt, _ = suit_waits_freq(sub, suit_base)
    print(f"===== 宣言牌 {label} (n={n}) — {suit} 色同色危险度 =====")
    # 同色内每个牌的听牌占比 + vs 普通宣言同色差
    rows = []
    for i in range(9):
        ra = cnt.get(i, 0) / n
        rn = norm_by_suit[suit_base][i]
        rows.append((fmt(suit_base + i), ra, rn, ra - rn))
    rows.sort(key=lambda x: -x[1])
    print(f"  {'牌':>4} {'赤牌宣言听牌%':>12} {'普通宣言%':>10} {'Δpp':>8}")
    for name, ra, rn, d in rows:
        mark = " ◀" if d > 1.0 else ""
        print(f"  {name:>4} {ra*100:>11.2f}% {rn*100:>9.2f}% {d*100:>+7.2f}{mark}")
    # 危险度排序结论
    top3 = [r[0] for r in sorted(rows, key=lambda x: -x[3])[:3]]
    print(f"  → 相对普通宣言升幅最大: {', '.join(top3)}\n")
