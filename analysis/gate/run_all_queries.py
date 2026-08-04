"""run_all_queries.py — 批量重跑查询族 (带内存护栏)

逐个运行: baseline_queries / furo_seq_queries / hata_queries / inferred_queries /
          l3_queries / pattern_queries / reading_queries
每脚本: 子进程监控 (RSS>4GB 或 系统可用<1.5GB → kill)
"""
import subprocess
import sys
import time
import psutil

PY = r"C:\Users\HP\AppData\Local\Programs\Python\Python313\python.exe"
ROOT = r"D:\tenhoulib"

SCRIPTS = [
    "baseline_queries.py",
    "furo_seq_queries.py",
    "hata_queries.py",
    "inferred_queries.py",
    "l3_queries.py",
    "pattern_queries.py",
    "reading_queries.py",
]

for script in SCRIPTS:
    print(f"\n{'=' * 56}\n=== {script} ===\n{'=' * 56}", flush=True)
    t0 = time.time()
    p = subprocess.Popen(
        [PY, f"{ROOT}\\{script}"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace")
    peak = 0
    killed = False
    while True:
        line = p.stdout.readline()
        if line:
            sys.stdout.write(line)
        if p.poll() is not None:
            break
        try:
            peak = max(peak, psutil.Process(p.pid).memory_info().rss / 2**20)
            if psutil.virtual_memory().available / 2**20 < 1536:
                p.kill()
                killed = True
                print(f"\n[guard] {script}: 系统可用内存 <1.5GB, 已 kill", flush=True)
                break
            if peak > 4096:
                p.kill()
                killed = True
                print(f"\n[guard] {script}: RSS {peak:.0f}MB > 4GB, 已 kill", flush=True)
                break
        except Exception:
            pass
        time.sleep(0.5)
    status = "KILLED" if killed else f"exit={p.returncode}"
    print(f"  --- {script}: {status}, peak={peak:.0f}MB, {(time.time()-t0)/60:.1f}min ---", flush=True)

print("\nALL DONE")
