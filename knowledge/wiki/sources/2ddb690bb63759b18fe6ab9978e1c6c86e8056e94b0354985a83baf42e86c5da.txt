"""V4-T3 周期调度：单实例守护线程，每分钟评估到期的 daily/weekly 委托。

- daily 09:00：当日已到 09:00 且今天尚未检查过 → 评估一次（防重复）。
- weekly：周一且本周尚未检查过 → 评估一次。
- 单实例内存线程即可（D009：Redis/Celery 仍推迟）；多实例前不引入外部依赖。
"""
import threading
import time
from datetime import datetime, timezone

from app.repository import Repository
from app.watch.evaluator import evaluate_one, _now_iso


def _parse_dt(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _is_due(target: dict, now: datetime) -> bool:
    """到期判断（纯函数，可注入 now 单测）。now 应带 tz。"""
    freq = target.get("frequency")
    if target.get("status") != "watching":
        return False
    last = _parse_dt(target.get("last_checked_at") or "")
    if freq == "daily 09:00":
        if last is not None and last.date() == now.date():
            return False
        return (now.hour, now.minute) >= (9, 0)
    if freq == "weekly":
        if last is not None and last.isocalendar()[:2] == now.isocalendar()[:2]:
            return False
        return now.weekday() == 0
    return False


def _tick_once() -> dict:
    """跑一轮：评估所有到期的周期委托；返回计数。"""
    repo = Repository()
    targets = repo.list_watch_targets()
    now = datetime.now(timezone.utc)
    due = [t for t in targets if _is_due(t, now)]
    if not due:
        return {"checked": 0}
    from app.engine.engine import run_engine
    insights = run_engine(repo)["insights"]
    checked = 0
    for t in due:
        evaluate_one(repo, t, insights)
        repo.touch_watch_target(t["id"], _now_iso())
        checked += 1
    return {"checked": checked}


_started = False
_running = False
_thread: threading.Thread | None = None


def start() -> None:
    """启动单例调度线程（幂等）。启动时先补跑一次，再进入每分钟循环。"""
    global _started, _running, _thread
    if _started:
        return
    _started = True
    _running = True

    def _loop():
        try:
            _tick_once()
        except Exception as exc:  # 调度辅助逻辑失败不崩服务
            print(f"[watch.scheduler] first tick skipped: {exc}")
        while _running:
            time.sleep(60)
            try:
                _tick_once()
            except Exception as exc:
                print(f"[watch.scheduler] tick skipped: {exc}")

    _thread = threading.Thread(target=_loop, name="dora-watch-scheduler", daemon=True)
    _thread.start()


def stop() -> None:
    global _running
    _running = False
