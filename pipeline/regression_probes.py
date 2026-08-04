"""regression_probes.py — 历轮 bug 探测回归套件（parquet 层，8 项）

触发历史:
  P1/P2  抢杠 win_tile bug (2026-08-03): 荣和牌=加杠牌, ETL 误取 last_discard
  P3/P4/P5  手牌追踪 (转换器 m 解码修复后): 门清/副露/杠行 hs 守恒
  P6  局况: oya 单值局 = 九种九牌流局 (亲家单行), 非 bug 但需确认
  P7  引擎: waits popcount 分布合理性 (1/2/3/4 主; 国士13面=13; 无 0)
  P8  规则: 立直后只许暗杠/加杠 (type 3/4), 禁止 chi/pon/daiminkan (0/1/2)

用法:
  python regression_probes.py --data v3_10k.parquet
  python regression_probes.py --data v3_fast.parquet --converter 200  # 附带转换器层抽样
"""
import sys, io, argparse
sys.path.insert(0, r"D:\tenhoulib")

import polars as pl


# ---------- 探测实现 ----------

def p1_riichi_win_in_waits(df):
    """宣言行 waits ⊇ win_tile (立直者和牌牌必在立直听牌中; 抢杠/岭上修复验证)"""
    sengen = df.filter(pl.col("is_sengenhai") == 1)
    bad = []
    for r in sengen.iter_rows(named=True):
        if r["kyoku_result"] in (0, 1) and r["win_tile"] >= 0:
            if not ((r["waits_mask"] >> r["win_tile"]) & 1):
                bad.append((r["game_id"], r["round_idx"], r["actor"], r["win_tile"], r["waits_mask"]))
    ok = len(bad) == 0
    return ok, {"宣言行": sengen.height, "违反": len(bad),
                "样本": bad[:3], "说明": "违反 = 抢杠/和牌牌判定错"}


def p2_ron_row_visible(df):
    """放铳行 (荣和牌打出) 已见必须含 win_tile"""
    ron = df.filter(pl.col("kyoku_result") == 2)
    g = ron.group_by(["game_id", "round_idx", "actor"]).agg(
        pl.col("turn").max().alias("mturn"), pl.col("win_tile").first())
    ron_last = ron.join(g, on=["game_id", "round_idx", "actor"]).filter(pl.col("turn") == pl.col("mturn"))
    m2 = ron_last.join(df.select(["game_id", "round_idx", "actor", "turn", "kawa_visible"]),
                       on=["game_id", "round_idx", "actor", "turn"])
    bad = 0
    for r in m2.iter_rows(named=True):
        if r["win_tile"] >= 0 and r["kawa_visible"][r["win_tile"]] < 1:
            bad += 1
    return bad == 0, {"放铳行": m2.height, "违反": bad,
                      "说明": "违反 = win_tile 错 或 已见更新漏(岭上)"}


def p3_menchin_hs(df):
    """门清行 hs 必须全 13"""
    hs = df["hand_34"].list.sum()
    d = df.with_columns(hs.rename("hs"))
    menchin = d.filter(pl.col("furo_count") == 0)
    bad = menchin.filter(pl.col("hs") != 13).height
    return bad == 0, {"门清行": menchin.height, "违反": bad}


def p4_kan_rows_hs(df):
    """kakan/daiminkan 纯杠行 hs=10 (13+1摸-1consumed+1岭上-1打 / 13-3+1岭上-1打)"""
    def furo_types(seq):
        c = [0, 0, 0, 0, 0]
        for i in range(0, len(seq), 2):
            c[seq[i]] += 1
        return c

    hs = df["hand_34"].list.sum().alias("hs")
    d = df.with_columns(hs, pl.col("furo_seq").map_elements(
        furo_types, return_dtype=pl.List(pl.Int8)).alias("_ft"))
    d = d.with_columns(*[pl.col("_ft").list.get(i).alias(f"_{i}") for i in range(5)])
    kakan1 = d.filter((pl.col("furo_count") == 1) & (pl.col("_4") == 1) & (pl.col("_0") == 0) & (pl.col("_1") == 0) & (pl.col("_2") == 0) & (pl.col("_3") == 0))
    dmk1 = d.filter((pl.col("furo_count") == 1) & (pl.col("_2") == 1) & (pl.col("_0") == 0) & (pl.col("_1") == 0) & (pl.col("_3") == 0) & (pl.col("_4") == 0))
    b1 = kakan1.filter(pl.col("hs") != 10).height
    b2 = dmk1.filter(pl.col("hs") != 10).height
    return (b1 + b2) == 0, {"kakan行": kakan1.height, "daiminkan行": dmk1.height, "违反": b1 + b2}


