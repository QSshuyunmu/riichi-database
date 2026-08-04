"""etl_v3.py — Fact Schema v3 ETL: mjai → 定长 dahai_events 表（含读牌维度）

v3 新增列（支撑读牌式查询族）:
  - dora_marker        i8   当前 dora 指示牌 idx (0-33, -1=无)
  - furo_pon_honor     i8   碰/大明杠出的字牌(役牌)副露数
  - middle_suit_variety i8  副露后手切 3-7 中张的花色种类数 (0-3)
  - pair_broken        i8   立直前/全手切中拆对次数 (同牌被手切 >=2 次)
  - pair_broken_last   i8   最近拆对子的类别: 0=无 1=字牌 2=幺九 3=中张

继承 v2:
  - tsumogiri 推断 (last_draw == tile)
  - waits 34-bit 位掩码 + 5-bit wait_type 掩码 (含 penchan)
  - kyoku_result / kyoku_pt_delta 每行冗余
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

try:
    import orjson
    PARSE = lambda b: orjson.loads(b)
except ImportError:
    import json as _json
    PARSE = lambda b: _json.loads(b.decode("utf-8"))

import polars as pl

from mahjong.shanten import Shanten as _MahjongShanten

_SHANTEN_ENGINE = _MahjongShanten()

_KOKUSHI_IDXS = (0, 8, 9, 17, 18, 26, 27, 28, 29, 30, 31, 32, 33)


def calc_shanten(hand_tiles, meld_count: int) -> tuple[int, bool]:
    """向听数（mahjong 库，合并普通形+七对；shanten.py 贪心有 bug 弃用）。"""
    arr = [0] * 34
    for t in hand_tiles:
        idx = _MAP.get(t, -1)
        if idx >= 0:
            arr[idx] += 1
    try:
        s = _SHANTEN_ENGINE.calculate_shanten_for_regular_hand(arr)
        # 七对/国士: 仅门清（无副露）时可能
        if meld_count == 0:
            try:
                s7 = _SHANTEN_ENGINE.calculate_shanten_for_chiitoitsu_hand(arr)
                if s7 < s:
                    s = s7
            except ValueError:
                pass
            try:
                sk = _SHANTEN_ENGINE.calculate_shanten_for_kokushi_hand(arr)
                if sk < s:
                    s = sk
            except ValueError:
                pass
    except ValueError:
        return 99, False
    return s, s <= 0


def _shanten_arr(arr, meld_count: int) -> int:
    """34 计数数组 → 向听数（mahjong 库，合并普通形+七对）。"""
    try:
        s = _SHANTEN_ENGINE.calculate_shanten_for_regular_hand(list(arr))
        if meld_count == 0:
            try:
                s7 = _SHANTEN_ENGINE.calculate_shanten_for_chiitoitsu_hand(list(arr))
                if s7 < s:
                    s = s7
            except ValueError:
                pass
            try:
                sk = _SHANTEN_ENGINE.calculate_shanten_for_kokushi_hand(list(arr))
                if sk < s:
                    s = sk
            except ValueError:
                pass
        return s
    except ValueError:
        return 99

_MAP = {
    '1m':0,'2m':1,'3m':2,'4m':3,'5m':4,'6m':5,'7m':6,'8m':7,'9m':8,
    '1p':9,'2p':10,'3p':11,'4p':12,'5p':13,'6p':14,'7p':15,'8p':16,'9p':17,
    '1s':18,'2s':19,'3s':20,'4s':21,'5s':22,'6s':23,'7s':24,'8s':25,'9s':26,
    'E':27,'S':28,'W':29,'N':30,'P':31,'F':32,'C':33,
    '5mr':4,'5pr':13,'5sr':22,
}

WIND_ORDER = {'E': 0, 'S': 1, 'W': 2, 'N': 3}
RESULT_CODE = {'win': 0, 'tsumo': 1, 'deal_in': 2, 'tsumo_loss': 3, 'draw': 4, 'pass': 5, '': -1}
# 流局类型 (天凤 RYUUKYOKU type; 无type=荒牌): -1 非流局, 0 荒牌, 1 nm(流局满贯), 2 yao9(九种九牌),
# 3 kaze4(四风连打), 4 reach4(四家立直), 5 ron3(三家和), 6 kan4(四杠散了)
RYU_TYPE = {"": 0, "nm": 1, "yao9": 2, "kaze4": 3, "reach4": 4, "ron3": 5, "kan4": 6}

SCHEMA = {
    "game_id": pl.Utf8, "round_idx": pl.Int16, "turn": pl.Int8, "actor": pl.Int8,
    "tile": pl.Int8, "is_aka": pl.Int8, "is_tsumogiri": pl.Int8, "is_sengenhai": pl.Int8,
    "prev_tedashi": pl.Int8, "shanten": pl.Int8, "is_tenpai": pl.Int8,
    "waits_mask": pl.Int64, "wait_type_mask": pl.Int8,
    "dora_count": pl.Int8, "dora_marker": pl.Int8,
    "furo_count": pl.Int8, "furo_pon_honor": pl.Int8, "furo_yakuhai": pl.Int8,
    "middle_suit_variety": pl.Int8,
    "pair_broken": pl.Int8, "pair_broken_last": pl.Int8,
    "hand_34": pl.List(pl.Int8),
    "furo_seq": pl.List(pl.Int8),  # 副露序列: [type0,tile0,type1,tile1,...] type: 0=chi 1=pon 2=daiminkan 3=ankan 4=kakan
    "kawa_visible": pl.List(pl.Int8),  # 全局已见牌张数 (34, 手牌+牌河+副露+宝牌指示)
    "win_tile": pl.Int8,  # 本局和牌牌 (-1=本局未和/无)
    "kyoku_scores": pl.List(pl.Int32), "actor_score": pl.Int32,
    "is_oya": pl.Int8, "seat_wind": pl.Int8,
    "kyoku_num": pl.Int8, "honba": pl.Int8, "kyotaku": pl.Int8, "bakaze": pl.Int8,
    "kyoku_result": pl.Int8, "kyoku_pt_delta": pl.Int32,
    "ryukyoku_type": pl.Int8,  # 流局类型: -1 非流局; 0 荒牌 1 流局满贯 2 九种九牌 3 四风连打 4 四家立直 5 三家和 6 四杠散
}

SUIT_3_7 = set()
for num in range(2, 7):  # 3-7 → idx 2..6 每花色
    for base in (0, 9, 18):
        SUIT_3_7.add(base + num)


def _t2i(tiles) -> list[int]:
    arr = [0] * 34
    for t in tiles:
        idx = _MAP.get(t)
        if idx is not None:
            arr[idx] += 1
    return arr


def _waits_mask(hand_arr, meld_count: int, is_tenpai: bool) -> tuple[int, int]:
    if not is_tenpai:
        return 0, 0
    mask = 0
    tmask = 0
    # 普通形听牌
    for idx in range(34):
        if hand_arr[idx] >= 4:
            continue
        hand_arr[idx] += 1
        s = _shanten_arr(hand_arr, meld_count)
        hand_arr[idx] -= 1
        if s < 0:
            mask |= 1 << idx
            tmask |= _classify_bit(hand_arr, idx)
    # 七对听牌（门清且普通形无听牌时补）
    if meld_count == 0 and mask == 0:
        for idx in range(34):
            if hand_arr[idx] >= 4:
                continue
            if hand_arr[idx] >= 2 and hand_arr[idx] < 4:
                # 有对子: 不能单骑听该牌(七对要求6对+1单)
                pass
            hand_arr[idx] += 1
            try:
                s7 = _SHANTEN_ENGINE.calculate_shanten_for_chiitoitsu_hand(hand_arr)
            except ValueError:
                s7 = 99
            hand_arr[idx] -= 1
            if s7 < 0:
                mask |= 1 << idx
                tmask |= 8  # 七对听牌 = 单骑形
    # 国士听牌（门清; 13面听全部13种幺九, 普通国士听缺的1种）
    if meld_count == 0 and mask == 0:
        for idx in _KOKUSHI_IDXS:
            if hand_arr[idx] >= 4:
                continue
            hand_arr[idx] += 1
            try:
                sk = _SHANTEN_ENGINE.calculate_shanten_for_kokushi_hand(hand_arr)
            except ValueError:
                sk = 99
            hand_arr[idx] -= 1
            if sk < 0:
                mask |= 1 << idx
                tmask |= 8  # 国士听牌 = 单骑形
    return mask, tmask


def _classify_bit(hand_arr, idx: int) -> int:
    if idx >= 27:
        # 字牌: 手牌 2+ 张听第 3 张 = 双碰(16); 1 张听成对 = 单骑(8)
        return 16 if hand_arr[idx] >= 2 else 8
    num = idx % 9
    has_l = idx - 1 >= 0 and hand_arr[idx - 1] > 0
    has_r = idx + 1 < 34 and hand_arr[idx + 1] > 0
    if num == 0:
        return 4 if has_r else 8
    if num == 8:
        return 4 if has_l else 8
    if has_l and has_r:
        return 1
    if has_l or has_r:
        return 2
    return 16 if hand_arr[idx] >= 1 else 8


def _tile_class(tile_idx: int) -> int:
    """1=字牌 2=幺九 3=中张"""
    if tile_idx < 0:
        return 0
    if tile_idx >= 27:
        return 1
    num = tile_idx % 9
    if num in (0, 8):
        return 2
    return 3


def _yakuhai_idxs(bakaze: int, oya: int, actor: int) -> set[int]:
    """役牌集合: 三元(31,32,33) + 场风 + 自风（场风=自风时去重）。"""
    s = {31, 32, 33}
    s.add(27 + bakaze)          # 场风: E=27, S=28
    s.add(27 + (actor - oya) % 4)  # 自风
    return s


def _dora_successor(ti: int) -> int:
    """指示牌 → 宝牌（同色后继，风/箭循环）。"""
    if ti < 27:
        if ti % 9 == 8:
            return ti - 8
        return ti + 1
    if ti <= 30:
        return 27 + (ti - 27 + 1) % 4
    return 31 + (ti - 31 + 1) % 3


def _dora_count(hand_tiles, meld_tiles, markers: list) -> int:
    """手牌+副露中宝牌数（指示牌后继 + 赤宝牌）。"""
    cnt = 0
    for t in hand_tiles:
        if t in ('5mr', '5pr', '5sr'):
            cnt += 1
    dora_idxs = set()
    for dm in markers:
        idx = _MAP.get(dm)
        if idx is not None:
            dora_idxs.add(_dora_successor(idx))
    for t in hand_tiles + meld_tiles:
        if _MAP.get(t, -1) in dora_idxs:
            cnt += 1
    return cnt


def process_file(path: str) -> list[dict]:
    rows = []
    try:
        raw = Path(path).read_bytes()
        events = [PARSE(l) for l in raw.split(b"\n") if l.strip()]
    except Exception:
        return rows

    gid = Path(path).stem
    hands = [[], [], [], []]
    meld_tiles = [[], [], [], []]  # 副露中所有牌
    turn_c = [0, 0, 0, 0]
    furo_c = [0, 0, 0, 0]
    furo_pon_honor = [0, 0, 0, 0]
    furo_yakuhai = [0, 0, 0, 0]  # 精确役牌（场风/自风/三元）碰/大明杠数
    furo_seq = [[], [], [], []]  # 副露序列: [type,tile_idx,...]
    middle_suits = [set(), set(), set(), set()]
    rii_s = [0, 0, 0, 0]
    rii_order = [0, 0, 0, 0]
    last_draw = [None, None, None, None]
    last_tedashi = [None, None, None, None]
    last_discard = [None, None, None, None]  # 每家最近打出的牌（荣和牌判定）
    kawa_vis = [0] * 34  # 全局已见张数（手牌+牌河+副露+宝牌指示）
    win_tile_by_actor = [-1, -1, -1, -1]  # 本局各家的和牌牌
    just_kan = [False, False, False, False]  # 杠后需补岭上摸
    ryukyoku_reason = None  # 本局流局原因 (天凤 type 字符串; None=非流局)
    tedashi_count = [dict(), dict(), dict(), dict()]  # tile -> 手切次数
    pair_broken = [0, 0, 0, 0]
    pair_broken_last = [0, 0, 0, 0]
    bakaze = 0
    kyoku_num = 1
    honba = 0
    kyotaku = 0
    oya = 0
    kyoku_scores = [25000] * 4
    dora_markers = []
    kyoku_delta = [None] * 4
    kyoku_result = [None] * 4
    riichi_paid = [0, 0, 0, 0]  # 本局各家庭托 (立直供托)
    round_idx = -1
    rii_counter = 0
    kyoku_start_row = 0
    game_idx = 0  # start_game 块计数（多半庄拼接）；0 = 文件开头残局
    block_active = False  # 当前是否在 start_game..end_game 有效块内
    kyoku_active = False  # 当前局是否属于有效 start_game 块
    bad_kyoku = set()  # 违规局 (game_idx, round_idx)：局级准入 G-1..G-3（ADR-005）
    all_bad = set()  # 跨块累计违规局（过滤用）

    for ev in events:
        t = ev.get("type")
        if t == "start_game":
            # 先回填上一半庄最后一局（若有）
            if kyoku_start_row < len(rows):
                _backfill(rows, kyoku_start_row, kyoku_delta, kyoku_result, riichi_paid, win_tile_by_actor, ryukyoku_reason)
            game_idx += 1
            block_active = True
            round_idx = -1
            kyoku_start_row = len(rows)
            all_bad |= bad_kyoku
            bad_kyoku = set()
            continue
        if t == "end_game":
            block_active = False
            kyoku_active = False
            continue
        if t == "start_kyoku":
            if not block_active:
                # 残局段（无 start_game 归属）→ 丢弃本局
                kyoku_active = False
                kyoku_start_row = len(rows)
                continue
            kyoku_active = True
            if kyoku_start_row < len(rows):
                _backfill(rows, kyoku_start_row, kyoku_delta, kyoku_result, riichi_paid, win_tile_by_actor, ryukyoku_reason)
            kyoku_start_row = len(rows)
            round_idx += 1
            bakaze = WIND_ORDER.get(ev.get("bakaze", "E"), 0)
            kyoku_num = int(ev.get("kyoku", 1))
            honba = int(ev.get("honba", 0))
            kyotaku = int(ev.get("kyotaku", 0))
            oya = int(ev.get("oya", 0))
            if ev.get("scores"):
                kyoku_scores = list(ev["scores"])
            hands = [list(h) for h in ev.get("tehais", [[], [], [], []])]
            meld_tiles = [[], [], [], []]
            turn_c = [0, 0, 0, 0]
            furo_c = [0, 0, 0, 0]
            furo_pon_honor = [0, 0, 0, 0]
            furo_yakuhai = [0, 0, 0, 0]
            furo_seq = [[], [], [], []]
            middle_suits = [set(), set(), set(), set()]
            rii_s = [0, 0, 0, 0]
            rii_order = [0, 0, 0, 0]
            last_draw = [None, None, None, None]
            last_tedashi = [None, None, None, None]
            last_discard = [None, None, None, None]
            kawa_vis = [0] * 34
            win_tile_by_actor = [-1, -1, -1, -1]
            just_kan = [False, False, False, False]
            ryukyoku_reason = None
            tedashi_count = [dict(), dict(), dict(), dict()]
            pair_broken = [0, 0, 0, 0]
            pair_broken_last = [0, 0, 0, 0]
            rii_counter = 0
            dora_markers = [ev.get("dora_marker", "")]
            kyoku_delta = [None] * 4
            kyoku_result = [None] * 4
            riichi_paid = [0, 0, 0, 0]
            # 已见初始化: 4 家手牌 + 宝牌指示牌
            for i in range(4):
                for t in hands[i]:
                    ti = _MAP.get(t, -1)
                    if ti >= 0:
                        kawa_vis[ti] += 1
            dmi = _MAP.get(ev.get("dora_marker", ""), -1)
            if dmi >= 0:
                kawa_vis[dmi] += 1
        elif not kyoku_active:
            # 残局段（无 start_game 归属）→ 全部跳过
            continue
        elif t == "dora":
            dora_markers.append(ev.get("dora_marker", ""))
            dmi = _MAP.get(ev.get("dora_marker", ""), -1)
            if dmi >= 0:
                kawa_vis[dmi] += 1
        elif t == "tsumo":
            a = int(ev["actor"])
            pai = ev.get("pai", "")
            last_draw[a] = pai
            hands[a].append(pai)
            pi = _MAP.get(pai, -1)
            if pi >= 0:
                kawa_vis[pi] += 1
        elif t == "reach":
            a = int(ev["actor"])
            if rii_s[a] == 0:
                rii_s[a] = 1
                rii_counter += 1
                rii_order[a] = rii_counter
        elif t == "reach_accepted":
            a = int(ev["actor"])
            rii_s[a] = 2
            riichi_paid[a] += 1000
        elif t == "dahai":
            a = int(ev["actor"])
            tile = ev.get("pai", "")
            # 杠(暗/加/大明)后必须摸岭上牌再打出; mjai 缺岭上摸 tsumo 事件(转换器局限)
            # 若打的牌不在手牌 → 该牌即岭上摸的牌 → 补回 (GAME_MODEL §0)
            if just_kan[a]:
                if rii_s[a] != 1 and tile not in hands[a]:
                    hands[a].append(tile)  # 岭上摸的牌
                    pi = _MAP.get(tile, -1)
                    if pi >= 0:
                        kawa_vis[pi] += 1  # 岭上摸 → 已见 +1
                just_kan[a] = False
            if tile in hands[a]:
                hands[a].remove(tile)
            else:
                # 局级准入 G-2 (ADR-005): dahai 移除失败 = 副本歧义连锁 → 整局丢弃
                bad_kyoku.add((game_idx, round_idx))
            turn_c[a] += 1  # 巡目在出牌时递增（副露后无 tsumo 事件）
            # tsumogiri: 立直宣言牌字段恒 false → 用 last_draw 推断；普通出牌用原始字段
            if rii_s[a] == 1:
                is_tsumo = last_draw[a] == tile
            else:
                is_tsumo = bool(ev.get("tsumogiri", False))
            is_sengenhai = rii_s[a] == 1
            if is_sengenhai:
                rii_s[a] = 2

            arr = _t2i(hands[a])
            meld_n = furo_c[a]
            s_val, is_tenpai = calc_shanten(hands[a], meld_n)
            waits_mask, wtype_mask = _waits_mask(arr, meld_n, is_tenpai) if is_tenpai else (0, 0)

            tile_idx = _MAP.get(tile, -1)
            is_aka = int(tile in ("5mr", "5pr", "5sr"))
            dm = _MAP.get(dora_markers[-1], -1) if dora_markers else -1
            dcnt = _dora_count(hands[a], meld_tiles[a], dora_markers)
            last_discard[a] = tile
            # 注: dahai 不新增已见 — 切出的牌已在初始手牌或 tsumo 时计过 (修复重复计数)
            ptd = int(kyoku_delta[a]) - riichi_paid[a] if kyoku_delta[a] is not None else None
            kr = kyoku_result[a]
            rows.append({
                "game_id": f"{gid}#{game_idx}" if game_idx > 1 else gid,
                "round_idx": round_idx, "turn": int(turn_c[a]),
                "actor": a, "tile": tile_idx, "is_aka": is_aka,
                "is_tsumogiri": int(is_tsumo),
                "is_sengenhai": int(is_sengenhai),
                "prev_tedashi": _MAP.get(last_tedashi[a]) if last_tedashi[a] else -1,
                "shanten": int(s_val), "is_tenpai": int(is_tenpai),
                "waits_mask": waits_mask, "wait_type_mask": wtype_mask,
                "dora_count": dcnt, "dora_marker": dm,
                "furo_count": int(furo_c[a]), "furo_pon_honor": int(furo_pon_honor[a]),
                "furo_yakuhai": int(furo_yakuhai[a]),
                "middle_suit_variety": len(middle_suits[a]),
                "pair_broken": int(pair_broken[a]), "pair_broken_last": int(pair_broken_last[a]),
                "hand_34": arr, "furo_seq": list(furo_seq[a]),
                "kawa_visible": list(kawa_vis), "win_tile": int(win_tile_by_actor[a]),
                "kyoku_scores": kyoku_scores, "actor_score": int(kyoku_scores[a]) if a < 4 else None,
                "is_oya": int(a == oya), "seat_wind": (a - oya) % 4,
                "kyoku_num": kyoku_num, "honba": honba, "kyotaku": kyotaku, "bakaze": bakaze,
                "kyoku_result": RESULT_CODE.get(kr, -1), "kyoku_pt_delta": ptd,
                "ryukyoku_type": -1,
            })
            # 手切追踪
            if not is_tsumo:
                last_tedashi[a] = tile
                tc = tedashi_count[a]
                cnt = tc.get(tile, 0)
                if cnt >= 1:
                    pair_broken[a] += 1
                    pair_broken_last[a] = _tile_class(tile_idx)
                tc[tile] = cnt + 1
                if furo_c[a] > 0 and tile_idx in SUIT_3_7:
                    suit = tile_idx // 9
                    middle_suits[a].add(suit)
        elif t == "chi":
            a = int(ev["actor"])
            for c in ev.get("consumed", []):
                if c in hands[a]:
                    hands[a].remove(c)
                else:
                    bad_kyoku.add((game_idx, round_idx))  # G-1 副露移除失败
            furo_c[a] += 1
            pai = ev.get("pai", "")
            if pai:
                meld_tiles[a].append(pai)
            meld_tiles[a].extend(ev.get("consumed", []))
            furo_seq[a].extend([0, _MAP.get(pai, -1)])
        elif t == "pon":
            a = int(ev["actor"])
            for c in ev.get("consumed", []):
                if c in hands[a]:
                    hands[a].remove(c)
                else:
                    bad_kyoku.add((game_idx, round_idx))  # G-1 副露移除失败
            furo_c[a] += 1
            pi = _MAP.get(ev.get("pai", ""), -1)
            if pi >= 27:
                furo_pon_honor[a] += 1
                if pi in _yakuhai_idxs(bakaze, oya, a):
                    furo_yakuhai[a] += 1
            pai = ev.get("pai", "")
            if pai:
                meld_tiles[a].append(pai)
            meld_tiles[a].extend(ev.get("consumed", []))
            furo_seq[a].extend([1, pi])
        elif t == "daiminkan":
            a = int(ev["actor"])
            for c in ev.get("consumed", []):
                if c in hands[a]:
                    hands[a].remove(c)
                else:
                    bad_kyoku.add((game_idx, round_idx))  # G-1 副露移除失败
            furo_c[a] += 1
            pi = _MAP.get(ev.get("pai", ""), -1)
            if pi >= 27:
                furo_pon_honor[a] += 1
                if pi in _yakuhai_idxs(bakaze, oya, a):
                    furo_yakuhai[a] += 1
            pai = ev.get("pai", "")
            if pai:
                meld_tiles[a].append(pai)
            meld_tiles[a].extend(ev.get("consumed", []))
            furo_seq[a].extend([2, pi])
            just_kan[a] = True
        elif t == "ankan":
            a = int(ev["actor"])
            for c in ev.get("consumed", []):
                if c in hands[a]:
                    hands[a].remove(c)
                else:
                    bad_kyoku.add((game_idx, round_idx))  # G-1 副露移除失败
            furo_c[a] += 1
            meld_tiles[a].extend(ev.get("consumed", []))
            furo_seq[a].extend([3, _MAP.get(ev.get("consumed", [""])[0], -1)])
            just_kan[a] = True
        elif t == "kakan":
            a = int(ev["actor"])
            if ev.get("pai") in hands[a]:
                hands[a].remove(ev["pai"])
            else:
                bad_kyoku.add((game_idx, round_idx))  # G-1 加杠牌移除失败
            # consumed = 从手牌拿出的第 4 张（碰的牌在副露，pai 不在手牌）
            for c in ev.get("consumed", []):
                if c in hands[a]:
                    hands[a].remove(c)
                else:
                    bad_kyoku.add((game_idx, round_idx))  # G-1 副露移除失败
            pai = ev.get("pai", "")
            if pai:
                meld_tiles[a].append(pai)
            # 加杠不新增副露: 更新已有 pon 条目为 kakan (type 4)
            pi = _MAP.get(pai, -1)
            seq = furo_seq[a]
            for i in range(len(seq) - 1, 0, -2):
                if seq[i] == pi and seq[i - 1] == 1:
                    seq[i - 1] = 4
                    break
            just_kan[a] = True
        elif t == "hora":
            w = int(ev["actor"])
            tg = ev.get("target", w)
            is_tsumo = w == tg
            deltas = ev.get("deltas", [0] * 4)
            # 和牌牌: 转换器声明的 machi 优先 (抢杠=加杠牌/岭上自摸=岭上牌 均正确);
            # 回退: 自摸 = 最后摸的牌; 荣和 = 放铳者最后打出的牌
            hp = ev.get("pai", "")
            if hp and hp in _MAP:
                win_tile_by_actor[w] = _MAP[hp]
            elif is_tsumo:
                win_tile_by_actor[w] = _MAP.get(last_draw[w], -1) if last_draw[w] else -1
            else:
                win_tile_by_actor[w] = _MAP.get(last_discard[tg], -1) if last_discard[tg] else -1
            for i in range(4):
                # 双和: 多个 hora 的 deltas 累加（每个只含部分玩家变动）
                kyoku_delta[i] = (kyoku_delta[i] if kyoku_delta[i] is not None else 0) + deltas[i]
                if i == w:
                    kyoku_result[i] = "tsumo" if is_tsumo else "win"
                elif not is_tsumo and i == tg:
                    kyoku_result[i] = "deal_in"
                elif is_tsumo:
                    kyoku_result[i] = "tsumo_loss"
                else:
                    kyoku_result[i] = "pass"
        elif t == "ryukyoku":
            if ev.get("deltas"):
                for i in range(4):
                    kyoku_delta[i] = ev.get("deltas", [0] * 4)[i]
            for i in range(4):
                kyoku_result[i] = "draw"
            ryukyoku_reason = ev.get("reason", "")
            # 流局: 立直供托转入下局 → 立直者仍扣 1000 (riichi_paid 不清零)

    if kyoku_start_row < len(rows):
        _backfill(rows, kyoku_start_row, kyoku_delta, kyoku_result, riichi_paid, win_tile_by_actor, ryukyoku_reason)
    # 局级准入 (ADR-005): 违规局整局丢弃
    all_bad |= bad_kyoku
    if all_bad:
        _DROP_STATS["kyoku_dropped"] += len(all_bad)
        _DROP_STATS["rows_dropped"] += sum(
            1 for r in rows
            if ((int(r["game_id"].rsplit("#", 1)[1]) if "#" in r["game_id"] else 1),
                r["round_idx"]) in all_bad
        )

        def _bad(row) -> bool:
            gid = row["game_id"]
            gk = int(gid.rsplit("#", 1)[1]) if "#" in gid else 1
            return (gk, row["round_idx"]) in all_bad

        rows = [r for r in rows if not _bad(r)]
    return rows


def _backfill(rows: list[dict], start: int, delta: list, result: list, riichi_paid: list | None = None,
              win_tile_by_actor: list | None = None, ryukyoku_reason: str | None = None) -> None:
    rp = riichi_paid or [0, 0, 0, 0]
    wt = win_tile_by_actor or [-1, -1, -1, -1]
    rty = RYU_TYPE.get(ryukyoku_reason, 0) if ryukyoku_reason is not None else -1
    # 全局和牌牌: 本局任一和牌者的和牌牌 (双和取第一张) → 所有行共享
    global_wt = next((v for v in wt if v >= 0), -1)
    for i in range(4):
        d = delta[i] if delta[i] is not None else None
        r = result[i] if result[i] is not None else None
        if d is None and r is None:
            continue
        for j in range(start, len(rows)):
            if rows[j]["actor"] == i:
                if rows[j]["kyoku_pt_delta"] is None:
                    rows[j]["kyoku_pt_delta"] = d - rp[i]
                rows[j]["kyoku_result"] = RESULT_CODE.get(r, -1)
                rows[j]["ryukyoku_type"] = rty
                if rows[j]["win_tile"] == -1 and global_wt >= 0:
                    rows[j]["win_tile"] = global_wt


FLUSH_FILES = 20  # worker 每处理 20 文件写一次 part，控制内存峰值（16GB 机器 6-8 workers 安全）

# 局级准入丢弃审计 (ADR-005 G-1..G-4)：worker 累加, run() 汇总打印
_DROP_STATS = {"kyoku_dropped": 0, "rows_dropped": 0}


def process_files_write(files: list, tmp_dir: Path, part_id: int) -> tuple[int, int, dict]:
    """Worker 分块写 parquet：每 FLUSH_FILES 个文件 flush 一次，降低内存峰值。"""
    rows = []
    n_files = 0
    sub_idx = 0
    for f in files:
        rows.extend(process_file(str(f)))
        n_files += 1
        if n_files % FLUSH_FILES == 0 and rows:
            df = pl.DataFrame(rows, schema=SCHEMA)
            df.write_parquet(tmp_dir / f"part_{part_id:04d}_{sub_idx:04d}.parquet",
                             compression="zstd")
            del df, rows
            rows = []
            sub_idx += 1
    if rows:
        df = pl.DataFrame(rows, schema=SCHEMA)
        df.write_parquet(tmp_dir / f"part_{part_id:04d}_{sub_idx:04d}.parquet",
                         compression="zstd")
    # 返回丢弃审计 (进程内 _DROP_STATS 是本地副本, 在返回前读取)
    return part_id, n_files, dict(_DROP_STATS)


def run(input_dir: str, out_path: str, limit: int | None, workers: int) -> None:
    t0 = time.time()
    files = sorted(
        input_dir / e for e in os.listdir(str(input_dir))
        if e.endswith(".mjai")
    )
    if limit:
        files = files[:limit]
    total = len(files)
    print(f"[etl_v3] {total} files, {workers} workers", flush=True)

    tmp_dir = Path(out_path).parent / f".tmp_{Path(out_path).stem}"
    tmp_dir.mkdir(exist_ok=True)
    batch = max(total // (workers * 4), 1)
    part_counter = [0]
    total_rows = [0]

    with ProcessPoolExecutor(max_workers=workers) as pool:
        futs = []
        pid = 0
        for i in range(0, total, batch):
            pid += 1
            futs.append(pool.submit(process_files_write, files[i:i + batch], tmp_dir, pid))
        drop_total = {"kyoku_dropped": 0, "rows_dropped": 0}
        for fut in as_completed(futs):
            part_id, n_files, drops = fut.result()
            part_counter[0] += 1
            total_rows[0] += n_files
            drop_total["kyoku_dropped"] += drops.get("kyoku_dropped", 0)
            drop_total["rows_dropped"] += drops.get("rows_dropped", 0)
            if part_counter[0] % 20 == 0:
                print(f"  [{total_rows[0]:,} files] {time.time()-t0:.0f}s", flush=True)

    print(f"[etl_v3] 局级准入丢弃 (ADR-005): 局 {drop_total['kyoku_dropped']:,} / "
          f"行 {drop_total['rows_dropped']:,}", flush=True)

    if part_counter[0] == 0:
        print("[etl_v3] no rows!")
        return

    print(f"[etl_v3] merging {part_counter[0]} parts...", flush=True)
    # 流式合并: lazy scan + sink，避免全量载入内存
    pattern = str(tmp_dir / "part_*.parquet")
    df = pl.scan_parquet(pattern).sink_parquet(out_path, compression="zstd")
    total_rows = int(pl.scan_parquet(out_path).select(pl.len().alias("n")).collect().item())
    for p in tmp_dir.glob("part_*.parquet"):
        p.unlink()
    tmp_dir.rmdir()
    mb = os.path.getsize(out_path) / 1e6
    print(f"[etl_v3] DONE {total_rows:,} rows, {mb:.1f} MB, {time.time()-t0:.0f}s")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    run(Path(args.input), args.out, args.limit, args.workers)
