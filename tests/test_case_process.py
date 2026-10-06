"""Real fork/process-group regressions; no game build or browser required."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "harness/web"))
import run as R
from cases import Case, CaseResult, BlockedError
import case_process as P


@unittest.skipUnless(os.name == "posix", "POSIX process groups")
class CaseProcessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = SimpleNamespace(run_dir=Path(self.tmp.name), scratch=None,
                                   scratch_dir=None)

    def execute(self, fn, timeout=1, heartbeat=None):
        return P.execute(Case("fixture", "browser", "fixture", run=fn),
                         self.ctx, timeout, heartbeat=heartbeat)

    def test_pass_and_large_result(self):
        res, meta = self.execute(lambda c: CaseResult("PASS", actual="x" * 200000))
        self.assertEqual(res.status, "PASS")
        self.assertEqual(len(res.actual), 200000)
        self.assertEqual(meta["exitCode"], 0)

    def test_exception_blocked_and_invalid_result(self):
        def blocked(c):
            raise BlockedError("no fixture")
        def broken(c):
            raise ValueError("broken fixture")
        for fn, status in [(blocked, "BLOCKED"), (broken, "FAIL"),
                           (lambda c: None, "FAIL")]:
            self.assertEqual(self.execute(fn)[0].status, status)

    def test_exit_without_result_is_failure(self):
        for code in (0, 7):
            res, meta = self.execute(lambda c: os._exit(code))
            self.assertEqual(res.status, "FAIL")
            self.assertEqual(meta["exitCode"], code)

    def test_timeout_and_progress(self):
        updates = []
        t = time.monotonic()
        res, meta = self.execute(lambda c: time.sleep(60), .25,
                                heartbeat=lambda value: updates.append(value))
        self.assertEqual(res.status, "FAIL")
        self.assertTrue(meta["timedOut"])
        self.assertLess(time.monotonic() - t, 3)
        self.assertTrue(updates)
        self.assertIn("pid", updates[0])

    def test_slow_heartbeat_cannot_accept_late_pass(self):
        def late(c):
            time.sleep(.15)
            return CaseResult("PASS")
        res, meta = self.execute(late, .05, heartbeat=lambda value: time.sleep(.25))
        self.assertTrue(meta["timedOut"])
        self.assertEqual(res.status, "FAIL")

    def test_cleanup_fact_survives_heartbeat_exception(self):
        def heartbeat(value):
            raise OSError("progress disk error")
        with patch.object(P, "group_running", return_value=True):
            with self.assertRaises(OSError):
                self.execute(lambda c: time.sleep(60), heartbeat=heartbeat)
        self.assertFalse(self.ctx.cleanup_pending["cleanupComplete"])

    def test_cleanup_pending_exception_never_starts_next_case(self):
        ctx = R.Ctx("slice", self.ctx.run_dir, {}, {})
        def failed_execute(case, context, *args):
            context.cleanup_pending = {"cleanupComplete": False, "pid": 123}
            raise OSError("heartbeat failure")
        selected = [Case("first", "browser", "first"), Case("second", "browser", "second")]
        with patch.object(P, "execute", side_effect=failed_execute) as execute:
            with self.assertRaises(RuntimeError):
                R.run_cases(selected, ctx)
            self.assertEqual(execute.call_count, 1)
        self.assertEqual(ctx.cleanup_pending["pid"], 123)

    def test_normal_exit_cleans_grandchild(self):
        def spawn(c):
            proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
            (c.run_dir / "grandchild.pid").write_text(str(proc.pid))
            return CaseResult("PASS")
        res, meta = self.execute(spawn)
        self.assertEqual(res.status, "PASS")
        self.assertFalse(P.group_running(meta["pid"]))

    def test_ignores_term_is_killed(self):
        def hang(c):
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            time.sleep(60)
        res, meta = self.execute(hang, .25)
        self.assertEqual(res.status, "FAIL")
        self.assertFalse(P.group_running(meta["pid"]))

    def test_pass_file_does_not_override_bad_exit(self):
        # Host protocol must reject a worker that wrote a result but then failed.
        original = P._worker
        def bad_worker(*args):
            original(*args)
            os._exit(9)
        P._worker = bad_worker
        try:
            res, meta = self.execute(lambda c: CaseResult("PASS"))
            self.assertEqual(res.status, "FAIL")
            self.assertEqual(meta["exitCode"], 9)
        finally:
            P._worker = original

    def test_pass_file_then_hang_is_timeout(self):
        original = P._worker
        def bad_worker(*args):
            original(*args)
            time.sleep(60)
        with patch.object(P, "_worker", bad_worker):
            res, meta = self.execute(lambda c: CaseResult("PASS"), .25)
        self.assertEqual(res.status, "FAIL")
        self.assertTrue(meta["timedOut"])

    def test_timeout_cleans_term_ignoring_grandchild(self):
        def spawn(c):
            subprocess.Popen([sys.executable, "-c",
                              "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(60)"])
            time.sleep(60)
        res, meta = self.execute(spawn, .4)
        self.assertTrue(meta["timedOut"])
        self.assertFalse(P.group_running(meta["pid"]))

    def test_scratch_orphan_scan_preserves_live_case_group(self):
        mgr = R.scratch_mod.ScratchManager(root=self.ctx.run_dir / "scratch",
                                         min_free_bytes=0)
        d = mgr.create("orphan-test")
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                 start_new_session=True)
        try:
            mgr.write_owner(d, pid=99999999, casePgid=child.pid)
            self.assertEqual(mgr.collect_orphans(), [])
            self.assertTrue(d.exists())
        finally:
            child.kill()
            child.wait()
        self.assertEqual(mgr.collect_orphans(), [d.name])

    def test_run_continues_after_timeout_and_preserves_scratch(self):
        mgr = R.scratch_mod.ScratchManager(root=self.ctx.run_dir / "scratch",
                                         min_free_bytes=0)
        scratch = mgr.create("integration")
        ctx = R.Ctx("slice", self.ctx.run_dir, {}, {}, mgr, scratch)
        ctx.case_timeout = .2
        def hang(c):
            work = c.work_dir("failure-evidence")
            work.mkdir()
            (work / "note").write_text("diagnostic")
            time.sleep(60)
        selected = [Case("hang", "browser", "hang", run=hang),
                    Case("next", "browser", "next", run=lambda c: CaseResult("PASS"))]
        observed = []
        original = R.write_progress
        def progress(*args, **kwargs):
            original(*args, **kwargs)
            observed.append(json.loads((ctx.run_dir / "progress.json").read_text()))
        with patch.object(R, "write_progress", progress):
            results = R.run_cases(selected, ctx)
        self.assertEqual([x["status"] for x in results], ["FAIL", "PASS"])
        self.assertTrue(any(x.get("currentCase") == "hang" for x in observed))
        self.assertEqual(mgr.read_works(scratch)["failure-evidence"], "hang")
        disp = mgr.finish(scratch, keep_case_ids={"hang"})
        self.assertEqual(disp["status"], "kept")
        self.assertTrue((scratch / "failure-evidence/note").exists())

    def test_progress_query_detects_dead_or_reused_pid_and_final_report(self):
        R.write_progress(self.ctx.run_dir, status="running", currentCase="x")
        self.assertTrue(R.read_progress(self.ctx.run_dir)["processAlive"])
        R.write_progress(self.ctx.run_dir, processIdentity="wrong-start-token")
        self.assertEqual(R.read_progress(self.ctx.run_dir)["status"], "interrupted")
        report = {"exitCode": 1, "summary": {"FAIL": 1}, "cases": []}
        R.write_report(self.ctx.run_dir / "report.json", report)
        self.assertEqual(R.read_progress(self.ctx.run_dir)["status"], "complete")
        self.assertEqual(R.read_progress(self.ctx.run_dir)["exitCode"], 1)

    def test_incomplete_cleanup_stops_run_and_preserves_active_scratch(self):
        case = Case("stuck", "browser", "stuck", run=lambda c: CaseResult("PASS"))
        # Isolate cleanup from the installed package's source binding. Real
        # provenance acceptance/rejection is covered by the CLI integration tests.
        with patch.object(R, "OUT_ROOT", self.ctx.run_dir / "reports"), \
             patch.object(R, "cases_for", return_value=[case]), \
             patch.object(R, "env_info", return_value={}), \
             patch.object(R, "provenance_errors", return_value=([], [])), \
             patch.object(P, "execute", return_value=(
                 CaseResult("FAIL", "cleanup incomplete"), {"cleanupComplete": False})), \
             patch.object(R.scratch_mod.ScratchManager, "finish") as finish:
            code = R.main(["--suite", "browser", "--case", "stuck",
                           "--scratch-root", str(self.ctx.run_dir / "scratch")])
            finish.assert_not_called()
        self.assertEqual(code, 1)
        report = json.loads((R.LAST_RUN_DIR / "report.json").read_text())
        self.assertEqual(report["scratch"]["disposition"]["status"], "cleanup-pending")
        scratch = Path(report["scratch"]["dir"])
        self.assertTrue(scratch.exists())
        self.assertEqual(R.scratch_mod.ScratchManager(root=scratch.parent)
                         .read_owner(scratch)["status"], "active")


if __name__ == "__main__":
    unittest.main()