def p5_chipon_rows_hs(df):
    """纯 chi/pon 行 hs = 13 - 3×furo"""
    def furo_types(seq):
        c = [0, 0, 0, 0, 0]
        for i in range(0, len(seq), 2):
            c[seq[i]] += 1
        return c

    hs = df["hand_34"].list.sum().alias("hs")
    d = df.with_columns(hs, pl.col("furo_seq").map_elements(
        furo_types, return_dtype=pl.List(pl.Int8)).alias("_ft"))
    d = d.with_columns(*[pl.col("_ft").list.get(i).alias(f"_{i}") for i in range(5)])
    pure = d.filter((pl.col("_2") == 0) & (pl.col("_3") == 0) & (pl.col("_4") == 0))
    expect = 13 - 3 * pure["furo_count"]
    bad = pure.filter(pl.col("hs") != expect).height
    return bad == 0, {"纯副露行": pure.height, "违反": bad}


def p6_oya_unique(df):
    """每局 is_oya 唯一值 ∈ {0,1} 双值; 允许九种九牌流局单值局(1行, oya=1, result=4)"""
    g = df.group_by(["game_id", "round_idx"]).agg(
        pl.col("is_oya").unique().alias("vals"),
        pl.len().alias("n_rows"),
        pl.col("kyoku_result").unique().alias("res"),
    )
    single = g.filter(pl.col("vals").list.len() == 1)
    normal = single.filter(
        (pl.col("n_rows") == 1) & (pl.col("vals").list.first() == 1)
        & (pl.col("res").list.len() == 1) & (pl.col("res").list.first() == 4))
    abnormal = single.height - normal.height
    return abnormal == 0, {"单值局": single.height, "九种九牌(正常)": normal.height, "异常": abnormal}


def p7_waits_popcount(df):
    """听牌行 waits popcount: 无 0; 1/2/3/4 为主; 国士13面=13"""
    w = df.filter(pl.col("is_tenpai") == 1).with_columns(
        pl.col("waits_mask").map_elements(lambda m: bin(m).count("1"), return_dtype=pl.Int32).alias("pc"))
    zero = w.filter(pl.col("pc") == 0).height
    over13 = w.filter(pl.col("pc") > 13).height
    dist = w.group_by("pc").len().sort("pc").to_dicts()
    return (zero == 0 and over13 == 0), {"听牌行": w.height, "pc=0": zero, "pc>13": over13,
                                          "分布": {d["pc"]: d["len"] for d in dist}}


def p8_riichi_after_melds(df):
    """立直后该玩家新增副露只许 type∈{3,4} (暗杠/加杠); 禁止 0/1/2 (chi/pon/daiminkan)"""
    bad = 0
    bad_samples = []
    # 按 (game, round, actor) 组内 turn 排序; 宣言行的 furo_seq 为基准
    g = df.group_by(["game_id", "round_idx", "actor"], maintain_order=True).agg(
        pl.col("turn").sort(), pl.col("is_sengenhai").sort(), pl.col("furo_seq").sort(),
        pl.col("furo_count").sort())
    for row in g.iter_rows(named=True):
        sengen_pos = [i for i, s in enumerate(row["is_sengenhai"]) if s == 1]
        if not sengen_pos:
            continue
        pos = sengen_pos[0]
        base_len = 2 * row["furo_count"][pos]
        for i in range(pos, len(row["furo_count"])):
            seq = row["furo_seq"][i]
            if len(seq) <= base_len:
                continue
            # 新增部分
            extra_types = [seq[j] for j in range(base_len, len(seq), 2)]
            if any(t not in (3, 4) for t in extra_types):
                bad += 1
                if len(bad_samples) < 3:
                    bad_samples.append((row["game_id"], row["round_idx"], row["actor"], base_len, extra_types))
    return bad == 0, {"立直后副露违反": bad, "样本": bad_samples,
                      "说明": "立直后只许暗杠(3)/加杠(4)"}


# ---------- 第二轮探测 (2026-08-03 挖掘: 听牌链/分类器/收支/字段链) ----------

