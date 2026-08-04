"""fetch_nodocchi.py — 抓取 nodocchi 凤凰卓统计基准数据 (min=5000, 270 玩家 / ~2000 万局聚合)

调用 nodocchi.moe /api/phoenix_list.php（服务器端已聚合，每次仅 ~30KB JSON）,
对每个指标字段抓取后保存到 data/nodocchi_raw/<field>.json。
"""
import json
import subprocess
import sys
import time
from pathlib import Path

BASE = "https://nodocchi.moe/api/phoenix_list.php"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
OUT = Path(r"D:\tenhoulib\data\nodocchi_raw")
OUT.mkdir(parents=True, exist_ok=True)

# 全部指标字段（PHOENIX_CONFIG.list 提取，去重）
FIELDS = [
    "agariC_", "agariC",          # 和率（降/升序同名）
    "houjuuC_", "houjuuC",        # 铳率
    "riichC_", "riichC",          # 立直率
    "fuuroC_", "fuuroC",          # 副露率
    "tsumoV_",                    # 自摸率
    "nagareVT", "nagareVT_",      # 流局
    "tobiZ_", "tobiZ",            # 击飞
    "ippatsuV_",                  # 一发率
    "pinfuV_",                    # 平和率
    "tanyaoV_",                   # 断幺率
    "akaV", "akaV_",              # 赤宝率
    "doraV", "doraV_",            # 宝牌率
    "yakumanV_",                  # 役满率
    "kanC_", "kanC",              # 杠率
    "riichsenV",                  # 立直宣言率
    "riich_seikou_V",             # 立直成功率
    "damaV_",                     # 默听率
    "toituV", "toituV_",          # 对子率
    "chiitoiV_",                  # 七对率
    "sanshokuV_",                 # 三色率
    "chantaiV_",                  # 全带率
    "rinshan_V_",                 # 岭上率
    "shuushiCT_",                 # 收支
    "houjuuVT",                   # 放铳点数
    "houjuuCT",                   # 铳收支
    "kyoutakuVT",                 # 供托
    "al_nyaku_up_Z",              # all-last 逆转率
    "order_Z",                    # 顺位分布
    "nagaretenpaiV",              # 流局听牌率
    "kaisenC_",                   # 开仙率
    "agariVFT",                   # 和牌点数
]


def fetch(field: str, retries: int = 3) -> dict | None:
    url = f"{BASE}?playernum=4&playlength=0&min=5000&recent=0&field={field}"
    for i in range(retries):
        try:
            p = subprocess.run(
                ["curl.exe", "-s", "-L", "--max-time", "90", "-A", UA,
                 "-H", "Accept: application/json", url],
                capture_output=True, text=True, timeout=120)
            if p.returncode == 0 and p.stdout.strip().startswith("{"):
                return json.loads(p.stdout)
        except Exception:
            pass
        time.sleep(3)
    return None


def main():
    ok = fail = 0
    for f in FIELDS:
        fp = OUT / f"{f}.json"
        if fp.exists():
            ok += 1
            continue
        j = fetch(f)
        if j and j.get("data"):
            fp.write_text(json.dumps(j, ensure_ascii=False), encoding="utf-8")
            ok += 1
            print(f"  {f}: {len(j['data'])} players")
        else:
            fail += 1
            print(f"  {f}: FAIL")
        time.sleep(1.0)
    print(f"\ndone: ok={ok} fail={fail}")


if __name__ == "__main__":
    main()
