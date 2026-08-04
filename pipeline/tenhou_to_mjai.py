"""Convert tenhou XML (mjloggm) to mjai JSON-lines format.

Handles XML tags like <D112/> (type+id combined as tag name).
Generates mjai events for all game actions including melds.

Fixed version (v2):
  - Tracks hands by full tile IDs (0-135), not categories, preserving aka.
  - Decodes chi consumed tiles from tenhou m bits correctly.
  - Properly separates pon/daiminkan/kakan/ankan logic.
  - Kakan removes only 1 added tile (not 3).
  - Emits end_kyoku after each kyoku (AGARI/RYUUKYOKU).
"""

import json, re, sys
from pathlib import Path
from xml.etree import ElementTree as ET
from urllib.parse import unquote

sys.stdout.reconfigure(encoding='utf-8')

TILE_CATS = (
    [f'{i+1}m' for i in range(9)] +
    [f'{i+1}p' for i in range(9)] +
    [f'{i+1}s' for i in range(9)] +
    ['E', 'S', 'W', 'N', 'P', 'F', 'C']
)

AKA_MAP = {4: '5mr', 13: '5pr', 22: '5sr'}
CAT_TO_T6 = (
    list(range(11, 20)) + list(range(21, 30)) +
    list(range(31, 40)) + [41, 42, 43, 44, 45, 46, 47]
)


def cat_to_t6(cat):
    return CAT_TO_T6[cat]


def id_to_pai(tile_id, aka):
    c = tile_id // 4
    cp = tile_id % 4
    if aka and c in AKA_MAP and cp == 0:
        return AKA_MAP[c]
    return TILE_CATS[c]


