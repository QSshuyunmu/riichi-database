"""build_golden_set.py — 扫描 XML 目录, 按稀有场景分类精选 200 个样本 → data/golden_set.json

场景 (每类最多 max_per 个):
  aka_discard    切赤牌宣言/赤牌副露 (赤牌相关, 修复验证重点)
  ankan          暗杠
  ron_grab       抢杠 (AGARI fromWho != who 且 machi 为杠牌)
  kokushi        国士 (AGARI yaku 含国士码)
  double_win     双和 (同局多个 AGARI)
  nagare_mangan  流局满贯 (RYUUKYOKU type=nm)
  yao9           九种九牌 (type=yao9)
  kaze4          四风连打 (type=kaze4)
  reach4         四家立直 (type=reach4)
  long_game      连庄长局 (>12 局半庄)
  bye            BYE 掉线
  plain          普通 (补充到 200)
"""
import argparse
import json
import re
from pathlib import Path

CATS = ["aka_discard", "ankan", "ron_grab", "kokushi", "double_win", "nagare_mangan",
        "yao9", "kaze4", "reach4", "long_game", "bye", "plain"]
TARGET = 200
MAX_PER = {c: 25 for c in CATS}
MAX_PER["plain"] = 60


def classify(xml_text: str) -> set[str]:
    tags = set()
    # 流局类型
    if re.search(r"<RYUUKYOKU[^>]*type=\"nm\"", xml_text):
        tags.add("nagare_mangan")
    if re.search(r"<RYUUKYOKU[^>]*type=\"yao9\"", xml_text):
        tags.add("yao9")
    if re.search(r"<RYUUKYOKU[^>]*type=\"kaze4\"", xml_text):
        tags.add("kaze4")
    if re.search(r"<RYUUKYOKU[^>]*type=\"reach4\"", xml_text):
        tags.add("reach4")
    if re.search(r"<BYE[^>]*>", xml_text):
        tags.add("bye")
    n_init = len(re.findall(r"<INIT[^>]*>", xml_text))
    if n_init > 12:
        tags.add("long_game")
    # AGARI 数 > INIT 数 → 双和
    n_agari = len(re.findall(r"<AGARI[^>]*>", xml_text))
    if n_agari > n_init:
        tags.add("double_win")
    # 暗杠: N 事件 m 低 2 位=0 且无 chi/pon/kakan bit
    for m in re.findall(r"<N[^>]*m=\"(\d+)\"", xml_text):
        mv = int(m)
        if (mv & 0x4) == 0 and (mv & 0x8) == 0 and (mv & 0x10) == 0 and (mv & 3) == 0:
            tags.add("ankan")
    # 国士: AGARI yaku 含国士码 (46=国士無双, 47=国士13面) 或 hai 全幺九
    for m in re.findall(r"<AGARI[^>]*yaku=\"([^\"]*)\"", xml_text):
        yaku_codes = [int(x) for x in m.split(",")[0::2]]
        if 46 in yaku_codes or 47 in yaku_codes:
            tags.add("kokushi")
    # 抢杠: AGARI fromWho != who 且前一 N 是 kakan (简化: 存在 fromWho!=who 的 AGARI)
    for m in re.findall(r"<AGARI[^>]*fromWho=\"(\d+)\"[^>]*who=\"(\d+)\"", xml_text):
        fw, w = int(m[0]), int(m[1])
        if fw != w:
            tags.add("ron_grab")
    # 赤牌: 切出/副露赤牌 (ID 16/52/88) — 用事件标签直接匹配
    if re.search(r"<[DEFG](16|52|88)/>", xml_text):
        tags.add("aka_discard")
    return tags


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xml-dir", required=True)
    ap.add_argument("--out", default="")
    ap.add_argument("--limit", type=int, default=50000, help="扫描前 N 个文件")
    args = ap.parse_args()
    xml_dir = Path(args.xml_dir)
    out = Path(args.out) if args.out else Path(__file__).parent / "data" / "golden_set.json"

    picked = {c: [] for c in CATS}
    scanned = 0
    for fp in sorted(xml_dir.glob("*.xml"))[: args.limit]:
        scanned += 1
        text = fp.read_text(encoding="utf-8", errors="replace")
        cats = classify(text)
        # 每文件按优先级放入第一个未满的类别
        for c in ["aka_discard", "ankan", "ron_grab", "kokushi", "double_win",
                  "nagare_mangan", "yao9", "kaze4", "reach4", "long_game", "bye", "plain"]:
            if c in cats and len(picked[c]) < MAX_PER[c]:
                picked[c].append(fp.stem)
                break
        if sum(len(v) for v in picked.values()) >= TARGET:
            break

    result = {c: v for c, v in picked.items() if v}
    total = sum(len(v) for v in result.values())
    print(f"scanned={scanned} picked={total}")
    for c in CATS:
        print(f"  {c}: {len(picked[c])}")
    # 若不足 200, 补普通
    if total < TARGET:
        need = TARGET - total
        for fp in sorted(xml_dir.glob("*.xml"))[: args.limit]:
            if len(picked["plain"]) >= MAX_PER["plain"] + need:
                break
            st = fp.stem
            if st not in [x for v in result.values() for x in v]:
                picked["plain"].append(st)
                total += 1
                if total >= TARGET:
                    break
        result["plain"] = picked["plain"]

    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "_meta": {"source": xml_dir.name, "scanned": scanned, "target": TARGET},
        "files": [x for v in picked.values() for x in v],
        "by_cat": {c: v for c, v in picked.items() if v},
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"written: {out} ({len(payload['files'])} files)")


if __name__ == "__main__":
    main()
