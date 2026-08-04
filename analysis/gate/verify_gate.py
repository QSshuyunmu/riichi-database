"""verify_gate.py — 重建门禁流水线编排器（L0-L3，防全量重建后才发现 bug）

原则（ADR-006）：修改转换器/ETL 后必须过 L0→L3 门禁，全部 PASS 才允许 L4 全量重建。

层级:
  L0 单元/锚点测试        converter_anchor_test.py        (~1s, 函数级)
  L1 黄金样本集           200 精选 XML (AGARI 交叉验证)    (~1min, 稀有场景)
  L2 小样本全维度         invariant + regression           (~5min)
  L3 统计 sanity          stats_sanity.py                  (~6min)

内存护栏 (mem_guard.py):
  - 每个子命令运行前 preflight 估算 (parquet 大小 × 膨胀系数)
  - 子进程运行时 guard_child 轮询 RSS + 系统可用内存, 超限 kill + 报 FAIL
  - 本进程 MemoryWatchdog 兜底

用法:
  python verify_gate.py --level L0|L1|L2|L3 [--data parquet] [--xml-dir games] [--n 2000]
  python verify_gate.py --all --data v3_xxx.parquet        # L0-L3 顺序执行
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from mem_guard import MemoryGuardError, MemoryWatchdog, estimate_parquet_mem, guard_child, preflight  # noqa: E402

ROOT = Path(__file__).parent
PY = r"C:\Users\HP\AppData\Local\Programs\Python\Python313\python.exe"


def run_cmd(cmd: list, timeout: int = 3600, need_mb: float = 0,
            tag: str = "") -> tuple[int, str, float]:
    """带内存护栏运行子命令: preflight 估算 + 运行中监控.

    护栏规则:
      - 子进程 RSS 上限 = max(4GB, 可用上限)  (子进程 1-2GB 是正常的, 4GB 才危险)
      - 系统可用内存 < 2GB → kill  (防系统级 OOM 强制关机)
    """
    if need_mb > 0:
        preflight(need_mb=need_mb, tag=tag)
    t0 = time.time()
    proc = subprocess.Popen([PY, *cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            encoding="utf-8", errors="replace", text=True)
    out_buf = []
    killed = False
    rss_limit = 4096.0  # 子进程 RSS 硬上限 4GB (16GB 机器)
    try:
        import psutil
        while True:
            try:
                line = proc.stdout.readline()
            except Exception:
                line = ""
            if line:
                out_buf.append(line)
                continue
            if proc.poll() is not None:
                break
            try:
                rss = psutil.Process(proc.pid).memory_info().rss / 2**20
                avail = psutil.virtual_memory().available / 2**20
            except Exception:
                rss, avail = 0, 0
            if rss > rss_limit:
                proc.kill()
                killed = True
                out_buf.append(f"\n[guard] {tag} 子进程 RSS {rss:.0f}MB > {rss_limit:.0f}MB, 已 kill\n")
                break
            if avail < 2.0 * 1024:
                proc.kill()
                killed = True
                out_buf.append(f"\n[guard] {tag} 系统可用内存 {avail:.0f}MB < 2GB, 已 kill\n")
                break
            time.sleep(0.5)
    except MemoryGuardError as e:
        proc.kill()
        killed = True
        out_buf.append(f"\n[guard] {e}\n")
    finally:
        stderr_tail = ""
        try:
            stderr_tail = proc.stderr.read() if proc.stderr else ""
        except Exception:
            pass
        out_buf.append(stderr_tail)
        proc.wait(timeout=30)

    out = "".join(out_buf).strip()
    rc = -9 if killed else (proc.returncode or 0)
    return rc, out, time.time() - t0


def l0() -> tuple[bool, str]:
    code, out, dt = run_cmd([str(ROOT / "converter_anchor_test.py")], timeout=300, tag="L0")
    ok = code == 0
    return ok, f"L0 锚点测试 ({dt:.1f}s)\n{out[-1500:]}"


def l1(golden_set: str, xml_dir: str) -> tuple[bool, str]:
    code, out, dt = run_cmd([
        str(ROOT / "verify_golden.py"), "--set", golden_set, "--xml-dir", xml_dir,
    ], timeout=1800, tag="L1")
    ok = code == 0
    return ok, f"L1 黄金样本集 ({dt:.1f}s)\n{out[-1500:]}"


def l2(data: str, n: int) -> tuple[bool, str]:
    ok_all = True
    msgs = []
    # invariant 全量 8GB (1.40 streaming 引擎 group_by 物化) → 门禁用 sample 截断, 全量留 L4
    inv_sample = min(n, 5_000_000)
    for name, script, args, mb in [
        ("不变量", "invariant_check.py", ["--data", data, "--sample", str(inv_sample)],
         estimate_parquet_mem(data, n_rows=inv_sample, expand=3.0)),
        ("回归探针", "regression_probes.py", ["--data", data, "--sample", str(n)],
         estimate_parquet_mem(data, n_rows=n, expand=8.0)),
    ]:
        code, out, dt = run_cmd([str(ROOT / script), *args], timeout=1800,
                                need_mb=mb, tag=f"L2/{name}")
        ok = code == 0
        ok_all &= ok
        sample_val = args[args.index("--sample") + 1] if "--sample" in args else "全量"
        msgs.append(f"[{'PASS' if ok else 'FAIL'}] {name} ({dt:.1f}s, est={mb:.0f}MB, sample={sample_val})")
        if not ok:
            msgs.append(out[-800:])
    return ok_all, "L2 小样本全维度\n" + "\n".join(msgs)


def l3(data: str) -> tuple[bool, str]:
    # 门禁用 500 万行截断 (统计指标稳定 + 内存安全); 全量统计留 L4 验收
    sample = 5_000_000
    est = estimate_parquet_mem(data, n_rows=sample, expand=6.0)
    code, out, dt = run_cmd(
        [str(ROOT / "stats_sanity.py"), "--data", data, "--mode", "warning",
         "--sample", str(sample)],
        timeout=3600, need_mb=est, tag="L3")
    ok = code == 0
    return ok, f"L3 统计 sanity ({dt:.1f}s, est={est:.0f}MB, sample={sample})\n{out[-1500:]}"


def main():
    ap = argparse.ArgumentParser(description="重建门禁流水线 L0-L3 (内存护栏内置)")
    ap.add_argument("--level", choices=["L0", "L1", "L2", "L3"])
    ap.add_argument("--all", action="store_true", help="顺序执行 L0-L3")
    ap.add_argument("--data", default="", help="parquet 路径 (L2/L3 需要)")
    ap.add_argument("--xml-dir", default=str(ROOT / "games"), help="XML 源目录 (L1 需要)")
    ap.add_argument("--golden-set", default=str(ROOT / "data" / "golden_set.json"))
    ap.add_argument("--n", type=int, default=2_000_000, help="L2 回归截断行数")
    args = ap.parse_args()

    levels = ["L0", "L1", "L2", "L3"] if args.all else [args.level]
    if not args.data and ("L2" in levels or "L3" in levels):
        print("L2/L3 需要 --data")
        sys.exit(2)

    # 本进程 watchdog 兜底: 只检查系统可用内存 (主进程自身很小)
    wd = MemoryWatchdog(tag="verify_gate", soft_mb=8.0 * 1024)
    wd.start()

    all_ok = True
    for lv in levels:
        print(f"\n{'=' * 60}\n=== {lv} ===\n{'=' * 60}")
        if lv == "L0":
            ok, msg = l0()
        elif lv == "L1":
            ok, msg = l1(args.golden_set, args.xml_dir)
        elif lv == "L2":
            ok, msg = l2(args.data, args.n)
        else:
            ok, msg = l3(args.data)
        print(msg)
        all_ok &= ok
        try:
            wd.raise_if_aborted()
        except MemoryGuardError as e:
            print(f"\n[guard] {e}")
            all_ok = False
            break

    wd.stop()
    print(f"\n{'=' * 60}\n门禁结果: {'ALL PASS' if all_ok else '存在 FAIL — 修复后再全量'}")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
