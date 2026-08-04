"""Q1 v2 (精确定义): 先制立直 + 听牌恰为 {1x,4x} 两面(x∈m/p/s, 合并) + 平和 + dora1
场面: 已见 1x = 3 且 已见 4x = 0 (可和数: 1剩1枚, 4剩4枚)
输出: 和率/自摸占比/收支/自亲, 含对照组合。
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"D:\tenhoulib")
import polars as pl
from yaku import is_pinfu_shape

# 列白名单 (避免 1 亿行全载 OOM; 200K 数据 14 列 ≈ 1GB)
df = pl.read_parquet(r"D:\tenhoulib\v3_200k_v2.parquet", columns=[
    "game_id", "round_idx", "actor", "is_sengenhai", "waits_mask", "wait_type_mask",
    "dora_count", "hand_34", "bakaze", "seat_wind", "kawa_visible",
    "kyoku_result", "win_tile", "is_oya", "kyoku_pt_delta",
])

# 先制立直
s = df.filter(pl.col("is_sengenhai") == 1)
s = s.with_columns(pl.col("is_sengenhai").shift(1).over(["game_id", "round_idx"]).fill_null(0).alias("_ps"))
sente = s.filter(pl.col("_ps") == 0)
print(f"先制立直: {sente.height:,}", flush=True)


def exact_14_base(mask: int) -> int:
    """waits 恰为 {1x,4x} → 返回花色 base (0/9/18); 否则 -1。"""
    for base in (0, 9, 18):
        if mask == (1 << base) | (1 << (base + 3)):
            return base
    return -1


# 恰听 {1x,4x}
masks = sente["waits_mask"].to_list()
bases = [exact_14_base(m) for m in masks]
sente = sente.with_columns(pl.Series("_base", bases, dtype=pl.Int8))
d = sente.filter(pl.col("_base") >= 0)
print(f"恰听14两面(三花色): {d.height:,}", flush=True)

# + 两面位(天然满足) + dora1 + 平和(非役雀头)
d2 = d.filter(pl.col("dora_count") == 1)
pinfu = []
for h, wm, wt, bz, sw in zip(d2["hand_34"].to_list(), d2["waits_mask"].to_list(),
                             d2["wait_type_mask"].to_list(), d2["bakaze"].to_list(),
                             d2["seat_wind"].to_list()):
    pinfu.append(int(is_pinfu_shape(h, wm, wt, int(bz), int(sw))))
d2 = d2.with_columns(pl.Series("_pinfu", pinfu, dtype=pl.Int8)).filter(pl.col("_pinfu") == 1)
print(f"+ dora1 + 平和: {d2.height:,}", flush=True)

# 已见计数: 1x = kawa_visible[base], 4x = kawa_visible[base+3]
kv = d2["kawa_visible"].to_list()
bs = d2["_base"].to_list()
vis1 = [k[b] for k, b in zip(kv, bs)]
vis4 = [k[b + 3] for k, b in zip(kv, bs)]
d2 = d2.with_columns(pl.Series("_vis1", vis1, dtype=pl.Int8),
                     pl.Series("_vis4", vis4, dtype=pl.Int8))

print("\n=== 已见分布 (1已见 × 4已见) ===")
dist = d2.group_by(["_vis1", "_vis4"]).len().sort(["_vis1", "_vis4"])
for r in dist.to_dicts():
    print(f"  1已见={r['_vis1']} 4已见={r['_vis4']}: n={r['len']}")


def report(sub, label):
    n = sub.height
    if n < 10:
        print(f"  {label}: n={n} (样本不足)")
        return
    kr = sub["kyoku_result"]
    win = int(((kr == 0) | (kr == 1)).sum())
    tsumo = int((kr == 1).sum())
    wsub = sub.filter(pl.col("win_tile") >= 0)
    wt = wsub["win_tile"].to_list()
    c14 = sum(1 for t, b in zip(wt, wsub["_base"].to_list()) if t in (b, b + 3))
    oya = sub.filter(pl.col("is_oya") == 1)
    ko = sub.filter(pl.col("is_oya") == 0)
    print(f"  {label}: n={n:,} | 和率={win/n*100:.1f}% | 自摸占比={tsumo/max(win,1)*100:.1f}%"
          f" | 收支={sub['kyoku_pt_delta'].mean():,.0f}"
          f" | 自亲和率={int(((oya['kyoku_result']==0)|(oya['kyoku_result']==1)).sum())/oya.height*100:.1f}%(n={oya.height})"
          f" | 子家和率={int(((ko['kyoku_result']==0)|(ko['kyoku_result']==1)).sum())/ko.height*100:.1f}%(n={ko.height})"
          f" | 和牌中14占比={c14/max(len(wt),1)*100:.0f}%")


print("\n=== 主结果: 1现3 & 4现0 (可和数 1枚+4枚) ===")
report(d2.filter((pl.col("_vis1") == 3) & (pl.col("_vis4") == 0)), "1现3/4现0")

print("\n=== 对照组合 ===")
report(d2.filter((pl.col("_vis1") == 0) & (pl.col("_vis4") == 0)), "全生张(1现0/4现0)")
report(d2.filter((pl.col("_vis1") == 3) & (pl.col("_vis4") == 3)), "1现3/4现3")
report(d2.filter((pl.col("_vis1") == 2) & (pl.col("_vis4") == 0)), "1现2/4现0")
report(d2.filter((pl.col("_vis1") == 1) & (pl.col("_vis4") == 0)), "1现1/4现0")
report(d2, "全部(不限已见)")
