"""mem_guard.py — 内存护栏（防 1 亿行 OOM 强制关机，2026-08-04 v2）

三层防护:
  1. preflight(): 运行前估算峰值内存, 超过可用阈值 → 立即拒绝
  2. MemoryWatchdog: 运行中后台线程轮询, 超限 → 设置 abort 标志 (主线程配合检查) 或 raise
  3. guard_child(): 子进程监控, 超限 → kill

v2 改进: watchdog 不在 daemon 线程里直接 raise (主线程可能已结束), 而是:
  - abort() 标志 + raise_if_aborted() 供主线程定期调用
  - 或传入 raise_in_thread=True 强制 raise (主线程仍在时)

16GB 机器教训 (2026-08-03): 1 亿行 eager 全载 = Kernel-Power 41 强制关机 3 次.
"""
from __future__ import annotations

import os
import threading
import time

try:
    import psutil
except ImportError:
    psutil = None

RESERVE_GB = 2.0
MAX_USABLE_RATIO = 0.80
POLL_INTERVAL = 0.5


class MemoryGuardError(RuntimeError):
    pass


def available_mb() -> float:
    if psutil is None:
        return 999999.0
    return psutil.virtual_memory().available / 2**20


def process_rss_mb(pid: int | None = None) -> float:
    if psutil is None:
        return 0.0
    try:
        return psutil.Process(pid or os.getpid()).memory_info().rss / 2**20
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return 0.0


def usable_limit_mb() -> float:
    avail = available_mb()
    return min(avail - RESERVE_GB * 1024, avail * MAX_USABLE_RATIO)


def estimate_parquet_mem(path: str, n_rows: int | None = None, expand: float = 6.0) -> float:
    import os
    size = os.path.getsize(path)
    est = size * expand / 2**20
    if n_rows is not None:
        est = min(est, est * n_rows / max(1, _approx_rows(path)))
    return est


def _approx_rows(path: str) -> int:
    try:
        import pyarrow.parquet as pq
        return pq.ParquetFile(path).metadata.num_rows
    except Exception:
        return 1_000_000


def preflight(need_mb: float, tag: str = "") -> None:
    if psutil is None:
        return
    limit = usable_limit_mb()
    avail = available_mb()
    if need_mb > limit:
        raise MemoryGuardError(
            f"[preflight] {tag} 估算 {need_mb:.0f}MB > 安全上限 {limit:.0f}MB "
            f"(available={avail:.0f}MB). 拒绝运行.")


class MemoryWatchdog:
    """运行中内存监控.

    用法:
      wd = MemoryWatchdog(tag="etl", raise_in_thread=False)
      wd.start()
      while working:
          wd.raise_if_aborted()     # 主循环内定期调用
          ...
      wd.stop()
    """

    def __init__(self, soft_mb: float | None = None, poll: float = POLL_INTERVAL,
                 tag: str = "", raise_in_thread: bool = False):
        self.limit_mb = soft_mb or usable_limit_mb()
        self.poll = poll
        self.tag = tag
        self.raise_in_thread = raise_in_thread
        self._abort = threading.Event()
        self._last_error: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._start_avail = available_mb()

    def start(self):
        if psutil is None:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None

    def raise_if_aborted(self):
        if self._abort.is_set():
            raise MemoryGuardError(self._last_error or "内存超限")

    @property
    def aborted(self) -> bool:
        return self._abort.is_set()

    def _loop(self):
        while not self._stop.is_set():
            rss = process_rss_mb()
            avail = available_mb()
            err = None
            if rss > self.limit_mb:
                err = (f"[watchdog:{self.tag}] 进程 RSS {rss:.0f}MB > 上限 "
                       f"{self.limit_mb:.0f}MB. 立即中断.")
            elif avail < RESERVE_GB * 1024:
                err = (f"[watchdog:{self.tag}] 系统可用 {avail:.0f}MB < "
                       f"保留 {RESERVE_GB}GB. 立即中断.")
            if err:
                self._last_error = err
                self._abort.set()
                self._stop.set()
                if self.raise_in_thread:
                    raise MemoryGuardError(err)
                return
            time.sleep(self.poll)


def guard_child(proc, tag: str = "", soft_mb: float | None = None,
                poll: float = POLL_INTERVAL, on_kill=None) -> None:
    """监控子进程, 超限 kill. 阻塞直到进程结束."""
    limit = soft_mb or usable_limit_mb()
    while proc.poll() is None:
        try:
            rss = process_rss_mb(proc.pid)
        except Exception:
            rss = 0
        avail = available_mb()
        if rss > limit:
            proc.kill()
            if on_kill:
                on_kill(f"[guard_child] {tag} RSS {rss:.0f}MB > {limit:.0f}MB, 已 kill")
            raise MemoryGuardError(f"[guard_child] {tag} 超限已 kill")
        if avail < RESERVE_GB * 1024:
            proc.kill()
            if on_kill:
                on_kill(f"[guard_child] {tag} 系统内存不足, 已 kill")
            raise MemoryGuardError(f"[guard_child] {tag} 系统内存不足已 kill")
        time.sleep(poll)
