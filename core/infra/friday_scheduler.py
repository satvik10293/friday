"""
friday_scheduler.py — Friday 3.0
Task scheduler. Ported from v2, upgraded with signal bus integration.
every_seconds / every_minutes / at_time / on_weekday / once_after
"""

import sys
import time
import threading
import datetime
import logging
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

log = logging.getLogger("friday.scheduler")

try:
    import schedule
    _HAS_SCHEDULE = True
except ImportError:
    _HAS_SCHEDULE = False
    log.warning("schedule not installed. Run: pip install schedule")

_jobs    = {}
_running = False
_thread  = None


def _wrap(name, task):
    def wrapped():
        log.debug("Running: '%s' at %s", name, datetime.datetime.now().strftime('%H:%M:%S'))
        try:
            task()
        except Exception as e:
            log.error("Task '%s' error: %s", name, e)
            try:
                from core.infra.friday_signal import get_bus, Signal
                get_bus().emit_sync(Signal.MODULE_ERROR,
                    data={"module": "scheduler", "task": name, "error": str(e)},
                    source="scheduler")
            except Exception:
                pass
    return wrapped


def every_seconds(seconds, task, name=None):
    if not _HAS_SCHEDULE: return
    name = name or getattr(task, '__name__', 'task')
    _jobs[name] = schedule.every(seconds).seconds.do(_wrap(name, task))
    log.info("Scheduled '%s' every %ds", name, seconds)

def every_minutes(minutes, task, name=None):
    if not _HAS_SCHEDULE: return
    name = name or getattr(task, '__name__', 'task')
    _jobs[name] = schedule.every(minutes).minutes.do(_wrap(name, task))
    log.info("Scheduled '%s' every %dm", name, minutes)

def every_hours(hours, task, name=None):
    if not _HAS_SCHEDULE: return
    name = name or getattr(task, '__name__', 'task')
    _jobs[name] = schedule.every(hours).hours.do(_wrap(name, task))

def at_time(time_str, task, name=None):
    if not _HAS_SCHEDULE: return
    name = name or getattr(task, '__name__', 'task')
    _jobs[name] = schedule.every().day.at(time_str).do(_wrap(name, task))
    log.info("Scheduled '%s' daily at %s", name, time_str)

def on_weekday(day, time_str, task, name=None):
    if not _HAS_SCHEDULE: return
    name    = name or getattr(task, '__name__', 'task')
    day_obj = getattr(schedule.every(), day.lower())
    _jobs[name] = day_obj.at(time_str).do(_wrap(name, task))

def once_after(seconds, task, name=None):
    name = name or getattr(task, '__name__', 'task')
    def _run():
        time.sleep(seconds)
        log.debug("One-time task: '%s'", name)
        task()
    threading.Thread(target=_run, daemon=True, name=f"once-{name}").start()

def cancel(name):
    if name in _jobs and _HAS_SCHEDULE:
        schedule.cancel_job(_jobs.pop(name))

def list_jobs():
    return list(_jobs.keys())

def clear_all():
    if _HAS_SCHEDULE:
        schedule.clear()
    _jobs.clear()

def start(blocking=False):
    global _running, _thread
    if _running: return
    _running = True
    if blocking:
        _run_loop()
    else:
        _thread = threading.Thread(target=_run_loop, daemon=True, name="friday-scheduler")
        _thread.start()
    log.info("Scheduler started")

def stop():
    global _running
    _running = False
    log.info("Scheduler stopped")

def _run_loop():
    while _running:
        if _HAS_SCHEDULE:
            schedule.run_pending()
        time.sleep(0.5)


# ── Built-in tasks ────────────────────────────────────────────────────────────

def task_heartbeat():
    try:
        from core.infra.friday_signal import get_bus, Signal
        get_bus().emit_sync(Signal.HEARTBEAT, source="scheduler")
    except Exception:
        pass

def task_remind(message):
    try:
        from core.io.friday_notify import get_notify
        get_notify().reminder(message)
    except Exception as e:
        log.warning("Reminder failed: %s", e)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    print("\n[friday_scheduler] Test — heartbeat every 2s for 8s\n")
    count = [0]
    def tick():
        count[0] += 1
        print(f"  ♥ tick {count[0]}")
    every_seconds(2, tick, "tick")
    once_after(7, lambda: print("  ★ one-time fired"), "one_time")
    start()
    time.sleep(8)
    stop()
    print(f"\n[friday_scheduler] {count[0]} ticks — Done ✓\n")
