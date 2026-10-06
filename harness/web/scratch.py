"""HARNESS-01：harness scratch 生命周期与磁盘预算（loop-harness-2026-09-26 §4）。

背景：09-23 门禁中间构建累积 22G 填满 40G 根盘（ENOSPC）。可再生工作副本
（det/sens/tamper 等）此前直接落在 out/web-harness/<runId>，与报告/截图证据
混放，无回收与容量控制。

本模块把"证据"（run_dir，保留）与"可再生 scratch"（本模块管理，PASS 回收）
分开：每个 run 一个独占 scratch 目录（默认系统临时目录下 bugbits-harness/
bugbits-<runId>，可用 --scratch-root / BUGBITS_HARNESS_SCRATCH 覆盖——注意
/tmp 与项目可能同根分区，换路径不代替回收+限额，两者都实现）。

安全边界：
- recycle() 只删 scratch 根内、带 owner/work 标记的目录；根自身与根外路径拒绝；
- 删除不跟随软链接（sens-root 内有指向原始数据的 symlink，穿透=删原资产）；
- 活动判定靠 owner 的 pid 存活，不靠目录年龄独断；孤儿（崩溃残留）由下次
  run 启动时恢复回收；
- FAIL 保留的诊断受 bytes/count/age 上限约束（保留策略可以用年龄，因为这只
  管已标 kept 的目录，不用来判定"在跑"）。

容量：create/预算检查可注入 free 值与时钟（测试用）；完全无空间时调用方仍须
至少非零退出+标准错误（见 run.py），不承诺写不出的报告。

SCRATCH-03（2026-09-27 审查修复）：finish() 返回最终实际处置——策略淘汰后
核对存在性，报 evicted + 触发策略（bytes/count/age）+ 真实可用路径；kept 时
keptSubdirs 只含仍存在的目录。容量上限不因报告而关闭（淘汰本身合理，缺陷
曾是"报告 kept 而文件已不存在"）。
"""
import errno
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

SCRATCH_ROOT_ENV = "BUGBITS_HARNESS_SCRATCH"
MIN_FREE_MB_ENV = "BUGBITS_HARNESS_MIN_FREE_MB"
KEEP_MAX_BYTES_ENV = "BUGBITS_HARNESS_KEEP_MAX_BYTES"
KEEP_MAX_COUNT_ENV = "BUGBITS_HARNESS_KEEP_COUNT"
KEEP_MAX_AGE_DAYS_ENV = "BUGBITS_HARNESS_KEEP_MAX_AGE_DAYS"

OWNER_FILE = ".bb-scratch-owner.json"
WORKS_FILE = ".bb-scratch-works.json"      # run 级工作目录登记（name→case）
RUN_DIR_PREFIX = "bugbits-"

DEFAULT_MIN_FREE_MB = 2048          # run 级保底水位（构建+裕量）
DEFAULT_KEEP_MAX_BYTES = 2 * 1024 ** 3
DEFAULT_KEEP_MAX_COUNT = 8
DEFAULT_KEEP_MAX_AGE_DAYS = 14


class ScratchBudgetError(Exception):
    """磁盘水位不足——调用方应产出有效的非成功报告（BLOCKED），而非静默。"""


class ScratchSafetyError(Exception):
    """回收目标越界/无归属标记——拒绝删除，宁可泄漏也不误删。"""


def _env_int(name, default):
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        raise SystemExit(f"环境变量 {name}={raw!r} 不是整数")


def _statvfs_free_bytes(path):
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize


def du(path):
    """目录磁盘占用（字节；不跟随软链——与回收安全性同一口径）。
    os.walk(followlinks=False) 自身不进入目录软链；文件一律 lstat。"""
    total = 0
    for dp, _dns, fns in os.walk(path, followlinks=False):
        for fn in fns:
            fp = os.path.join(dp, fn)
            try:
                total += os.lstat(fp).st_size
            except OSError:
                pass
    return total


def pid_alive(pid):
    """pid 存活判定（Linux os.kill 0 探测；权限拒绝=存在；其他 OSError=保守活）。"""
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True                  # 别的用户进程：存在
    except OSError:
        return True                  # 保守：当作活动，不误回收
    return True


