"""build_baseline.py v2 — 从 nodocchi 原始数据生成 baseline_stats.json（修正口径）

规则:
  1. 每个指标只从**单个字段文件**取数（该文件按该指标排序的 top 270 玩家）
  2. 比率指标 = 同一行内的 num/den（同文件同玩家），总加权用该行 totalgame
  3. 玩家级统计与局级加权并行输出
"""
import json
import statistics
from pathlib import Path

RAW = Path(r"D:\tenhoulib\data\nodocchi_raw")
OUT = Path(r"D:\tenhoulib\data\baseline_stats.json")


def load(name: str) -> list:
    fp = RAW / f"{name}.json"
    if not fp.exists():
        return []
    with open(fp, encoding="utf-8-sig") as f:
        j = json.load(f)
    return j.get("data", []) if isinstance(j, dict) else []


def ratio_metric(src_file: str, num_key: str, den_key: str) -> dict | None:
    """从单一文件计算 num/den 比率（局级加权 + 玩家级分位）."""
    rows = []
    for r in load(src_file):
        n, d = r.get(num_key), r.get(den_key)
        tg = r.get("totalgame")
        if n is None or not d or not tg:
            continue
        rows.append((tg, n / d))
    if not rows:
        return None
    vs = [v for _, v in rows]
    tw = sum(tg for tg, _ in rows)
    n = len(vs)
    vs_s = sorted(vs)
    return {
        "n": n, "total_games": int(tw),
        "mean_w": round(sum(rows[i][1] * rows[i][0] for i in range(n)) / max(tw, 1), 6),
        "mean_p": round(sum(vs) / n, 6),
        "median": round(vs_s[n // 2], 6),
        "p10": round(vs_s[int(n * 0.1)], 6),
        "p90": round(vs_s[int(n * 0.9)], 6),
        "min": round(vs_s[0], 6), "max": round(vs_s[-1], 6),
    }


def value_metric(src_file: str, key: str) -> dict | None:
    """单一字段的加权均值统计."""
    rows = []
    for r in load(src_file):
        v = r.get(key)
        tg = r.get("totalgame")
        if v is None or not tg or not isinstance(v, (int, float)):
            continue
        rows.append((tg, v))
    if not rows:
        return None
    vs = [v for _, v in rows]
    tw = sum(tg for tg, _ in rows)
    n = len(vs)
    vs_s = sorted(vs)
    return {
        "n": n, "total_games": int(tw),
        "mean_w": round(sum(rows[i][1] * rows[i][0] for i in range(n)) / max(tw, 1), 4),
        "mean_p": round(sum(vs) / n, 4),
        "median": round(vs_s[n // 2], 4),
        "p10": round(vs_s[int(n * 0.1)], 4),
        "p90": round(vs_s[int(n * 0.9)], 4),
        "min": round(vs_s[0], 4), "max": round(vs_s[-1], 4),
    }


def main():
    out = {}
    # 文件 -> (指标名, 计算方式)
    out["和率_agari_rate"] = ratio_metric("agariC_", "agari", "totalgame")
    out["铳率_houjuu_rate"] = ratio_metric("houjuuC_", "houjuu", "totalgame")
    out["立直率_riichi_rate"] = ratio_metric("riichC_", "riich", "totalgame")
    out["副露率_fuuro_rate"] = ratio_metric("fuuroC_", "fuuro", "totalgame")
    out["流局率_nagare_rate"] = ratio_metric("nagareVT", "nagare", "totalgame")
    out["自摸率_tsumo_share"] = ratio_metric("tsumoV_", "agariM", "agari")
    out["赤宝率_aka_share"] = ratio_metric("akaV", "aka", "agari")
    out["役满率_yakuman_share"] = ratio_metric("yakumanV_", "yakuman", "agari")
    out["杠率_kan_rate"] = ratio_metric("kanC_", "kan", "totalgame")
    out["击飞率_tobi_rate"] = ratio_metric("tobiZ_", "tobi", "totalgame")
    out["流局听牌率_nagare_tenpai_share"] = ratio_metric("nagaretenpaiV", "nagaretenpai", "nagare")
    out["all_last_逆转率"] = ratio_metric("al_nyaku_up_Z", "al_nyaku_up", "totalgame")
    out["一发率_ippatsu_share"] = ratio_metric("ippatsuV_", "ippatsu", "riichA")
    out["平和率_pinfu_share"] = ratio_metric("pinfuV_", "pinfu", "agari")
    out["断幺率_tanyao_share"] = ratio_metric("tanyaoV_", "tanyao", "agari")
    out["七对率_chiitoi_share"] = ratio_metric("chiitoiV_", "chiitoi", "agari")
    out["三色率_sanshoku_share"] = ratio_metric("sanshokuV_", "sanshoku", "agari")
    out["全带率_chantai_share"] = value_metric("chantaiV_", "chantaiV")
    out["岭上率_rinshan_share"] = ratio_metric("rinshan_V_", "rinshan", "kan")
    out["默听率_dama_share"] = ratio_metric("damaV_", "agariD", "agari")
    out["立直成功率_riichi_success"] = ratio_metric("riich_seikou_V", "agariR", "riichkansei")
    out["和牌点数_agari_points"] = value_metric("agariVFT", "agariVFT")
    out["放铳点数_houjuu_points"] = value_metric("houjuuVT", "houjuuVT")
    out["宝牌数_dora_avg"] = value_metric("doraV", "doraV")
    out["供托_kyotaku"] = value_metric("kyoutakuVT", "kyoutakuVT")
    out["收支_shuushi"] = value_metric("shuushiCT_", "shuushiCT")

    # 顺位: order_Z 字段直接给出平均顺位 (final1..4 的次数/局数)
    out["平均顺位_avg_rank"] = value_metric("order_Z", "order_Z")
    out["一位率_rank1_rate"] = ratio_metric("order_Z", "final1", "totalrecord")
    out["四位率_rank4_rate"] = ratio_metric("order_Z", "final4", "totalrecord")

    out["_meta"] = {
        "source": "nodocchi.moe /api/phoenix_list.php (Phoenix DB)",
        "filter": "playernum=4, playlength=0, min=5000, recent=0 (全时段)",
        "fetched": "2026-08-04",
        "note": "每指标取该字段排序的 top 玩家; mean_w=局级加权, mean_p=玩家级均值, p10/p90=玩家级分位"
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"written: {OUT} ({OUT.stat().st_size} bytes)\n")
    for k, v in out.items():
        if k == "_meta":
            continue
        if v is None:
            print(f"  {k}: MISSING")
        else:
            print(f"  {k}: mean_w={v['mean_w']} p10={v['p10']} p90={v['p90']} n={v['n']} games={v['total_games']}")


if __name__ == "__main__":
    main()
