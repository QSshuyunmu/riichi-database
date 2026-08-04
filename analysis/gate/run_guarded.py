"""run_guarded.py — 带内存护栏运行任意脚本 (统一入口)

用法: python run_guarded.py <script.py> [args...]
护栏: 子进程 RSS>4GB 或 系统可用<1.5GB → kill + 报错
"""
import subprocess
import sys
import time
import psutil

PY = r"C:\Users\HP\AppData\Local\Programs\Python\Python313\python.exe"

script = sys.argv[1]
args = sys.argv[2:]

print(f"[guard] 运行 {script} ...", flush=True)
t0 = time.time()
p = subprocess.Popen([PY, script, *args], stdout=subprocess.PIPE,
                     stderr=subprocess.STDOUT, text=True,
                     encoding="utf-8", errors="replace")
peak = 0
killed = False
lines = []
while True:
    line = p.stdout.readline()
    if line:
        lines.append(line.rstrip())
    if p.poll() is not None:
        break
    try:
        peak = max(peak, psutil.Process(p.pid).memory_info().rss / 2**20)
        if psutil.virtual_memory().available / 2**20 < 1536:
            p.kill()
            killed = True
            print(f"\n[guard] 系统可用内存 <1.5GB, 已 kill", flush=True)
            break
        if peak > 4096:
            p.kill()
            killed = True
            print(f"\n[guard] RSS {peak:.0f}MB > 4GB, 已 kill", flush=True)
            break
    except Exception:
        pass
    time.sleep(0.5)
status = "KILLED" if killed else f"exit={p.returncode}"
print(f"--- {script}: {status}, peak={peak:.0f}MB, {(time.time()-t0)/60:.1f}min ---", flush=True)
sys.exit(1 if killed else (p.returncode or 0))
