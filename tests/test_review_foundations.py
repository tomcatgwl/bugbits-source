"""独立预期验证 REVIEW：矩阵代数、动画边沿、三维距离与脚本单只出兵。"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # 扁平导入修复（NC-harness C）
from bugbits.assets import pose, v3d, data_dir
from bugbits.sim import combat
from test_sim_combat import make_sim, place
from test_scriptvm import make_vm


IDENTITY = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)


class TestMatrixFoundations(unittest.TestCase):
    def test_affine_inverse_both_orders(self):
        # 90° rotation plus translation; nonuniform scale/shear; independent I oracle.
        for m in ((0, 1, 0, 0, -1, 0, 0, 0, 0, 0, 1, 0, 3, 4, 5, 1),
                  (2, 1, 0, 0, 0, 3, 0, 0, 0, 0, 4, 0, 3, -4, 5, 1)):
            for product in (pose.mat_mul(m, pose.mat_inv(m)),
                            pose.mat_mul(pose.mat_inv(m), m)):
                for got, expected in zip(product, IDENTITY):
                    self.assertAlmostEqual(got, expected, places=9)

    def test_invalid_inverse_rejected(self):
        for m in ((0,) * 16, IDENTITY[:15] + (2,),
                  (math.nan,) + IDENTITY[1:]):
            with self.assertRaises(ValueError):
                pose.mat_inv(m)

    def test_skin_bind_local_then_animated_world(self):
        bind = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 10, 0, 0, 1)
        anim = (0, 1, 0, 0, -1, 0, 0, 0, 0, 0, 1, 0, 0, 20, 0, 1)
        # world (11,0,0) -> bone-local (1,0,0) -> rotated (0,1,0) + (0,20,0).
        got = pose.skin_at([((11, 0, 0), (0, 0, 1), [(0, 1)])], [bind], [anim])
        self.assertEqual(got[0][0], (0, 21, 0))

    def test_skin_transforms_normals_by_rotation(self):
        # 90° 绕 Z：法线 (1,0,0) 应随旋转变 (0,1,0)（刚体变换法线只受旋转，不受平移）。
        bind = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 10, 0, 0, 1)
        anim = (0, 1, 0, 0, -1, 0, 0, 0, 0, 0, 1, 0, 0, 20, 0, 1)
        got = pose.skin_at([((11, 0, 0), (1, 0, 0), [(0, 1)])], [bind], [anim])
        for got_c, want in zip(got[0][1], (0, 1, 0)):
            self.assertAlmostEqual(got_c, want, places=6)

    def test_real_bind_pose_restores_vertices(self):
        names = sorted(p[:-4] for p in os.listdir(data_dir("models", "bugs"))
                       if p.endswith(".v3d"))
        self.assertEqual(len(names), 24)
        for name in names:
            _, skin, records, _ = v3d.parse_v3d(data_dir("models", "bugs", name + ".v3d"))
            bind = pose.worlds_from_records(records)
            result = pose.skin_at(skin, bind, bind)
            for (p, _, inf), (got, _, _) in zip(skin, result):
                # Original44C5B0 divides by the weight total; identity skinning
                # restores the source point despite exporter weight rounding.
                for a, b in zip(got, p):
                    self.assertAlmostEqual(a, b, places=5)


class TestCombatFoundations(unittest.TestCase):
    def scenario(self, frames=(0.5,)):
        s = make_sim()
        u = s.units["ant"]
        u.attack_speed = 1
        u.attack_hit_frame = frames[0]
        u.attack_hit_frames = frames
        u.attack_duration = 2.0
        u.attack_wait_min = u.attack_wait_max = 0.4
        place(s, 0, "ant", 0)
        target = place(s, 1, "tick", 2)
        target.hp = 10000
        return s

    def test_first_hit_starts_from_zero(self):
        s = self.scenario()
        s.run(10)
        self.assertFalse(any(e[1] == "damage" for e in s.events))
        s.step()  # start at t1, 0.5 seconds = 10 updates -> t11
        self.assertEqual([e[0] for e in s.events if e[1] == "damage"], [11])

    def test_cycle_includes_tail_then_wait(self):
        s = self.scenario()
        s.run(62)
        # strict loop-end >2s at t42, wait .4+.1=.5s, restart t52, hit t62.
        self.assertEqual([e[0] for e in s.events if e[1] == "damage"], [11, 62])

    def test_multiple_hits_in_one_animation(self):
        s = self.scenario((0.5, 1.0, 1.5))
        s.run(41)
        self.assertEqual([e[0] for e in s.events if e[1] == "damage"], [11, 21, 31])

    def test_vertical_separation_excludes_melee_target(self):
        s = self.scenario()
        s.bugs[1].cur_pos = (2, 100, 0)
        self.assertIsNone(combat.pick_target(s, s.bugs[0]))

    def test_no_wait_rng_draw_at_hit(self):
        s = self.scenario()
        s.run(1)
        rng = s.rng.getstate()
        s.run(10)
        self.assertEqual(s.rng.getstate(), rng)  # 命中不重掷；仅圈末重掷等待

    def test_attack_progress_is_in_state_hash(self):
        s = self.scenario()
        old = s.state_hash()
        s.bugs[0].attack_tick = 2
        self.assertNotEqual(s.state_hash(), old)
        old = s.state_hash()
        s.bugs[0].attack_ready_at = 100
        self.assertNotEqual(s.state_hash(), old)

    def test_lost_target_cancels_animation(self):
        s = self.scenario()
        s.run(8)
        s.bugs[1].cur_pos = (2, 100, 0)
        s.step()
        self.assertEqual(s.bugs[0].attack_tick, -1)
        s.bugs[1].cur_pos = (2, 0, 0)
        s.run(10)
        self.assertFalse(any(e[1] == "damage" for e in s.events))
        s.step()
        self.assertEqual([e[0] for e in s.events if e[1] == "damage"], [20])

    def test_script_arguments_never_multiply_units(self):
        for command in ("sendenemy", "sendplayer"):
            for dialog in ("null", "D_NONE"):
                for value in ("0", "9", "4.75", "10.3"):
                    vm, sim = make_vm([(command, ["ant", "0", dialog, value])])
                    vm.run(1)
                    self.assertEqual(len(sim.bugs), 1, (command, dialog, value))
