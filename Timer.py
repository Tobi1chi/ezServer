import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional, List


@dataclass
class _TimerInfo:
    interval_ms: int
    callback: Callable
    single_shot: bool
    timer: threading.Timer


class TimerManager:
    """
    Qt-free 版本的 TimerManager：
    - 使用 threading.Timer 实现定时器
    - 使用 time.perf_counter() 实现秒表
    """

    def __init__(self):
        self._timers: Dict[str, _TimerInfo] = {}
        self._stopwatches: Dict[str, float] = {}
        self._lock = threading.Lock()

    # ---------- 定时器部分 ----------

    def _run_timer(self, name: str):
        """内部方法：定时器时间到了之后调用"""
        with self._lock:
            info = self._timers.get(name)
            if info is None:
                return
            callback = info.callback
            interval_ms = info.interval_ms
            single_shot = info.single_shot

        # 在锁外执行回调，避免回调里阻塞导致其他操作卡住
        try:
            callback()
        except Exception as e:
            # 这里可以改成 logging
            print(f"[TimerManager] Error in timer '{name}': {e}")

        # 如果是循环定时器，则重新启动
        if not single_shot:
            with self._lock:
                # 可能在回调里 stop_timer 了，这里要再确认一下
                if name not in self._timers:
                    return
                t = threading.Timer(interval_ms / 1000.0, self._run_timer, args=(name,))
                self._timers[name].timer = t
                t.start()

    def start_timer(self, name: str, interval_ms: int, callback: Callable, single_shot: bool = False):
        """
        启动一个命名定时器。
        如果同名定时器已经存在，则先停止再替换。
        """
        with self._lock:
            # 如果已经存在，先停掉旧的
            if name in self._timers:
                self._timers[name].timer.cancel()

            t = threading.Timer(interval_ms / 1000.0, self._run_timer, args=(name,))
            info = _TimerInfo(
                interval_ms=interval_ms,
                callback=callback,
                single_shot=single_shot,
                timer=t,
            )
            self._timers[name] = info
            t.start()

    def stop_timer(self, name: str) -> bool:
        """停止并移除指定名字的定时器。返回是否成功停止。"""
        with self._lock:
            info = self._timers.pop(name, None)
            if info is None:
                return False
            info.timer.cancel()
            return True

    def is_timer_active(self, name: str) -> bool:
        """检查指定名字的定时器是否存在（粗略的“是否在运行”）。"""
        with self._lock:
            return name in self._timers

    def list_timers(self) -> List[str]:
        """返回当前所有定时器的名字（调试用）。"""
        with self._lock:
            return list(self._timers.keys())

    def stop_all_timers(self):
        """停止所有定时器 & 清空秒表"""
        with self._lock:
            for info in self._timers.values():
                info.timer.cancel()
            self._timers.clear()
            self._stopwatches.clear()

    # ---------- 秒表部分 ----------

    def start_stopwatch(self, name: str) -> bool:
        """启动一个秒表（仅用于计时，不会触发回调）。"""
        with self._lock:
            if name in self._stopwatches:
                return False
            self._stopwatches[name] = time.perf_counter()
            return True

    def get_elapsed_time(self, name: str) -> Optional[int]:
        """
        获取某个秒表已过去的时间（毫秒）。
        若不存在返回 None。
        """
        with self._lock:
            start = self._stopwatches.get(name)
            if start is None:
                return None
            now = time.perf_counter()
            return int((now - start) * 1000)

    def stop_stopwatch(self, name: str) -> Optional[int]:
        """停止秒表并返回耗时（毫秒），不存在则返回 None。"""
        with self._lock:
            start = self._stopwatches.pop(name, None)
        if start is None:
            return None
        now = time.perf_counter()
        return int((now - start) * 1000)

    def is_stopwatch_running(self, name: str) -> bool:
        """检查秒表是否在运行。"""
        with self._lock:
            return name in self._stopwatches

tm = TimerManager()