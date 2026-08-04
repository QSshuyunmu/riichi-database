"""切赤牌宣言 vs 切同色普通5宣言: 同色数牌听牌危险度差异 (200K)。"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import polars as pl
from collections import Counter

df = pl.read_parquet(r"D:\tenhoulib\v3_200k_v2.parquet", columns=[
    "is_sengenhai", "is_aka", "tile", "waits_mask",
])

TILE_NAMES = ['1m','2m','3m','4m','5m','6m','7m','8m','9m',
              '1p','2p','3p','4p','5p','6p','7p','8p','9p',
              '1s','2s','3s','4s','5s','6s','7s','8s','9s',
              'E','S','W','N','P','F','C']

# 三花色: tile_idx(5x), suit_base
SUITS = [(4, 0, "m"), (13, 9, "p"), (22, 18, "s")]

def suit_freq(sub, base):
    cnt = Counter()
    n = sub.height
    for mask in sub["waits_mask"].to_list():
        m = mask >> base
        i = 0
        while m:
            if m & 1:
                cnt[i] += 1
            m >>= 1
            i += 1
    return cnt, n

sengen = df.filter(pl.col("is_sengenhai") == 1)
aka5 = sengen.filter(pl.col("is_aka") == 1)
norm5 = sengen.filter(pl.col("is_aka") == 0)

print("=== 切赤5x 宣言 vs 切普通5x 宣言 (同色危险度) ===\n")
for tile_idx, base, suit in SUITS:
    a = aka5.filter(pl.col("tile") == tile_idx)      # 赤5x
    b = norm5.filter(pl.col("tile") == tile_idx)     # 普通5x
    cnt_a, na = suit_freq(a, base)
    cnt_b, nb = suit_freq(b, base)
    print(f"===== {suit} 色: 赤5{suit}宣言 n={na} | 普通5{suit}宣言 n={nb} =====")
    print(f"  {'牌':>4} {'赤5宣言%':>10} {'普通5宣言%':>12} {'Δpp':>8}")
    rows = []
    for i in range(9):
        ra = cnt_a.get(i, 0) / na
        rb = cnt_b.get(i, 0) / nb
        rows.append((f"5{suit}" if i == 4 else f"{i+1}{suit}", ra, rb, (ra - rb) * 100))
    rows.sort(key=lambda x: -x[3])
    for name, ra, rb, d in rows:
        mark = " ◀" if abs(d) > 0.5 else ""
        print(f"  {name:>4} {ra*100:>9.2f}% {rb*100:>11.2f}% {d:>+7.2f}{mark}")
    top3 = [r[0] for r in sorted(rows, key=lambda x: -x[3])[:3]]
    bot3 = [r[0] for r in sorted(rows, key=lambda x: x[3])[:3]]
    print(f"  → 赤切相对升幅最大: {', '.join(top3)} | 降幅最大: {', '.join(bot3)}\n")