def atomic_write_json(path, obj):
    """原子写 JSON（tmp + os.replace）——避免半份 report 被当成结果。"""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


class ScratchManager:
    """一个 harness run 的 scratch 生命周期（create→登记→回收/保留）。"""

    def __init__(self, root=None, *, pid=None, now=None, free_bytes=None,
                 min_free_bytes=None, keep_max_bytes=None, keep_max_count=None,
                 keep_max_age_seconds=None):
        self.root = Path(root) if root is not None else self.default_root()
        self.pid = pid if pid is not None else os.getpid()
        self._now = now if now is not None else time.time
        self._free_bytes = free_bytes       # None → statvfs 实测
        self.min_free_bytes = (min_free_bytes if min_free_bytes is not None
                               else _env_int(MIN_FREE_MB_ENV, DEFAULT_MIN_FREE_MB)
                               * 1024 * 1024)
        self.keep_max_bytes = (keep_max_bytes if keep_max_bytes is not None
                               else _env_int(KEEP_MAX_BYTES_ENV,
                                             DEFAULT_KEEP_MAX_BYTES))
        self.keep_max_count = (keep_max_count if keep_max_count is not None
                               else _env_int(KEEP_MAX_COUNT_ENV,
                                             DEFAULT_KEEP_MAX_COUNT))
        self.keep_max_age_seconds = (
            keep_max_age_seconds if keep_max_age_seconds is not None
            else _env_int(KEEP_MAX_AGE_DAYS_ENV, DEFAULT_KEEP_MAX_AGE_DAYS) * 86400)
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def default_root():
        """默认 scratch 根：系统临时目录下固定子目录（不直接用 /tmp 顶层——
        孤儿扫描与安全边界需要独占根，避免与无关进程的 bugbits-* 前缀碰撞）。"""
        override = os.environ.get(SCRATCH_ROOT_ENV)
        if override:
            return Path(override)
        return Path(tempfile.gettempdir()) / "bugbits-harness"

    # ── owner / 登记 ────────────────────────────────────────────────
    def run_dir(self, run_id):
        return self.root / (RUN_DIR_PREFIX + run_id)

    def create(self, run_id):
        """创建本 run 的独占 scratch 目录（先过水位检查，再建目录写 owner）。"""
        self.budget_check(label=f"scratch create {run_id}")
        d = self.run_dir(run_id)
        d.mkdir(parents=True, exist_ok=True)
        self.write_owner(d, status="active")
        return d

    def owner_path(self, d):
        return Path(d) / OWNER_FILE

    def read_owner(self, d):
        try:
            return json.loads(self.owner_path(d).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def write_owner(self, d, **fields):
        owner = self.read_owner(d)
        owner.setdefault("runId", Path(d).name[len(RUN_DIR_PREFIX):])
        owner.setdefault("pid", self.pid)
        owner.setdefault("created", self._now())
        owner.setdefault("status", "active")
        owner.update(fields)
        owner["heartbeat"] = self._now()
        atomic_write_json(self.owner_path(d), owner)

    def touch(self, d):
        """心跳：长 run 期间每个用例后调用（崩溃恢复时佐证最后活动时刻）。"""
        self.write_owner(d)

    def register_work(self, run_dir, name, case_id):
        """登记一个可再生工作子目录（name→case），返回其路径。

        **不创建目录**：构建器（web_build._prepare_out）拒绝覆盖"非空且无
        manifest"的目录——预创建+标记文件会触发该安全守卫（2026-09-26 实跑
        发现的集成 bug）。归属信息记 run 级 WORKS_FILE；目录由用例/构建器自建。
        """
        run_dir = Path(run_dir)
        works = self.read_works(run_dir)
        works[name] = case_id
        atomic_write_json(run_dir / WORKS_FILE, works)
        return run_dir / name

    def read_works(self, run_dir):
        try:
            return json.loads((Path(run_dir) / WORKS_FILE).read_text(
                encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    # ── 活动 / 孤儿 ─────────────────────────────────────────────────
    def is_active(self, d):
        owner = self.read_owner(d)
        from case_process import group_running
        return owner.get("status") == "active" and (
            pid_alive(owner.get("pid")) or group_running(owner.get("casePgid")))

    def managed_dirs(self):
        if not self.root.is_dir():
            return []
        return sorted(p for p in self.root.iterdir()
                      if p.name.startswith(RUN_DIR_PREFIX))

    def orphan_scan(self):
        """孤儿 = 本根内 bugbits-* 且（无 owner / active 但 pid 已死）。
        kept 状态的目录不判孤儿（由保留上限策略淘汰）；判定不依赖目录年龄。"""
        out = []
        for p in self.managed_dirs():
            if not p.is_dir() and not p.is_symlink():
                continue
            owner = self.read_owner(p)
            if not owner:
                out.append(p)                 # mkdir 后崩溃等残留
            elif owner.get("status") == "active" and not self.is_active(p):
                out.append(p)                 # 硬终止残留（finally 未执行）
        return out

    def collect_orphans(self):
        recycled = []
        for p in self.orphan_scan():
            try:
                self.recycle(p)
                recycled.append(p.name)
            except ScratchSafetyError:
                continue                      # 越界/无标记：宁可泄漏不误删
        return recycled

    # ── 回收（安全边界） ────────────────────────────────────────────
    def _inside_root(self, path):
        root = self.root.resolve()
        p = path.resolve()
        return p != root and root in p.parents

    def recycle(self, path):
        path = Path(path)
        if path.is_symlink():
            # 顶层软链：unlink 本身安全（不触目标），但父目录须在根内
            if path.parent.resolve() != self.root.resolve() \
                    and self.root.resolve() not in path.parent.resolve().parents:
                raise ScratchSafetyError(f"软链不在 scratch 根内: {path}")
            path.unlink()
            return
        if not self._inside_root(path):
            raise ScratchSafetyError(f"拒绝删除 scratch 根外/根自身: {path}")
        if not path.is_dir():
            raise ScratchSafetyError(f"非目录: {path}")
        # 归属标记（防误删陌生目录）：自身是受管 run 目录（有 owner），或
        # 位于某个受管 run 目录之内（工作子目录/嵌套产物/.vendor-cache——
        # register_work 不预创建目录，归属由 run 级 WORKS_FILE 登记）。
        if not (path / OWNER_FILE).exists():
            managed = any((anc / OWNER_FILE).exists()
                          for anc in path.resolve().parents
                          if self._inside_root(anc))
            if not managed:
                raise ScratchSafetyError(f"无归属标记，拒绝删除: {path}")
        shutil.rmtree(path)     # 不跟随树内软链（symlink→unlink，见单测）

    # ── 保留策略 ────────────────────────────────────────────────────
    def _kept_dirs(self):
        return [p for p in self.managed_dirs()
                if p.is_dir() and self.read_owner(p).get("status") == "kept"]

    def enforce_keep_policy(self):
        """kept 目录的容量/数量/时间上限（只作用于已保留诊断，不判活动状态）。

        返回本轮淘汰记录 [{"dir": 目录名, "policy": "age"|"count"|"bytes"}]——
        SCRATCH-03：finish 据此 + 存在性核对报告最终实际处置（淘汰原因）。
        """
        evicted = []
        now = self._now()
        for p in self._kept_dirs():
            owner = self.read_owner(p)
            if now - float(owner.get("created", now)) > self.keep_max_age_seconds:
                self.recycle(p)
                evicted.append({"dir": p.name, "policy": "age"})
        kept = self._kept_dirs()
        if len(kept) > self.keep_max_count:
            kept.sort(key=lambda p: self.read_owner(p).get("created", 0))
            for p in kept[:len(kept) - self.keep_max_count]:
                self.recycle(p)
                evicted.append({"dir": p.name, "policy": "count"})
        kept = self._kept_dirs()
        kept.sort(key=lambda p: self.read_owner(p).get("created", 0))
        total = sum(du(p) for p in kept)
        for p in kept:
            if total <= self.keep_max_bytes:
                break
            total -= du(p)
            self.recycle(p)
            evicted.append({"dir": p.name, "policy": "bytes"})
        return evicted

    def finish(self, run_dir, *, keep_case_ids, keep_all=False):
        """run 结束处置：PASS→全回收；FAIL→仅保留失败用例的工作副本（有界）。

        返回**最终实际处置**（SCRATCH-03，2026-09-27）：enforce_keep_policy
        之后核对存在性——本 run 被容量/数量/年龄策略淘汰时报 evicted +
        触发策略（evictedBy=bytes/count/age）+ 根内仍存在的可用诊断
        （survivingKeptDirs，真实路径）；kept 时 keptSubdirs 只含仍存在的
        目录，不承诺不存在的诊断。归属以 run 级 WORKS_FILE 为准；未登记
        子目录（.vendor-cache、崩溃残留等）一律回收——FAIL 最小诊断只保留
        已登记的失败用例工作副本。
        """
        run_dir = Path(run_dir)
        if not run_dir.is_dir():
            return {"status": "absent", "keptSubdirs": [], "recycledSubdirs": []}
        if keep_all:
            intended = sorted(p.name for p in run_dir.iterdir()
                              if p.name not in (OWNER_FILE, WORKS_FILE))
            self.write_owner(run_dir, status="kept", keepReason="--keep-scratch")
            evictions = self.enforce_keep_policy()
            return self._final_disposition(
                run_dir, intended=intended, recycled=[], evictions=evictions,
                keep_all=True)
        works = self.read_works(run_dir)
        kept, recycled = [], []
        for child in sorted(run_dir.iterdir()):
            if child.name in (OWNER_FILE, WORKS_FILE):
                continue
            if works.get(child.name) in keep_case_ids:
                kept.append(child.name)
                continue
            try:
                self.recycle(child)
                recycled.append(child.name)
            except ScratchSafetyError:
                continue
        if kept:
            self.write_owner(run_dir, status="kept",
                             keepReason=f"FAIL diagnostics: {sorted(keep_case_ids)}")
            evictions = self.enforce_keep_policy()
            return self._final_disposition(
                run_dir, intended=kept, recycled=recycled, evictions=evictions)
        self.recycle(run_dir)
        return {"status": "recycled", "keptSubdirs": [],
                "recycledSubdirs": recycled}

    def _final_disposition(self, run_dir, *, intended, recycled, evictions,
                           keep_all=False):
        """enforce_keep_policy 之后的最终实际处置（存在性核对，不美饰）。

        intended = 原拟保留的子目录名（keep_all=全部子目录；FAIL=登记的失败
        用例工作副本）。本 run 目录已被策略淘汰 → evicted（诊断不可用，不报
        kept/不承诺路径）；存活 → kept 且 keptSubdirs 只含仍存在的 intended。
        """
        run_dir = Path(run_dir)
        evictions = evictions or []
        if not run_dir.is_dir():
            own = next((e["policy"] for e in evictions
                        if e["dir"] == run_dir.name), None)
            disp = {"status": "evicted",
                    "evictedBy": own or "keep-policy",
                    "keptSubdirs": [],          # 已淘汰：不承诺不存在的诊断
                    "recycledSubdirs": recycled,
                    "intendedKeptSubdirs": sorted(intended),
                    # 真实可用路径：根内仍存在的其他 kept 诊断
                    "survivingKeptDirs": [p.name for p in self._kept_dirs()]}
            if keep_all:
                disp["keepAll"] = True
            return disp
        kept_now = sorted(name for name in intended
                          if (run_dir / name).is_dir())
        disp = {"status": "kept", "keptSubdirs": kept_now,
                "recycledSubdirs": recycled}
        if keep_all:
            disp["keepAll"] = True
        return disp

    # ── 容量 ────────────────────────────────────────────────────────
    def free_bytes(self):
        if self._free_bytes is not None:
            return self._free_bytes
        try:
            return _statvfs_free_bytes(self.root)
        except OSError as e:
            if e.errno == errno.ENOENT:
                return _statvfs_free_bytes(self.root.parent)
            raise

    def budget_check(self, need_bytes=0, label=""):
        free = self.free_bytes()
        if free - need_bytes < self.min_free_bytes:
            raise ScratchBudgetError(
                f"磁盘预算不足{f'（{label}）' if label else ''}: "
                f"需 {need_bytes // (1024 * 1024)}MB + 保底 "
                f"{self.min_free_bytes // (1024 * 1024)}MB > "
                f"可用 {free // (1024 * 1024)}MB（scratch 根 {self.root}；"
                f"不自动删除任何数据，请释放空间或调整 "
                f"{MIN_FREE_MB_ENV}）")
