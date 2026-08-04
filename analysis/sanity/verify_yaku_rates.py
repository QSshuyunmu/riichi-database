"""verify_yaku_rates.py — 役种率验证 vs nodocchi 基准

从 mjai 事件流 (games_200k_v2) 统计: 平和/断幺/七对/三色/立直 在和牌中的占比,
对比 nodocchi 基准 (data/baseline_stats.json).

yaku 码 (天凤 hupai_name 索引): 0=门清自摸 1=立直 7=平和 8=断幺 9=一盃口
  11-18=自风/场风/役牌 21=両立直 22=七对 23=混全 24=一通 25=三色同順 26=三色同刻
  27=三杠子 28=对对 29=三暗刻 30=小三元 31=混老头 32=二盃口 33=纯全 34=混一色 35=清一色
"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, r"D:\tenhoulib")

MJAI_DIR = Path(r"D:\tenhoulib\games_200k_v2")
BASE = json.loads(Path(r"D:\tenhoulib\data\baseline_stats.json").read_text(encoding="utf-8"))

# 天凤 yaku 码 → 名称 (与 nodocchi 字段对应)
YAKU_MAP = {
    1: "立直", 7: "平和", 8: "断幺", 9: "一盃口", 22: "七对",
    25: "三色同順", 33: "纯全", 34: "混一色", 35: "清一色",
}


def main():
    n_files = 5000
    total_agari = 0
    yaku_counts = Counter()
    for i, fp in enumerate(sorted(MJAI_DIR.glob("*.mjai"))):
        if i >= n_files:
            break
        for line in fp.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            ev = json.loads(line)
            if ev.get("type") == "hora":
                total_agari += 1
                for code in ev.get("yaku", []):
                    yaku_counts[code] += 1
    print(f"files={n_files} agari={total_agari}\n")
    print(f"{'役种':<10}{'和牌占比%':>10}{'nodocchi基准%':>14}{'p10-p90':>16}  判定")
    for code, name in YAKU_MAP.items():
        rate = yaku_counts.get(code, 0) / total_agari * 100
        b = BASE.get(f"{name}率_{'pinfu' if name=='平和' else 'tanyao' if name=='断幺' else 'chiitoi' if name=='七对' else 'sanshoku' if name=='三色同順' else name}_share")
        print(f"{name:<10}{rate:>10.2f}{'':>14}")
    # 直接对基准
    print("\n=== 对照基准 ===")
    checks = [
        ("平和", 7, "平和率_pinfu_share"),
        ("断幺", 8, "断幺率_tanyao_share"),
        ("七对", 22, "七对率_chiitoi_share"),
        ("三色", 25, "三色率_sanshoku_share"),
    ]
    for name, code, key in checks:
        rate = yaku_counts.get(code, 0) / total_agari * 100
        b = BASE.get(key)
        if not b:
            print(f"{name}: 无基准")
            continue
        lo, hi = b["p10"] * 100, b["p90"] * 100
        status = "PASS" if lo <= rate <= hi else ("WARN" if abs(rate - b["mean_w"] * 100) < 5 else "FAIL")
        print(f"{name}: 观测 {rate:.2f}% vs 基准 {b['mean_w']*100:.2f}% [p10-p90: {lo:.2f}-{hi:.2f}] → {status}")


if __name__ == "__main__":
    main()
