"""POSIX case isolation. Parent owns deadlines, result acceptance and cleanup.

Fork preserves injected selftest callables. Cases start after scratch ownership is
registered. Result files avoid pipe backpressure. Bounds assume a responsive OS;
descendants deliberately escaping the process group are outside this contract.
"""
from dataclasses import asdict
import json
import math
import multiprocessing
import os
from pathlib import Path
import signal
import sys
import time
import traceback
import uuid

from scratch import atomic_write_json

DEFAULT_TIMEOUTS = {"browser": 300.0, "bridge": 300.0, "assets": 7200.0}


def group_running(pgid):
    """Live group members (Linux zombies no longer execute or own scratch)."""
    if not isinstance(pgid, int) or pgid <= 0:
        return False
    if Path("/proc").is_dir():
        for stat in Path("/proc").glob("[0-9]*/stat"):
            try:
                fields = stat.read_text().rsplit(")", 1)[1].split()
                if int(fields[2]) == pgid and fields[0] != "Z":
                    return True
            except (OSError, ValueError, IndexError):
                continue
        return False
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _signal_group(pid, sig):
    try:
        os.killpg(pid, sig)
    except ProcessLookupError:
        pass


def _worker(case, ctx, result_path, log_path, gate, parent_pid):
    os.setsid()
    # Parent may die before releasing the gate: never start unregistered work.
    while not gate.wait(.1):
        if os.getppid() != parent_pid:
            return
    if os.getppid() != parent_pid:
        return
    with open(log_path, "w", buffering=1, encoding="utf-8") as log:
        os.dup2(log.fileno(), 1)
        os.dup2(log.fileno(), 2)
        sys.stdout = log
        sys.stderr = log
        from cases import BlockedError, CaseResult
        try:
            result = case.check(ctx)
            if not isinstance(result, CaseResult):
                result = CaseResult("FAIL", f"用例返回非 CaseResult: {result!r}")
        except BlockedError as error:
            result = CaseResult("BLOCKED", f"环境阻塞: {error}")
        except Exception:
            result = CaseResult("FAIL", "异常:\n" + traceback.format_exc())
        atomic_write_json(result_path, asdict(result))


def execute(case, ctx, timeout, heartbeat=None):
    """Return (CaseResult, supervision metadata); never accept a bad exit as PASS."""
    from cases import CaseResult
    if os.name != "posix" or "fork" not in multiprocessing.get_all_start_methods():
        return CaseResult("BLOCKED", "用例监管需要POSIX fork/process groups"), {}
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("case timeout must be finite and positive")
    work = ctx.run_dir / "case-process" / uuid.uuid4().hex
    work.mkdir(parents=True)
    result_path, log_path = work / "result.json", work / "output.log"
    mp = multiprocessing.get_context("fork")
    gate = mp.Event()
    proc = mp.Process(target=_worker, args=(case, ctx, result_path, log_path,
                                           gate, os.getpid()))
    sys.stdout.flush()
    sys.stderr.flush()
    start = time.monotonic()
    proc.start()
    pid = proc.pid
    meta = {"pid": pid, "timeoutSeconds": timeout, "timedOut": False,
            "log": str(log_path), "result": str(result_path)}
    try:
        if ctx.scratch is not None:
            ctx.scratch.write_owner(ctx.scratch_dir, casePgid=pid)
        gate.set()
        while proc.is_alive():
            elapsed = time.monotonic() - start
            if heartbeat is not None:
                heartbeat({**meta, "elapsedSeconds": round(elapsed, 3)})
            elapsed = time.monotonic() - start
            if elapsed >= timeout:
                meta["timedOut"] = True
                break
            proc.join(min(.25, timeout - elapsed))
        # Completion observed after the deadline must not become a late PASS,
        # including when a heartbeat/disk write delayed the parent observer.
        if time.monotonic() - start >= timeout:
            meta["timedOut"] = True
    finally:
        # Includes normal-return descendants. Do not leave browsers/builders alive.
        _signal_group(pid, signal.SIGTERM)
        if proc.is_alive():
            proc.terminate()  # also covers failure before setsid
        until = time.monotonic() + .5
        while group_running(pid) and time.monotonic() < until:
            time.sleep(.025)
        _signal_group(pid, signal.SIGKILL)
        if proc.is_alive():
            proc.kill()
        proc.join(2)
        until = time.monotonic() + .5
        while group_running(pid) and time.monotonic() < until:
            time.sleep(.025)
        meta["exitCode"] = proc.exitcode
        meta["cleanupComplete"] = not proc.is_alive() and not group_running(pid)
        if not meta["cleanupComplete"]:
            # Survives heartbeat/progress I/O exceptions before a result returns.
            ctx.cleanup_pending = dict(meta)
        if ctx.scratch is not None and meta["cleanupComplete"]:
            ctx.scratch.write_owner(ctx.scratch_dir, casePgid=None)
        if not proc.is_alive():
            proc.close()
    meta["elapsedSeconds"] = round(time.monotonic() - start, 3)
    if not meta["cleanupComplete"]:
        result = CaseResult("FAIL", f"用例进程组清理未完成，须保留scratch并停止后续用例: {meta}")
    elif meta["timedOut"]:
        result = CaseResult("FAIL", f"用例超时（预算 {timeout:g}s），已终止所属进程组")
    elif meta["exitCode"] != 0 or not meta["cleanupComplete"]:
        result = CaseResult("FAIL", f"用例进程异常退出/清理未完成: {meta}")
    else:
        try:
            result = CaseResult(**json.loads(result_path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            result = CaseResult("FAIL", "用例进程无有效结果协议")
    result.artifacts = list(result.artifacts) + [str(log_path)]
    return result, meta