def id_to_t6(tile_id):
    return cat_to_t6(tile_id // 4)


def _remove_tile_by_id(hands, actor, tile_id):
    """Remove exact tile instance from hand."""
    try:
        hands[actor].remove(tile_id)
    except ValueError:
        pass


def _remove_tile_by_cat(hands, actor, cat, aka):
    """按类别移除一张手牌，返回被移除的实际牌名（含赤标记，与手牌一致）.

    m 字段只编码类别（+被叫位置+赤显示标志），不编码具体副本 ID（0-135）。
    推导副本号移除 31.8% 失败（AUDIT_TILE_ID.md）→ 改为按类别移除，
    输出用实际被移除的牌（若手牌有赤牌则输出 5xr，普通则 5x）。
    """
    for tid in list(hands[actor]):
        if tid // 4 == cat:
            hands[actor].remove(tid)
            return id_to_pai(tid, aka)
    return None


# ---- converter ----

_ACTOR_MAP = {'T': 0, 'U': 1, 'V': 2, 'W': 3, 'D': 0, 'E': 1, 'F': 2, 'G': 3}
_EVENTS = []


def ev(obj):
    _EVENTS.append(obj)


def _tag_type(tag):
    """Parse '<D112/>' → ('D', 112) or ('T', 124) or ('N', '') etc."""
    if tag in ('N', 'DORA', 'REACH', 'INIT', 'TAIKYOKU', 'AGARI',
               'RYUUKYOKU', 'SHUFFLE', 'GO', 'UN', 'MJLOG', 'mjloggm',
               'TAIKYOKU', 'BYE'):
        return tag, ''
    m = re.match(r'^([TUVWDEFG])(\d+)$', tag)
    if m:
        return m.group(1), int(m.group(2))
    return tag, ''


def convert_one(xml_path):
    _EVENTS.clear()
    tree = ET.parse(xml_path)
    root = tree.getroot()

    go = root.find('.//GO')
    gtype = int(go.get('type', '0')) if go is not None else 0
    aka = not ((gtype >> 1) & 1)

    un = root.find('.//UN')
    names = []
    if un is not None:
        for i in range(4):
            raw = un.get(f'n{i}', '')
            names.append(unquote(raw) if raw else f'P{i}')

    ev({'type': 'start_game', 'names': names, 'kyoku_first': 0, 'aka_flag': aka})

    scores = [25000] * 4
    bakaze = 'E'
    oya = 0
    hands = [[] for _ in range(4)]  # stores full tile IDs (0-135)
    last_discard = None
    last_discarder = None
    last_tsumo = [None, None, None, None]

    for elem in root:
        tag = elem.tag
        ttype, tval = _tag_type(tag)

        if tag == 'TAIKYOKU':
            oya = int(elem.get('oya', '0'))

        elif tag == 'INIT':
            seed = elem.get('seed', '0,0,0,0,0,0').split(',')
            kyoku = int(seed[0])
            honba = int(seed[1])
            kyotaku = int(seed[2])
            oya = int(elem.get('oya', '0'))
            bakaze = ['E', 'S', 'W', 'N'][kyoku // 4]

            ten = elem.get('ten', '').split(',')
            if len(ten) >= 4:
                scores = [int(x) * 100 for x in ten[:4]]

            dora_val = int(seed[5])
            dora_marker = id_to_pai(dora_val, aka)

            tehais = []
            for i in range(4):
                hai = elem.get(f'hai{i}', '')
                if hai:
                    tile_ids = [int(x) for x in hai.split(',')]
                    hands[i] = list(tile_ids)  # full tile IDs
                    tehais.append([id_to_pai(t, aka) for t in tile_ids])
                else:
                    hands[i] = ['?'] * 13
                    tehais.append(['?'] * 13)

            last_discard = last_discarder = None
            last_tsumo = [None, None, None, None]

            ev({
                'type': 'start_kyoku',
                'bakaze': bakaze,
                'dora_marker': dora_marker,
                'kyoku': (kyoku % 4) + 1,
                'honba': honba,
                'kyotaku': kyotaku,
                'oya': oya,
                'scores': list(scores),
                'tehais': tehais,
            })

        elif ttype in 'TUVW':
            actor = _ACTOR_MAP[ttype]
            pai_val = tval
            pai = id_to_pai(pai_val, aka)
            hands[actor].append(pai_val)  # full tile ID
            last_tsumo[actor] = pai_val
            ev({'type': 'tsumo', 'actor': actor, 'pai': pai})

        elif ttype in 'DEFG':
            actor = _ACTOR_MAP[ttype]
            pai_val = tval
            pai = id_to_pai(pai_val, aka)
            _remove_tile_by_id(hands, actor, pai_val)
            is_tsumo = (last_tsumo[actor] == pai_val)
            ev({'type': 'dahai', 'actor': actor, 'pai': pai, 'tsumogiri': is_tsumo})
            last_discard = pai_val
            last_discarder = actor

        elif tag == 'N':
            who = int(elem.get('who', '0'))
            m = int(elem.get('m', '0'))
            _handle_n(who, m, last_discard, last_discarder, aka, hands)

        elif tag == 'DORA':
            dora_marker = id_to_pai(int(elem.get('hai', '0')), aka)
            ev({'type': 'dora', 'dora_marker': dora_marker})

        elif tag == 'REACH':
            who = int(elem.get('who', '0'))
            step = int(elem.get('step', '1'))
            if step == 1:
                ev({'type': 'reach', 'actor': who})
            elif step == 2:
                ev({'type': 'reach_accepted', 'actor': who})
                ten = elem.get('ten', '').split(',')
                if len(ten) >= 4:
                    scores = [int(x) * 100 for x in ten[:4]]

        elif tag == 'AGARI':
            who = int(elem.get('who', '0'))
            from_who = int(elem.get('fromWho', '0'))
            sc = elem.get('sc', '')
            deltas = None
            if sc:
                parts = sc.split(',')
                deltas = [int(parts[i * 2 + 1]) * 100 for i in range(4)]
            ura = elem.get('doraHaiUra', '')
            ura_markers = [id_to_pai(int(x), aka) for x in ura.split(',') if x]
            machi = elem.get('machi', '')
            machi_tiles = [id_to_pai(int(x), aka) for x in machi.split(',') if x]
            # 役种 (成对: 役码,番数) + 符数/点数 (ten)
            yaku_raw = elem.get('yaku', '')
            yaku_list = []
            if yaku_raw:
                yparts = [int(x) for x in yaku_raw.split(',')]
                yaku_list = [yparts[i] for i in range(0, len(yparts) - 1, 2)]
            ten_fu, ten_points = 0, 0
            ten_raw = elem.get('ten', '')
            if ten_raw:
                tparts = ten_raw.split(',')
                if len(tparts) >= 2:
                    ten_fu = int(tparts[0])
                    ten_points = int(tparts[1])
            ev({
                'type': 'hora',
                'actor': who,
                'target': from_who,
                'pai': machi_tiles[0] if machi_tiles else None,
                'deltas': deltas,
                'ura_markers': ura_markers,
                'yaku': yaku_list,
                'ten_fu': ten_fu,
                'ten_points': ten_points,
            })
            ev({'type': 'end_kyoku'})

        elif tag == 'RYUUKYOKU':
            sc = elem.get('sc', '')
            deltas = None
            if sc:
                parts = sc.split(',')
                deltas = [int(parts[i * 2 + 1]) * 100 for i in range(4)]
            ev({'type': 'ryukyoku', 'deltas': deltas, 'reason': elem.get('type', '')})
            ev({'type': 'end_kyoku'})

    ev({'type': 'end_game'})
    return _EVENTS


def _handle_n(who, m, last_discard, last_discarder, aka, hands):
    """Handle N (meld) element — authoritative tenhou m bitfield decode.

    mjlog v4 bit layout (tehai.js, libriichi, pymahjong agree):
      bits 0-1: relative seat providing the called tile (0 = ankan)
      bit 2  : chi
      bit 3  : pon
      bit 4  : kakan (add 4th tile to existing pon)
      bit 5  : nukidora (sanma only)
      none of bits 2-5: daiminkan (bits0-1 != 0) or ankan (bits0-1 == 0)
    """
    target_rel = m & 3
    target = (who + target_rel) % 4

    if (m & 0x3F) == 0x20:
        # nukidora (sanma): remove one north from hand (sanma rule)
        _remove_tile_by_cat(hands, who, 30, aka)
        ev({'type': 'kita', 'actor': who, 'pai': 'N'})
        return

    if m & (1 << 2):
        # chi: t 解码出 3 个连续类别, 被叫牌在 r 位置 (来自他家, 不在手牌), 其余 2 个从手牌移除
        t = (m & 0xFC00) >> 10
        r = t % 3
        t = t // 3
        base = 9 * (t // 7) + (t % 7)
        cats = [base, base + 1, base + 2]
        # 被叫牌 = 他家打出的牌 (last_discard), 其类别 = cats[r]
        called = id_to_pai(last_discard, aka) if last_discard is not None and last_discard // 4 == cats[r] else None
        # 手牌 2 张 = 除被叫位置外的 2 个类别
        consumed_cats = [cats[i] for i in range(3) if i != r]
        consumed = [c for c in (_remove_tile_by_cat(hands, who, c, aka) for c in consumed_cats)
                    if c is not None]
        if called is None:
            # 被叫牌类别与 last_discard 不符 (异常) → 用类别名
            called = TILE_CATS[cats[r]]
        ev({
            'type': 'chi', 'actor': who, 'target': target,
            'pai': called,
            'consumed': consumed,
        })
        return

    if m & (1 << 3):
        # pon: 碰 3 张同类别, 被叫牌来自他家, 手牌移除 2 张
        t = (m & 0xFE00) >> 9
        pn = t // 3
        cat = (pn // 9) * 9 + pn % 9
        called = id_to_pai(last_discard, aka) if last_discard is not None and last_discard // 4 == cat else None
        consumed = [c for c in (_remove_tile_by_cat(hands, who, cat, aka)
                                for _ in range(2)) if c is not None]
        if called is None:
            called = TILE_CATS[cat]
        ev({
            'type': 'pon', 'actor': who, 'target': target,
            'pai': called,
            'consumed': consumed,
        })
        return

    if m & (1 << 4):
        # kakan: 手牌移除第 4 张 (加杠牌), 类别 = t 解码
        t = (m & 0xFE00) >> 9
        pn = t // 3
        cat = (pn // 9) * 9 + pn % 9
        added = _remove_tile_by_cat(hands, who, cat, aka)
        ev({
            'type': 'kakan', 'actor': who,
            'pai': added,
            'consumed': [added] if added else [],
        })
        return

    # daiminkan / ankan
    hai0 = (m & 0xFF00) >> 8
    pn = hai0 // 4
    cat = (pn // 9) * 9 + pn % 9
    if target_rel == 0:
        # ankan: 手牌 4 张全移除 (按类别×4)
        consumed = [c for c in (_remove_tile_by_cat(hands, who, cat, aka)
                                for _ in range(4)) if c is not None]
        ev({
            'type': 'ankan', 'actor': who,
            'consumed': consumed,
        })
    else:
        # daiminkan: h[0] = called tile from target, 手牌移除 3 张
        called = id_to_pai(last_discard, aka) if last_discard is not None and last_discard // 4 == cat else None
        consumed = [c for c in (_remove_tile_by_cat(hands, who, cat, aka)
                                for _ in range(3)) if c is not None]
        if called is None:
            called = TILE_CATS[cat]
        ev({
            'type': 'daiminkan', 'actor': who, 'target': target,
            'pai': called,
            'consumed': consumed,
        })


def convert(xml_path, output_path=None):
    events = convert_one(xml_path)
    out = output_path or xml_path.with_suffix('.mjai')
    out.write_text('\n'.join(json.dumps(e, ensure_ascii=False) for e in events), encoding='utf-8')
    return out


def batch(input_dir, output_dir=None):
    input_dir = Path(input_dir)
    output_dir = Path(output_dir) if output_dir else input_dir
    output_dir.mkdir(exist_ok=True)
    results = []
    for f in sorted(input_dir.glob('*.xml')):
        out = output_dir / f.with_suffix('.mjai').name
        convert(f, out)
        results.append((f.name, out.name))
    return results


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='Convert tenhou XML logs to mjai format')
    ap.add_argument('input', help='XML file or directory')
    ap.add_argument('-o', '--output', help='Output file or directory')
    args = ap.parse_args()

    p = Path(args.input)
    out_path = Path(args.output) if args.output else None
    if p.is_dir():
        res = batch(p, out_path)
        for src, dst in res:
            print(f'  {src} -> {dst}')
        print(f'\nConverted {len(res)} files')
    else:
        out = convert(p, out_path)
        print(f'Converted: {out}')
