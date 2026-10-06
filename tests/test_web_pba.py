"""PBA 并行审计回归（桥/runner/harness 侧）。

覆盖 PBA-04（桥 buy_ok/buy_reject 与 sim 原生事件统一保留窗裁窗）、
PBA-06（迟到命令排序合同：targetTick 为可执行门，同相位按提交序，不重排）、
PBA-09（P04 缺 performance.memory 时 BLOCKED 而非 PASS）。

独立预期来源：W0-web-contract §4/§5 与缺陷报告 ai/bug/2026-09-19-parallel-audit.md，
不反抄被测输出。PBA-04/06 用 from_objects 直接注入原解析对象（只读原资产），
无需 out/web 构建；PBA-09 用依赖替身验证 p04 的判定分支，非浏览器 E2E。
"""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "harness" / "web"))

from bugbits import level, unitdb, web_bridge, worlddb  # noqa: E402
from bugbits.assets import data_dir  # noqa: E402

import cases  # noqa: F401,E402  # 先导入以完成注册，规避 cases_browser 的循环导入
import cases_browser  # noqa: E402
from cases import BlockedError  # noqa: E402


def _bridge(retention=10000):
    lv = level.parse_level(data_dir('scripts', 'levels', 'level_02.vsc'))
    lv.scripts = []
    lv.props['InitialNectar'] = ['100']
    wd = worlddb.parse_world(data_dir('worlds', lv.world_name + '.vsc'))
    units = {u: unitdb.load_unit(u) for u in ('ant', 'littlebeetle', 'bee')}
    b = web_bridge.WebBridge()
    info = b.from_objects(lv, wd, units, 2026,
                          {'buyable': list(units), 'eventRetention': retention})
    return b, info


def _submit(b, info, cid, tick, unit='ant', lane=0):
    return b.submit({'sessionId': info['sessionId'], 'commandId': cid,
                     'targetTick': tick, 'type': 'buy', 'unit': unit,
                     'lane': lane})


class TestBridgeEventRetention(unittest.TestCase):
    """PBA-04：桥事件与 sim 原生事件走同一 seq 分配/裁窗路径。"""

    def test_bridge_events_respect_retention_window(self):
        b, info = _bridge(retention=30)
        for i in range(100):
            self.assertTrue(_submit(b, info, f'cd-{i}', 1)['queued'],
                            f"第 {i} 笔免费购买未排队")
        self.assertEqual(b.advance(1)['advanced'], 1)
        # 1 成功 + 99 E_CD 桥事件 + sim 原生 buy 事件，统一裁窗后保留 ≤30
        self.assertLessEqual(len(b.session.events), 30,
                             f"保留窗失效: {len(b.session.events)}")
        ev = b.read_events(0)
        self.assertTrue(ev['gap'], "保留窗溢出后 afterSeq=0 应报 gap")
        self.assertLessEqual(len(ev['events']), 30)
        # 从保留底界起增量读：连续、无重复、无 gap
        cursor = ev['events'][0]['seq'] - 1
        seen = []
        while True:
            r = b.read_events(cursor)
            self.assertFalse(r['gap'], "保留窗内增量读不应 gap")
            if not r['events']:
                break
            seqs = [e['seq'] for e in r['events']]
            self.assertEqual(seqs, list(range(cursor + 1, cursor + 1 + len(seqs))),
                             "seq 必须连续")
            seen += seqs
            cursor = r['nextSeq']
        self.assertEqual(seen, sorted(set(seen)), "重复事件")
        # 拒绝事件确为冷却拒绝
        rejects = [e for e in ev['events'] if e['type'] == 'buy_reject']
        self.assertTrue(rejects, "无拒绝事件")
        self.assertTrue(any(e['data'].get('reason') == 'E_CD' for e in rejects),
                        "拒绝事件应含 E_CD")


class TestLateCommandOrdering(unittest.TestCase):
    """PBA-06：targetTick 是可执行门，非排序键；同相位按提交序执行。"""

    def test_late_command_does_not_reorder(self):
        b, info = _bridge()
        self.assertEqual(b.advance(5)['advanced'], 5)
        # 先提交 targetTick=5，再提交 targetTick=1（迟到）；下 tick 两者同时到期
        self.assertTrue(_submit(b, info, 'first', 5)['queued'])
        self.assertTrue(_submit(b, info, 'second', 1)['queued'])
        self.assertEqual(b.advance(1)['advanced'], 1)
        log = b.audit_state()['cmds']['log']
        # 提交序：first 先执行（targetTick=5），second 后执行（迟到不插队）
        self.assertEqual([e[0] for e in log], ['first', 'second'],
                         f"迟到命令插队: {log}")
        # first 成功，second 因同泳道冷却被拒
        self.assertTrue(log[0][3], "first 应成功")
        self.assertFalse(log[1][3], "second 应被拒")
        self.assertEqual(log[1][4], 'E_CD', f"second 应因冷却拒绝: {log[1]}")


class TestP04MissingMemory(unittest.TestCase):
    """PBA-09：P04 缺 performance.memory 时 BLOCKED，而非 PASS。"""

    def _ctx(self):
        tmp = Path(tempfile.mkdtemp(prefix="pba-p04-"))
        return SimpleNamespace(web_out=tmp / "not-served", run_dir=tmp)

    def _patch(self, ctx, mem):
        class FakePage:
            def __init__(self):
                self.resets = 0

            def goto(self, *a, **k):
                pass

            def wait_for_function(self, *a, **k):
                pass

            def wait_for_timeout(self, *a, **k):
                pass

            def evaluate(self, source):
                if "resetGame" in source:
                    self.resets += 1
                    return None
                if "resetCount" in source:
                    return self.resets
                if "perfStats" in source:
                    return {"mem": mem}
                if "startGame" in source:
                    return None
                raise AssertionError(f"Unexpected P04 dependency: {source}")

        page = FakePage()
        browser = SimpleNamespace(new_page=lambda: page, close=lambda: None)
        playwright = SimpleNamespace(chromium=SimpleNamespace(
            launch=lambda **kw: browser))
        factory = lambda: __import__('contextlib').nullcontext(playwright)
        server = SimpleNamespace(shutdown=lambda: None)
        return patch.object(cases_browser, "_need_playwright", return_value=factory), \
            patch.object(cases_browser, "_serve", return_value=("http://fixture/", server))

    def test_missing_memory_blocks(self):
        ctx = self._ctx()
        p1, p2 = self._patch(ctx, None)
        with p1, p2:
            with self.assertRaises(BlockedError):
                cases_browser.p04(ctx)

    def test_present_memory_passes(self):
        ctx = self._ctx()
        mem = {"usedJSHeapMB": 50, "totalJSHeapMB": 100}
        p1, p2 = self._patch(ctx, mem)
        with p1, p2:
            result = cases_browser.p04(ctx)
        self.assertEqual(result.status, "PASS")
        self.assertIn("heap", result.detail)


if __name__ == "__main__":
    unittest.main()
