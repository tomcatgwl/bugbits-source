"""Normal motion through public gameplay; independent R389/R390 examples."""
import unittest

from bugbits import level, sim, unitdb, worlddb


def normal_game(*, acceleration=38, direction_factor=12, mass=1, speed=22, target=(1000.,0.,0.)):
    spec = unitdb.load_unit('ant')
    spec.props['Acceleration'] = [str(acceleration)]
    spec.props['DirectionFactor'] = [str(direction_factor)]
    spec.props['Mass'] = [str(mass)]
    spec.props['Speed'] = [str(speed)]
    unitdb.apply_props(spec)
    starts = [worlddb.Start('A',(0.,0.,0.),(1.,0.,0.),0,0,['B']),
              worlddb.Start('E',(2000.,0.,0.),(1.,0.,0.),1,0,[])]
    nodes = [worlddb.Waypoint('B',target,(1.,0.,0.),False,['E'])]
    world = worlddb.WorldData({},[],[],None,starts,nodes,2,
                              {'A':{'B'},'B':{'A','E'},'E':{'B'}})
    lv = level.LevelData({'InitialNectar':['10'],'NectarOnPaths':['0'],
                          'PlayerBaseSize':['100'],'EnemyBaseSize':['100']})
    return sim.Sim(lv,world,{'ant':spec},2026)


