"""HARNESS-01 + SCRATCH-03：scratch 生命周期与磁盘预算单测。

全部用合成小 fixture（mkdtemp），不碰真实数据、不填真实根盘。
覆盖：创建/登记、PASS 回收、FAIL 有界保留、孤儿恢复（pid 判活）、活动锁保护、
软链接不穿透、容量预算拒绝、连续两轮占用上限、报告原子写。

SCRATCH-03（2026-09-27 审查，ai/bug/2026-09-27-ui-provenance-review.md）：
finish() 必须返回**最终实际处置**——enforce_keep_policy 之后核对存在性；
被 bytes/count/age 策略淘汰 → evicted + 触发策略 + 真实可用路径
（survivingKeptDirs）；kept 时 keptSubdirs 只含仍存在的目录；keep_all 与
普通 FAIL 路径同样如实。容量上限本身不因修报告而关闭。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness" / "web"))

import scratch  # noqa: E402  (harness/web/scratch.py)


def _dead_pid():
    """取得一个已退出的 pid（子进程 wait 后即死；测试窗口内复用概率可忽略）。"""
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


class ScratchTestBase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="bb-scratch-test-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def mgr(self, **kw):
        kw.setdefault("root", self.root)
        return scratch.ScratchManager(**kw)


class TestCreateAndOwner(ScratchTestBase):
    def test_create_writes_owner_with_live_pid(self):
        m = self.mgr()
        d = m.create("r1")
        self.assertTrue(d.is_dir())
        self.assertEqual(d.name, "bugbits-r1")
        owner = m.read_owner(d)
        self.assertEqual(owner["runId"], "r1")
        self.assertEqual(owner["pid"], os.getpid())
        self.assertEqual(owner["status"], "active")
        self.assertTrue(m.is_active(d))

    def test_create_enforces_budget(self):
        m = self.mgr(free_bytes=100, min_free_bytes=1000)
        with self.assertRaises(scratch.ScratchBudgetError) as cm:
            m.create("r2")
        self.assertIn("磁盘预算", str(cm.exception))
        self.assertFalse((self.root / "bugbits-r2").exists())

    def test_budget_check_injected_free(self):
        m = self.mgr(free_bytes=5000, min_free_bytes=1000)
        with self.assertRaises(scratch.ScratchBudgetError):
            m.budget_check(need_bytes=4100, label="A06")   # 剩 900 < 保底 1000
        m.budget_check(need_bytes=4000, label="A06")       # 剩 1000 ≥ 保底：不抛


class TestRecycleSafety(ScratchTestBase):
    def test_recycle_removes_managed_dir_only(self):
        m = self.mgr()
        d = m.create("r1")
        (d / "det-a").mkdir()
        (d / "det-a" / "x.bin").write_bytes(b"x" * 1024)
        m.recycle(d)
        self.assertFalse(d.exists())
        self.assertTrue(self.root.exists())             # 根不可删

    def test_recycle_refuses_root_and_outside(self):
        m = self.mgr()
        outside = Path(tempfile.mkdtemp(prefix="bb-outside-"))
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        with self.assertRaises(scratch.ScratchSafetyError):
            m.recycle(self.root)                        # 根自身
        with self.assertRaises(scratch.ScratchSafetyError):
            m.recycle(outside)                          # 根外目录
        self.assertTrue(outside.exists())

    def test_recycle_requires_owner_or_work_marker(self):
        m = self.mgr()
        stranger = self.root / "bugbits-stranger"       # 无 owner 的根内目录
        stranger.mkdir()
        (stranger / "x").write_text("x")
        with self.assertRaises(scratch.ScratchSafetyError):
            m.recycle(stranger)
        self.assertTrue(stranger.exists())

    def test_recycle_top_level_symlink_unlinks_without_touching_target(self):
        m = self.mgr()
        target = Path(tempfile.mkdtemp(prefix="bb-target-"))
        self.addCleanup(shutil.rmtree, target, ignore_errors=True)
        (target / "keep.bin").write_bytes(b"k" * 32)
        link = self.root / "bugbits-link"
        link.symlink_to(target)
        m.recycle(link)
        self.assertFalse(link.is_symlink())
        self.assertTrue((target / "keep.bin").exists())  # 目标完好

    def test_recycle_does_not_follow_symlinks_inside(self):
        """sens-root 场景：scratch 内 symlink 指向外部文件——链接被清，目标完好。"""
        m = self.mgr()
        d = m.create("r1")
        outside_dir = Path(tempfile.mkdtemp(prefix="bb-outside-"))
        self.addCleanup(shutil.rmtree, outside_dir, ignore_errors=True)
        victim = outside_dir / "original.bin"
        victim.write_bytes(b"v" * 64)
        sub = d / "sens-root"
        sub.mkdir()
        (sub / "file-link").symlink_to(victim)          # 文件软链
        (sub / "dir-link").symlink_to(outside_dir)      # 目录软链
        (sub / "real").write_text("real")
        m.recycle(d)
        self.assertFalse(d.exists())
        self.assertEqual(victim.read_bytes(), b"v" * 64)  # 未穿透
        self.assertTrue(outside_dir.is_dir())


class TestOrphanRecovery(ScratchTestBase):
    def test_dead_pid_dir_is_orphan_and_collected(self):
        m = self.mgr()
        d = m.create("r-dead")
        m.write_owner(d, pid=_dead_pid())               # 模拟崩溃残留
        self.assertEqual([p.name for p in m.orphan_scan()], ["bugbits-r-dead"])
        recycled = m.collect_orphans()
        self.assertEqual(recycled, ["bugbits-r-dead"])
        self.assertFalse(d.exists())

    def test_active_pid_dir_is_not_orphan(self):
        m = self.mgr()
        d = m.create("r-live")                          # owner pid = 本进程（活）
        self.assertEqual(m.orphan_scan(), [])
        m.collect_orphans()
        self.assertTrue(d.exists())                     # 活动锁保护

    def test_kept_dir_with_dead_pid_is_not_orphan(self):
        """FAIL 保留的诊断不因 pid 死亡被孤儿回收（由保留上限策略管理）。"""
        m = self.mgr()
        d = m.create("r-kept")
        m.write_owner(d, pid=_dead_pid(), status="kept", keepReason="FAIL diagnostics")
        self.assertEqual(m.orphan_scan(), [])
        m.collect_orphans()
        self.assertTrue(d.exists())


class TestDisposition(ScratchTestBase):
    def _run_with_work(self, m, run_id, cases):
        d = m.create(run_id)
        for name, case_id, size in cases:
            w = m.register_work(d, name, case_id)
            w.mkdir(parents=True, exist_ok=True)      # 目录由用例/构建器自建
            (w / "data.bin").write_bytes(b"\0" * size)
        return d

    def test_register_work_does_not_create_dir(self):
        """回归（2026-09-26 实跑发现的集成 bug）：register_work 预创建目录会
        触发 web_build._prepare_out 的"非空且无 manifest 拒绝覆盖"安全守卫，
        A06/A07 全炸。归属只记 run 级 WORKS_FILE，目录不预创建。"""
        m = self.mgr()
        d = m.create("r1")
        w = m.register_work(d, "det-a", "A06")
        self.assertFalse(w.exists())
        self.assertEqual(m.read_works(d), {"det-a": "A06"})

    def test_pass_recycles_everything(self):
        m = self.mgr()
        d = self._run_with_work(m, "r1", [("det-a", "A06", 2048),
                                          ("sens-root", "A07", 512)])
        summary = m.finish(d, keep_case_ids=set(), keep_all=False)
        self.assertFalse(d.exists())
        self.assertEqual(summary["status"], "recycled")

    def test_fail_keeps_only_failed_case_work(self):
        m = self.mgr()
        d = self._run_with_work(m, "r1", [("det-a", "A06", 2048),
                                          ("det-b", "A06", 2048),
                                          ("tamper-a09", "A09", 512)])
        summary = m.finish(d, keep_case_ids={"A09"}, keep_all=False)
        self.assertTrue((d / "tamper-a09").is_dir())
        self.assertFalse((d / "det-a").exists())
        self.assertFalse((d / "det-b").exists())
        self.assertEqual(summary["status"], "kept")
        self.assertEqual(summary["keptSubdirs"], ["tamper-a09"])

    def test_fail_recycles_unregistered_children(self):
        """未登记子目录（.vendor-cache/崩溃残留）不作诊断保留。"""
        m = self.mgr()
        d = self._run_with_work(m, "r1", [("det-a", "A06", 2048)])
        cache = d / ".vendor-cache"
        cache.mkdir()
        (cache / "pyodide-core-0.26.4.tar.bz2").write_bytes(b"\0" * 128)
        summary = m.finish(d, keep_case_ids={"A06"}, keep_all=False)
        self.assertTrue((d / "det-a").is_dir())
        self.assertFalse(cache.exists())
        self.assertEqual(summary["keptSubdirs"], ["det-a"])
        self.assertIn(".vendor-cache", summary["recycledSubdirs"])

    def test_keep_all_flag(self):
        m = self.mgr()
        d = self._run_with_work(m, "r1", [("det-a", "A06", 2048)])
        summary = m.finish(d, keep_case_ids=set(), keep_all=True)
        self.assertTrue((d / "det-a").is_dir())
        self.assertEqual(summary["status"], "kept")

    def test_fail_kept_subdirs_all_exist_on_disk(self):
        """SCRATCH-03：普通 FAIL 路径——kept 时 keptSubdirs 与盘上一一对应，
        不承诺不存在的诊断。"""
        m = self.mgr()
        d = self._run_with_work(m, "r1", [("det-a", "A06", 2048),
                                          ("tamper-a09", "A09", 512)])
        summary = m.finish(d, keep_case_ids={"A09"})
        self.assertEqual(summary["status"], "kept")
        self.assertEqual(summary["keptSubdirs"], ["tamper-a09"])
        for name in summary["keptSubdirs"]:
            self.assertTrue((d / name).is_dir(),
                            f"keptSubdirs 承诺了不存在的目录: {name}")
        self.assertTrue(d.is_dir())

    def test_keep_all_reports_existing_subdirs(self):
        """SCRATCH-03：keep_all 存活时 keptSubdirs 只含仍存在的子目录。"""
        m = self.mgr()
        d = self._run_with_work(m, "r1", [("det-a", "A06", 2048)])
        summary = m.finish(d, keep_case_ids=set(), keep_all=True)
        self.assertEqual(summary["status"], "kept")
        self.assertTrue(summary.get("keepAll"))
        self.assertEqual(summary["keptSubdirs"], ["det-a"])
        self.assertTrue((d / "det-a").is_dir())

    def test_bytes_eviction_reported_as_evicted(self):
        """SCRATCH-03 回归（探针反例）：keep_max_bytes=1 + 3B fixture——
        旧代码返回 kept/keptSubdirs=[fixture] 而文件已淘汰；修复后必须报
        最终实际处置 evicted + 触发策略 bytes，不承诺不存在的诊断。"""
        m = self.mgr(keep_max_bytes=1)
        d = m.create("r1")
        w = m.register_work(d, "fixture", "FAIL1")
        w.mkdir(parents=True)
        (w / "data").write_bytes(b"abc")
        summary = m.finish(d, keep_case_ids={"FAIL1"})
        self.assertEqual(summary["status"], "evicted")
        self.assertEqual(summary["evictedBy"], "bytes")
        self.assertEqual(summary["keptSubdirs"], [])
        self.assertEqual(summary.get("intendedKeptSubdirs"), ["fixture"])
        self.assertFalse(d.exists())
        self.assertFalse(w.exists())

    def test_age_eviction_reported_as_evicted(self):
        """SCRATCH-03：age 策略淘汰 → evicted + evictedBy=age。"""
        now = 1_000_000_000.0
        m = self.mgr(keep_max_age_seconds=86400, now=lambda: now)
        d = m.create("r-old")
        m.write_owner(d, created=now - 10 * 86400)
        w = m.register_work(d, "det-a", "A06")
        w.mkdir(parents=True)
        (w / "data.bin").write_bytes(b"\0" * 16)
        summary = m.finish(d, keep_case_ids={"A06"})
        self.assertEqual(summary["status"], "evicted")
        self.assertEqual(summary["evictedBy"], "age")
        self.assertEqual(summary["keptSubdirs"], [])
        self.assertFalse(d.exists())

    def test_count_eviction_of_self_reported(self):
        """SCRATCH-03：count 策略淘汰【本轮】（本轮为最旧 kept）→ evicted +
        evictedBy=count + 仍存在的可用诊断（survivingKeptDirs 真实路径）。"""
        now = 1_000_000_000.0
        m = self.mgr(keep_max_count=1, now=lambda: now)
        prior = m.create("r-prior")
        m.write_owner(prior, status="kept", keepReason="earlier round",
                      created=now + 100)          # 比本轮新 → 本轮最旧被淘汰
        d = m.create("r-cur")
        w = m.register_work(d, "det-a", "A06")
        w.mkdir(parents=True)
        (w / "data.bin").write_bytes(b"\0" * 16)
        summary = m.finish(d, keep_case_ids={"A06"})
        self.assertEqual(summary["status"], "evicted")
        self.assertEqual(summary["evictedBy"], "count")
        self.assertEqual(summary["keptSubdirs"], [])
        self.assertTrue(prior.is_dir())           # 新者保留
        self.assertIn("bugbits-r-prior",
                      summary.get("survivingKeptDirs", []))
        self.assertFalse(d.exists())

    def test_keep_all_bytes_eviction_reported(self):
        """SCRATCH-03：keep_all 也会被容量上限淘汰（不得为报告关闭上限）——
        淘汰后报 evicted 而非 kept。"""
        m = self.mgr(keep_max_bytes=1)
        d = self._run_with_work(m, "r1", [("det-a", "A06", 2048)])
        summary = m.finish(d, keep_case_ids=set(), keep_all=True)
        self.assertEqual(summary["status"], "evicted")
        self.assertEqual(summary["evictedBy"], "bytes")
        self.assertFalse(d.exists())


class TestKeepPolicyBounds(ScratchTestBase):
    def test_two_consecutive_fail_rounds_bounded_by_bytes(self):
        """连续两轮 FAIL 各保留诊断，总量受 keep_max_bytes 上限约束。"""
        m = self.mgr(keep_max_bytes=4096)
        d1 = m.create("r1")
        w1 = m.register_work(d1, "det-a", "A06")
        w1.mkdir(parents=True)
        (w1 / "data.bin").write_bytes(b"\0" * 3000)
        m.finish(d1, keep_case_ids={"A06"}, keep_all=False)
        self.assertTrue(d1.is_dir())
        d2 = m.create("r2")
        w2 = m.register_work(d2, "det-a", "A06")
        w2.mkdir(parents=True)
        (w2 / "data.bin").write_bytes(b"\0" * 3000)
        m.finish(d2, keep_case_ids={"A06"}, keep_all=False)
        kept = [p for p in m.managed_dirs()
                if m.read_owner(p).get("status") == "kept"]
        total = sum(scratch.du(p) for p in kept)
        self.assertLessEqual(total, 4096 + 1024)        # 上限 + 单目录粒度容差
        self.assertTrue(d2.is_dir())                    # 保留最新的，淘汰最旧的
        self.assertFalse(d1.is_dir())

    def test_keep_count_bound(self):
        m = self.mgr(keep_max_count=2)
        made = []
        for i in range(4):
            d = m.create(f"r{i}")
            m.register_work(d, "det-a", "A06").mkdir(parents=True)
            m.finish(d, keep_case_ids={"A06"}, keep_all=False)
            made.append(d)
        kept = [p for p in m.managed_dirs()
                if m.read_owner(p).get("status") == "kept"]
        self.assertEqual(len(kept), 2)
        self.assertTrue(made[3].is_dir() and made[2].is_dir())
        self.assertFalse(made[0].is_dir() or made[1].is_dir())

    def test_keep_age_bound(self):
        now = 1_000_000_000.0
        m = self.mgr(keep_max_age_seconds=86400, now=lambda: now)
        d = m.create("r-old")
        m.write_owner(d, created=now - 10 * 86400)
        m.finish(d, keep_case_ids={"A06"}, keep_all=False)  # 触发策略
        self.assertFalse(d.exists())


class TestAtomicWrite(ScratchTestBase):
    def test_atomic_write_json_replaces_and_leaves_no_tmp(self):
        p = self.root / "report.json"
        scratch.atomic_write_json(p, {"a": 1})
        self.assertEqual(json.loads(p.read_text())["a"], 1)
        scratch.atomic_write_json(p, {"a": 2})
        self.assertEqual(json.loads(p.read_text())["a"], 2)
        self.assertEqual(list(self.root.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
