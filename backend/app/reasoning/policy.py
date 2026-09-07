"""LLM 刷新兜底策略（阶段 1，P011/D028）：超时/预算/并发/熔断/优先级/单飞参数与状态。

- 参数均可用 env 覆盖（backend/.env 或 shell）。
- 熔断只数"供应商网络级降级"（DegradationError）；本地配置/解析错误不计（避免把配置错当故障熔掉全批）。
- CircuitBreaker 注入 now 便于单测。
"""
import os
import threading
import time
import urllib.error

DEFAULT_TIMEOUT = 10.0
DEFAULT_BUDGET = 20.0
DEFAULT_CONCURRENCY = 3
DEFAULT_CIRCUIT_FAILS = 3
DEFAULT_CIRCUIT_WINDOW = 60.0
DEFAULT_CIRCUIT_COOLDOWN = 30.0

TYPE_PRIORITY = {"problem": 0, "opportunity": 1, "change": 2}


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return default


def _i(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name) or default)
    except ValueError:
        return default


def timeout_secs() -> float:
    return _f("DORA_LLM_TIMEOUT", DEFAULT_TIMEOUT)


def budget_secs() -> float:
    return _f("DORA_LLM_BUDGET_SECS", DEFAULT_BUDGET)


def concurrency() -> int:
    return max(1, _i("DORA_LLM_CONCURRENCY", DEFAULT_CONCURRENCY))


def circuit_fails() -> int:
    return max(1, _i("DORA_LLM_CIRCUIT_FAILS", DEFAULT_CIRCUIT_FAILS))


def circuit_window() -> float:
    return _f("DORA_LLM_CIRCUIT_WINDOW", DEFAULT_CIRCUIT_WINDOW)


def circuit_cooldown() -> float:
    return _f("DORA_LLM_CIRCUIT_COOLDOWN", DEFAULT_CIRCUIT_COOLDOWN)


class DegradationError(Exception):
    """供应商网络级降级（超时/连接失败/5xx/429）——熔断只统计这类。"""


class CircuitOpenError(DegradationError):
    """熔断开启时快速失败（不触网）。"""


def is_degraded(exc: BaseException) -> bool:
    """外部服务网络级故障判定：429/5xx/超时/URLError（注意 HTTPError 是 URLError 子类，先判 HTTP）。"""
    import socket
    if isinstance(exc, (DegradationError, CircuitOpenError)):
        return True
    if isinstance(exc, urllib.error.HTTPError):  # 先于 URLError
        return exc.code == 429 or exc.code >= 500
    if isinstance(exc, (urllib.error.URLError, socket.timeout, TimeoutError)):
        return True
    return False


def priority_key(insight: dict) -> tuple:
    return TYPE_PRIORITY.get(insight.get("type"), 9), insight.get("id", "")


class CircuitBreaker:
    """滑动窗口失败计数熔断：窗口内失败 ≥N → open（冷却期后自动 half-close 探测）。"""

    def __init__(self, now=None):
        self._now = now or time.monotonic
        self._lock = threading.Lock()
        self._fail_ts: list[float] = []
        self._open_until = 0.0
        self.fails = circuit_fails()
        self.window = circuit_window()
        self.cooldown = circuit_cooldown()

    def _prune(self, ts: float) -> None:
        cutoff = ts - self.window
        self._fail_ts = [t for t in self._fail_ts if t > cutoff]

    def record_failure(self) -> None:
        with self._lock:
            ts = self._now()
            self._prune(ts)
            self._fail_ts.append(ts)
            if len(self._fail_ts) >= self.fails:
                self._open_until = ts + self.cooldown

    def record_success(self) -> None:
        with self._lock:
            self._fail_ts = []
            self._open_until = 0.0

    def is_open(self) -> bool:
        with self._lock:
            ts = self._now()
            self._prune(ts)
            if ts < self._open_until:
                return True
            if self._open_until and ts >= self._open_until:
                # 冷却结束：自动复位为 closed（下次调用即探测）
                self._open_until = 0.0
                self._fail_ts = []
            return False

    def reset_for_tests(self) -> None:
        with self._lock:
            self._fail_ts = []
            self._open_until = 0.0


# 进程级默认熔断（llm.py / cache.refresh 共用）
breaker = CircuitBreaker()