class NormalMotion(unittest.TestCase):
    def test_missing_speed_uses_normal_constructor_default_for_buy_and_spawn(self):
        for spawn in ('buy','spawn_free'):
            with self.subTest(spawn=spawn):
                base = normal_game()
                spec = base.units['ant']
                spec.props.pop('Speed')
                unitdb.apply_props(spec)
                self.assertIsNone(spec.speed)  # Legal absent native property.
                game = sim.Sim(base.level,base.world,{'ant':spec},2026)
                actor = getattr(game,spawn)(0,'ant',0)
                self.assertIsNotNone(actor)
                self.assertEqual(actor.speed,10.)  # Original ctor4CEB5C.
                game.run(3)
                self.assertAlmostEqual(actor.pos(game)[0],.095,places=6)

    def test_normal_dialogue_wait_stops_position_with_nonzero_velocity_and_resumes(self):
        from test_scriptvm_cursor import lang4_keys
        self.assertIn('D_01_INTRO',lang4_keys())  # Actual first-level ant text.
        game = normal_game(); actor = game.buy(0,'ant',0)
        game.run(4)
        game.set_dialogue(actor,'D_01_INTRO',0)
        game.run(19)
        point = actor.pos(game)
        game.step()  # One second after set_dialogue: conditional ground cap0.
        self.assertEqual(actor.pos(game),point)
        self.assertEqual(actor.dialogue_wait_until,game.tick+60)
        game.run(59)
        self.assertEqual(actor.pos(game),point)
        game.step()  # Public deadline reached; old nonzero velocity resumes P.
        self.assertGreater(actor.pos(game)[0],point[0])
        self.assertEqual([e[0] for e in game.events if e[1]=='dialogue_wait'],[24])

    def test_zero_route_projection_uses_slow_current_anchor_height_after_body_sample(self):
        base = normal_game(direction_factor=0,target=(0.,10.,0.))
        base.world.waypoints[0].connect_to = ['C']
        base.world.waypoints.append(worlddb.Waypoint('C',(0.,10.,1000.),(1.,0.,0.),False,['E']))
        base.world.adjacency = {'A':{'B'},'B':{'A','C'},'C':{'B','E'},'E':{'C'}}
        game = sim.Sim(base.level,base.world,base.units,2026)
        actor = game.buy(0,'ant',0)
        game.run(4)
        self.assertEqual((actor.route_current,actor.route_target),('B','C'))
        self.assertEqual(actor.body_pos(game)[1],0.)
        # Original AH41 includes equality, so t0 goes to the .5dt CC anchor.
        # CC.Y10 and physics.Y0 =>10*.05*.5=.25, not positive-branch2dt=1.
        self.assertEqual(actor.pos(game)[1],.25)

    def test_fractional_speed_preserves_public_cap_and_distinguishes_future_hash(self):
        for spawn in ('buy','spawn_free'):
            with self.subTest(spawn=spawn):
                game = normal_game(acceleration=443,direction_factor=0,speed=22.5)
                actor = getattr(game,spawn)(0,'ant',0)
                game.run(3)
                # Native f32 Speed22.5 leaves oldV22.1499996 below the cap.
                self.assertEqual(actor.pos(game),(1.1074999570846558,0.,0.))
        slow = normal_game(speed=22.5); fast = normal_game(speed=22.75)
        a = slow.buy(0,'ant',0); b = fast.buy(0,'ant',0)
        self.assertEqual(a.pos(slow),b.pos(fast))
        self.assertNotEqual(slow.state_hash(),fast.state_hash())

    def test_speed_cap_stores_the_scale_before_multiplying_old_velocity(self):
        game = normal_game(acceleration=443,direction_factor=0)
        actor = game.buy(0,'ant',0)
        game.run(3)
        # R393 original401350 independent store witness: oldV22.1499996,
        # f32(22/sqrt(f32(V^2))) then V*scale =>22 exactly. Normalizing
        # first instead gives21.999998 and a different physical-position bit.
        self.assertEqual(actor.pos(game),(1.100000023841858,0.,0.))

    def test_vertical_clamp_normalizes_before_the_setter_and_matrix(self):
        from bugbits import web_data
        from bugbits.web_bridge import WebBridge
        game = normal_game(target=(590.,1170.,1870.))
        bridge = WebBridge()
        opened = bridge.init('clamped-forward',2026,web_data.level_to_dict(game.level),
                             web_data.world_to_dict(game.world),
                             {'ant':web_data.unit_to_dict(game.units['ant'])},
                             {'buyable':['ant']})
        bridge.submit({'type':'buy','commandId':'clamp-buy',
                       'sessionId':opened['sessionId'],'unit':'ant','lane':0})
        bridge.advance(4)
        # R393-b target590/1170/1870: raw-C clamp then three original
        # normalize stores differ from the incomplete two-stage consumer.
        self.assertEqual(bridge.snapshot()['bugs'][0]['direction'],
                         [0.7094789147377014,0.3195665776729584,0.628105878829956])

    def test_body_matrix_normalizes_forward_column_again(self):
        from bugbits import web_data
        from bugbits.web_bridge import WebBridge
        game = normal_game(target=(1000.,500.,1000.))
        bridge = WebBridge()
        opened = bridge.init('matrix-forward',2026,web_data.level_to_dict(game.level),
                             web_data.world_to_dict(game.world),
                             {'ant':web_data.unit_to_dict(game.units['ant'])},
                             {'buyable':['ant']})
        bridge.submit({'type':'buy','commandId':'matrix-buy',
                       'sessionId':opened['sessionId'],'unit':'ant','lane':0})
        bridge.advance(4)
        # R393 independent Fraction/Decimal stores, raw forward-column chain:
        # 443090 normalize ->405560 normalize ->442E00, static up/roll0.
        # Expected bits 3f5f7484/3e5f7485/3edf7485 distinguish one normalize.
        self.assertEqual(bridge.snapshot()['bugs'][0]['direction'],
                         [0.8728716373443604,0.21821792423725128,0.43643584847450256])

    def test_zero_target_direction_uses_original_body_fallback_before_force(self):
        from bugbits import web_data
        from bugbits.web_bridge import WebBridge
        game = normal_game(direction_factor=20,target=(0.,0.,0.))
        bridge = WebBridge()
        opened = bridge.init('zero-direction',2026,web_data.level_to_dict(game.level),
                             web_data.world_to_dict(game.world),
                             {'ant':web_data.unit_to_dict(game.units['ant'])},
                             {'buyable':['ant']})
        bridge.submit({'type':'buy','commandId':'zero-buy',
                       'sessionId':opened['sessionId'],'unit':'ant','lane':0})
        bridge.advance(4)
        actor = bridge.snapshot()['bugs'][0]
        # 443090 zero input selects raw(0,1,0), canonical(-1,0,0).
        # Direction changes force, while position still uses OLD V(+1.9).
        self.assertEqual(actor['direction'],[-1.,0.,0.])
        self.assertAlmostEqual(actor['pos'][0],.095,places=6)
        motion = bridge.audit_state()['bugs'][0]['motion']
        self.assertAlmostEqual(motion['velocity'][0],-.095,places=6)

    def test_zero_direction_factor_keeps_start_heading_despite_a_sideways_target(self):
        game = normal_game(direction_factor=0,target=(0.,0.,1000.))
        actor = game.spawn_free(0,'ant',0)
        game.run(4)
        self.assertAlmostEqual(actor.pos(game)[0],.28025,places=6)
        self.assertEqual(actor.pos(game)[1:],(0.,0.))
        turning = normal_game(target=(0.,0.,1000.))
        rotated = turning.spawn_free(0,'ant',0)
        turning.run(4)
        self.assertGreater(rotated.pos(turning)[2],0.)

    def test_mass_scaled_force_preserves_acceleration_and_hash_distinguishes_configuration(self):
        light = normal_game(mass=1); heavy = normal_game(mass=2)
        a = light.buy(0,'ant',0); b = heavy.buy(0,'ant',0)
        self.assertEqual(a.pos(light),b.pos(heavy))
        self.assertNotEqual(light.state_hash(),heavy.state_hash())
        for _ in range(4):
            light.step(); heavy.step()
            self.assertEqual(a.pos(light),b.pos(heavy))
        self.assertAlmostEqual(b.pos(heavy)[0],.28025,places=6)

    def test_strict_arrival_keeps_free_position_and_selects_next_leg_on_a_later_call(self):
        game = normal_game(target=(20.,0.,0.)); actor = game.buy(0,'ant',0)
        game.run(2)
        self.assertEqual(actor.route_target,'B')
        game.step()  # Exactly20 is not arrival.
        self.assertEqual(actor.route_current,'A')
        self.assertEqual(actor.route_target,'B')
        self.assertAlmostEqual(actor.pos(game)[0],.095,places=6)
        game.step()  # Strictly less20 updates logical CC, without a snap.
        self.assertEqual(actor.route_current,'B')
        self.assertIsNone(actor.route_target)
        self.assertAlmostEqual(actor.pos(game)[0],.28025,places=6)
        game.step()
        self.assertTrue(actor.route_returning)
        self.assertEqual(actor.route_target,'A')
        self.assertGreater(actor.pos(game)[0],.28025)
        self.assertLess(actor.pos(game)[0],20.)

    def test_acceleration_changes_public_birth_trajectory_without_instant_speed(self):
        moving = normal_game(); still = normal_game(acceleration=0)
        actor = moving.buy(0,'ant',0); stopped = still.buy(0,'ant',0)
        # R390 stages and R389 collinear finite input: state1 and target
        # selection keep constructor cap0; subsequent calls move with OLD V.
        # This fixture declares engineering synchronous activation/20Hz,
        # not a same-frame original runtime birth assertion.
        expected = (0.,0.,.095,.28025)
        for point in expected:
            moving.step(); still.step()
            self.assertEqual(stopped.pos(still),(0.,0.,0.))
            self.assertAlmostEqual(actor.pos(moving)[0],point,places=6)
            self.assertEqual(actor.pos(moving)[1:],(0.,0.))

    def test_bridge_exposes_birth_heading_and_resets_motion_with_the_session(self):
        from bugbits import web_data
        from bugbits.web_bridge import WebBridge
        game = normal_game(speed=22.5)
        inputs = ('motion-fixture',2026,web_data.level_to_dict(game.level),
                  web_data.world_to_dict(game.world),
                  {'ant':web_data.unit_to_dict(game.units['ant'])},{'buyable':['ant']})
        bridge = WebBridge()
        def buy():
            opened = bridge.init(*inputs)
            ack = bridge.submit({'type':'buy','commandId':'motion-buy',
                                 'sessionId':opened['sessionId'],'unit':'ant','lane':0})
            self.assertTrue(ack['queued'])
            bridge.advance(1)
        buy()
        actor = bridge.snapshot()['bugs'][0]
        self.assertEqual(actor['pos'],[0.,0.,0.])
        self.assertEqual(actor['direction'],[1.,0.,0.])
        motion = bridge.audit_state()['bugs'][0]['motion']
        self.assertEqual(bridge.audit_state()['bugs'][0]['speed'],22.5)
        self.assertEqual(motion['bodyPosition'],actor['pos'])
        self.assertEqual(motion['position'],[0.,0.,0.])
        # Bridge applies purchases AFTER step, so this is the constructor
        # sample; its first mover call is the next advance tick.
        self.assertEqual(motion['velocity'],[0.,0.,0.])
        self.assertEqual(motion['maxSpeed'],0.)
        self.assertEqual(motion['acceleration'],38.)
        bridge.advance(4)
        self.assertAlmostEqual(bridge.snapshot()['bugs'][0]['pos'][0],.28025,places=6)
        bridge.reset(*inputs)
        self.assertEqual(bridge.snapshot()['bugs'],[])
        self.assertEqual(bridge.audit_state()['bugs'],[])
        buy()
        self.assertEqual(bridge.audit_state()['bugs'][0]['motion'],motion)
        self.assertEqual(bridge.audit_state()['bugs'][0]['speed'],22.5)

    def test_bridge_keeps_body_sample_separate_from_post_mover_route_height(self):
        from bugbits import web_data
        from bugbits.web_bridge import WebBridge
        game = normal_game(target=(1000.,1000.,0.))
        bridge = WebBridge()
        opened = bridge.init('slope',2026,web_data.level_to_dict(game.level),
                             web_data.world_to_dict(game.world),
                             {'ant':web_data.unit_to_dict(game.units['ant'])},
                             {'buyable':['ant']})
        bridge.submit({'type':'buy','commandId':'slope-buy',
                       'sessionId':opened['sessionId'],'unit':'ant','lane':0})
        bridge.advance(4)  # Purchase, transition, selection, first old-V move.
        display = bridge.snapshot()['bugs'][0]
        motion = bridge.audit_state()['bugs'][0]['motion']
        # 45DD60 local-copy precedes R390 route height: body Y0 while
        # projection on a 45-degree line gives .0475, then 2dt correction.
        self.assertAlmostEqual(display['pos'][0],.095,places=6)
        self.assertEqual(display['pos'][1],0.)
        self.assertEqual(motion['bodyPosition'],display['pos'])
        self.assertAlmostEqual(motion['position'][1],.00475,places=6)
        self.assertGreater(display['direction'][1],0.)


if __name__ == '__main__':
    unittest.main()