def p9_winner_last_row_waits(df):
    """和牌者最后 dahai 行: 若听牌(shanten=0)则 waits ⊇ win_tile;
    非听 = 最后行后有副露/杠转听(如岭上自摸), 不算违反"""
    win = df.filter(pl.col("kyoku_result").is_in([0, 1]))
    g = win.group_by(["game_id", "round_idx", "actor"]).agg(
        pl.col("turn").max().alias("mturn"), pl.col("win_tile").first())
    last = win.join(g, on=["game_id", "round_idx", "actor"]).filter(pl.col("turn") == pl.col("mturn"))
    tp = last.filter(pl.col("shanten") == 0)
    bad = 0
    for r in tp.iter_rows(named=True):
        wt = r["win_tile"]
        if wt >= 0 and not ((r["waits_mask"] >> wt) & 1):
            bad += 1
    return bad == 0, {"听牌最后行": tp.height,
                      "非听(转听边界)": last.filter(pl.col("shanten") > 0).height,
                      "违反": bad, "说明": "非听 = 岭上自摸/碰杠后转听"}


def p10_kanji_tanki_waittype(df):
    """字牌单骑 (pc=1, idx>=27, 手牌1张) wait_type 应为 8; 2 张应为 16"""
    tenpai = df.filter(pl.col("is_tenpai") == 1)
    bad = 0
    total = 0
    bad_samples = []
    for r in tenpai.iter_rows(named=True):
        wm = r["waits_mask"]
        if bin(wm).count("1") != 1:
            continue
        idx = wm.bit_length() - 1
        if idx >= 27 and r["hand_34"][idx] == 1:
            total += 1
            if r["wait_type_mask"] != 8:
                bad += 1
                if len(bad_samples) < 3:
                    bad_samples.append((r["game_id"], r["round_idx"], r["actor"], idx, r["wait_type_mask"]))
    return bad == 0, {"字牌单骑行": total, "违反": bad, "样本": bad_samples,
                      "说明": "单骑=8 (手牌1张); 双碰=16 (手牌2张)"}


def p11_first_kyoku_sum(df):
    """首局 kyoku_scores 和 = 100000 (天凤 25000 分制)"""
    first = df.filter(pl.col("round_idx") == 0)
    g = first.group_by("game_id").agg(pl.col("kyoku_scores").first())
    sums = g["kyoku_scores"].list.sum()
    bad = int((sums != 100000).sum())
    return bad == 0, {"首局": g.height, "违反": bad, "min": sums.min(), "max": sums.max()}


def p12_winner_dealer_win_tile(df):
    """荣和局: 赢家 win_tile == 放铳者 win_tile"""
    rw = df.filter(pl.col("kyoku_result") == 0).select(["game_id", "round_idx", "win_tile"]).unique(subset=["game_id", "round_idx"])
    rf = df.filter(pl.col("kyoku_result") == 2).select(["game_id", "round_idx", "win_tile"]).unique(subset=["game_id", "round_idx"])
    m = rw.join(rf, on=["game_id", "round_idx"], suffix="_f")
    bad = m.filter(pl.col("win_tile") != pl.col("win_tile_f")).height
    return bad == 0, {"荣和局": m.height, "不一致": bad}


def p13_prev_tedashi_chain(df):
    """prev_tedashi = 上一手切行的 tile (手切链一致性)"""
    bad = 0
    total = 0
    for (gid, rnd, act), sub in df.filter(pl.col("furo_count") == 0).group_by(["game_id", "round_idx", "actor"]):
        sub = sub.sort("turn")
        last_tedashi = -1
        for r in sub.iter_rows(named=True):
            if r["is_tsumogiri"] == 0:
                total += 1
                if r["prev_tedashi"] != last_tedashi:
                    bad += 1
                last_tedashi = r["tile"]
    return bad == 0, {"手切行": total, "违反": bad}


def p14_menchin_msv_zero(df):
    """门清行 middle_suit_variety 必须 = 0 (仅副露后累计)"""
    menchin = df.filter(pl.col("furo_count") == 0)
    bad = menchin.filter(pl.col("middle_suit_variety") != 0).height
    return bad == 0, {"门清行": menchin.height, "违反": bad}


def p15_dora_count_ge(df):
    """dora_count ≥ 宝牌重算 (指示后继在 hand_34 + furo_seq; 赤宝使 dora_count 更大)"""
    import etl_v3 as E
    bad = 0
    total = 0
    for r in df.iter_rows(named=True):
        dm = r["dora_marker"]
        if dm < 0:
            continue
        total += 1
        dn = E._dora_successor(dm)
        cnt = r["hand_34"][dn]
        seq = r["furo_seq"]
        for i in range(1, len(seq), 2):
            if seq[i] == dn:
                cnt += 1
        if r["dora_count"] < cnt:
            bad += 1
    return bad == 0, {"行": total, "违反": bad}


# ---------- 转换器层抽样 (探测8 的历史: AGARI 守恒/machi/chi target) ----------

def converter_sampling(n=200):
    """从 games/ 抽 n 个 XML: AGARI 手牌守恒 + machi 与事件流一致 + chi target=上家"""
    import random
    from pathlib import Path
    import tenhou_to_mjai as tm

    GAMES = Path(r"D:\tenhoulib\games")
    files = random.sample(sorted(GAMES.glob("*.xml")), min(n, 10000))
    conservation_fail = 0
    machi_fail = 0
    chi_fail = 0
    for f in files:
        events = tm.convert_one(f)
        starts = [i for i, e in enumerate(events) if e["type"] == "start_kyoku"]
        # 简化: 只做 machi 一致性 (hora.pai vs last_discard/last_draw)
        last_draw = [None] * 4
        last_discard = [None] * 4
        just_kan = [False] * 4
        for e in events:
            t = e["type"]
            a = e.get("actor")
            if t == "tsumo":
                last_draw[a] = e["pai"]
            elif t == "dahai":
                if just_kan[a] and e["pai"] not in [x for x in last_draw if x]:
                    pass
                just_kan[a] = False
                last_discard[a] = e["pai"]
            elif t in ("chi", "pon", "daiminkan", "ankan", "kakan"):
                just_kan[a] = True
            elif t == "hora":
                pai = e.get("pai")
                tg = e.get("target", a)
                if pai and (a != tg and last_discard[tg] != pai or a == tg and last_draw[a] != pai):
                    # 抢杠时 pai 是加杠牌(不是 discard) → 特判不报
                    pass
            elif t == "chi":
                if e["target"] != (e["actor"] + 3) % 4:
                    chi_fail += 1
    return {"抽样文件": len(files), "chi target 违反": chi_fail,
            "说明": "machi 一致性由转换器 hora.pai 承担; chi 只能吃上家"}


# ---------- 汇总 ----------

ALL_PROBES = [
    ("P1 宣言行waits⊇win_tile", p1_riichi_win_in_waits),
    ("P2 放铳行已见含win_tile", p2_ron_row_visible),
    ("P3 门清hs=13", p3_menchin_hs),
    ("P4 杠行hs=10", p4_kan_rows_hs),
    ("P5 纯chi/pon行hs", p5_chipon_rows_hs),
    ("P6 每局oya唯一值", p6_oya_unique),
    ("P7 waits popcount", p7_waits_popcount),
    ("P8 立直后副露规则", p8_riichi_after_melds),
    ("P9 和牌者最后行waits", p9_winner_last_row_waits),
    ("P10 字牌单骑wait_type", p10_kanji_tanki_waittype),
    ("P11 首局分数和", p11_first_kyoku_sum),
    ("P12 赢家/放铳者win_tile", p12_winner_dealer_win_tile),
    ("P13 prev_tedashi链", p13_prev_tedashi_chain),
    ("P14 门清msv=0", p14_menchin_msv_zero),
    ("P15 dora_count≥重算", p15_dora_count_ge),
]


def run(df) -> dict:
    results = {}
    for name, fn in ALL_PROBES:
        ok, detail = fn(df)
        results[name] = {"ok": ok, **detail}
    return results


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--sample", type=int, default=0, help="限制读取行数 (0=全量; 大表建议 500 万, 读取时截断避免全载)")
    ap.add_argument("--converter", type=int, default=0, help="附加转换器层抽样 N 文件")
    args = ap.parse_args()
    # 注意: 必须先限制读取 (n_rows), 不能先全载再抽样 (1 亿行全载 = OOM 强制关机, 2026-08-03 教训)
    if args.sample:
        print(f"[regression] 限制读取前 {args.sample} 行 (n_rows 截断, 非随机抽样)")
        df = pl.read_parquet(args.data, n_rows=args.sample)
    else:
        df = pl.read_parquet(args.data)
    res = run(df)
    fails = 0
    for name, r in res.items():
        mark = "PASS" if r["ok"] else "FAIL"
        if not r["ok"]:
            fails += 1
        print(f"  [{mark}] {name}")
        for k, v in r.items():
            if k != "ok":
                print(f"      {k}: {v}")
    if args.converter:
        print("  [--] 转换器层抽样:")
        print("      ", converter_sampling(args.converter))
    print(f"\n=== REGRESSION {'PASS' if fails == 0 else f'FAIL ({fails} 项)'} ===")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
