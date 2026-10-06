"""Ordinary nongather public movement; finite original controller contract."""
import unittest

from bugbits import level, sim, unitdb, worlddb


def ordinary_game(*, acceleration=35, direction_factor=10, speed=14,
                  target=(0.,0.,1000.), end=(2000.,0.,0.), terminal_start=False,
                  level_type='battle'):
    spec=unitdb.load_unit('littlebeetle')
    spec.props['Acceleration']=[str(acceleration)]
    spec.props['DirectionFactor']=[str(direction_factor)]
    spec.props['Speed']=[str(speed)]
    unitdb.apply_props(spec)
    starts=[worlddb.Start('A',(0.,0.,0.),(1.,0.,0.),0,0,[] if terminal_start else ['B']),
            worlddb.Start('E',end,(1.,0.,0.),1,0,[])]
    nodes=[worlddb.Waypoint('B',target,(1.,0.,0.),False,['E'])]
    world=worlddb.WorldData({},[],[],None,starts,nodes,2,
                            {'A':{'B'},'B':{'A','E'},'E':{'B'}})
    lv=level.LevelData({'Type':[level_type],'InitialNectar':['1000'],'NectarOnPaths':['0'],
                        'PlayerBaseSize':['100'],'EnemyBaseSize':['100']})
    return sim.Sim(lv,world,{'littlebeetle':spec},2026)


class NongatherMotion(unittest.TestCase):
    def test_bridge_uses_duration_and_hash_distinguishes_same_display_future(self):
        from bugbits import web_data
        from bugbits.web_bridge import WebBridge
        base=ordinary_game(target=(1.,0.,0.),end=(1000.,0.,0.))
        inputs=('nongather-base-text',2026,web_data.level_to_dict(base.level),
                web_data.world_to_dict(base.world),
                {'littlebeetle':web_data.unit_to_dict(base.units['littlebeetle'])},
                {'buyable':['littlebeetle']})
        bridge=WebBridge();opened=bridge.init(*inputs)
        bridge.submit({'type':'buy','commandId':'base-buy','sessionId':opened['sessionId'],
                       'unit':'littlebeetle','lane':0})
        bridge.advance(5)  # buy then four mover calls to terminal selection.
        self.assertEqual(bridge.snapshot()['bugs'][0]['dialogue'],'BUGCHAT_BASE_LITTLEBEETLE')
        self.assertEqual(bridge.audit_state()['bugs'][0]['dialogueDuration'],7.)
        self.assertEqual(bridge.audit_state()['bugs'][0]['dialogueWait'],0.)
        for _ in range(139):
            advanced=bridge.advance(1)
            self.assertEqual(advanced['advanced'],1)
            self.assertNotIn('error',advanced)
        self.assertEqual(bridge.snapshot()['bugs'][0]['dialogue'],'BUGCHAT_BASE_LITTLEBEETLE')
        bridge.advance(1)
        self.assertIsNone(bridge.snapshot()['bugs'][0]['dialogue'])
        for alternative in ({'duration':10.,'wait':0.},{'duration':7.,'wait':3.}):
            short=ordinary_game();other=ordinary_game()
            a=short.buy(0,'littlebeetle',0);b=other.buy(0,'littlebeetle',0)
            short.set_dialogue(a,'BUGCHAT_BASE_LITTLEBEETLE',0.,duration=7.,wait=0.)
            other.set_dialogue(b,'BUGCHAT_BASE_LITTLEBEETLE',0.,**alternative)
            self.assertEqual(a.pos(short),b.pos(other))
            self.assertEqual(a.dialogue_text,b.dialogue_text)
            self.assertNotEqual(short.state_hash(),other.state_hash())

    def test_explicit_idle_keeps_ground_defender_stationary_and_alive(self):
        # Public engineering idle contract used by Bot(defend=True), not a
        # claim that the native controller's state1 is permanently stationary.
        for birth in ('buy','spawn_free'):
            with self.subTest(birth=birth):
                game=ordinary_game()
                actor=getattr(game,birth)(0,'littlebeetle',0)
                actor.mode='idle'
                position=actor.pos(game)
                game.run(10)
                self.assertEqual(actor.mode,'idle')
                self.assertEqual(actor.pos(game),position)
                self.assertFalse(actor.dead)
        game=ordinary_game(terminal_start=True)
        actor=game.buy(0,'littlebeetle',0)
        game.step()  # normal state1 schedules4; explicit idle overrides marching.
        actor.mode='idle'
        game.run(2)
        self.assertFalse(actor.dead)
        self.assertEqual(game.hives[1].hp,100)

    def test_export_closure_includes_original_nongather_base_text(self):
        from bugbits import web_build
        lv=level.LevelData({'Type':['battle'],'World':['world_01']},
                           bug_setups=[(0,'littlebeetle',3)])
        closure=web_build.LevelClosure('nongather-text',lv)
        self.assertIn('BUGCHAT_BASE_LITTLEBEETLE',closure.text_keys)

    def test_terminal_start_preserves_state1_and_menu_damage_bypass(self):
        for level_type in ('battle','menu'):
            with self.subTest(level_type=level_type):
                game=ordinary_game(terminal_start=True,level_type=level_type)
                actor=game.buy(0,'littlebeetle',0)
                hp=game.hives[1].hp
                game.step()  # Native state1 only schedules state4.
                self.assertFalse(actor.dead)
                self.assertEqual(game.hives[1].hp,hp)
                game.step()  # Forward current-zero business; menu still dies.
                self.assertTrue(actor.dead)
                self.assertEqual(actor.hp,0)
                self.assertEqual(game.hives[1].hp,hp-(level_type=='battle'))

    def test_returning_state_bypasses_forward_terminal_business(self):
        game=ordinary_game(terminal_start=True)
        actor=game.buy(0,'littlebeetle',0)
        # Explicit valid runtime43E input; not proof of a native spawn writer.
        actor.route_returning=True
        game.run(2)
        self.assertFalse(actor.dead)
        self.assertFalse([e for e in game.events if e[1]=='hive_damage'])

    def test_zero_direction_factor_keeps_start_heading_and_force_axis(self):
        game=ordinary_game(direction_factor=0)
        actor=game.spawn_free(0,'littlebeetle',0)
        game.run(4)
        self.assertGreater(actor.pos(game)[0],0.)
        self.assertEqual(actor.pos(game)[1:],(0.,0.))

    def test_nongather_fork_uses_dry_local_target_instead_of_short_water_path(self):
        starts=[worlddb.Start('A',(0.,0.,0.),(1.,0.,0.),0,0,['W','D']),
                worlddb.Start('E',(2000.,0.,0.),(1.,0.,0.),1,0,[])]
        nodes=[worlddb.Waypoint('W',(10.,0.,0.),(1.,0.,0.),True,['M']),
               worlddb.Waypoint('D',(0.,0.,100.),(1.,0.,0.),False,['M']),
               worlddb.Waypoint('M',(1000.,0.,0.),(1.,0.,0.),False,['E'])]
        world=worlddb.WorldData({},[],[],None,starts,nodes,2,
                               {'A':{'W','D'},'W':{'A','M'},'D':{'A','M'},
                                'M':{'W','D','E'},'E':{'M'}})
        base=ordinary_game()
        game=sim.Sim(base.level,world,base.units,2026)
        actor=game.buy(0,'littlebeetle',0)
        game.run(2)
        self.assertEqual(actor.route_target,'D')  # Native dry0 vs water-500.
        self.assertEqual(actor.pos(game),(0.,0.,0.))  # Selection cap remains0.
        game.run(2)
        self.assertGreater(actor.pos(game)[2],0.)

    def test_fractional_and_missing_speed_reach_nongather_birth_and_bridge_reset(self):
        for birth in ('buy','spawn_free'):
            with self.subTest(birth=birth):
                game=ordinary_game(speed=14.5)
                actor=getattr(game,birth)(0,'littlebeetle',0)
                self.assertEqual(actor.speed,14.5)
                base=ordinary_game()
                spec=base.units['littlebeetle']
                spec.props.pop('Speed');unitdb.apply_props(spec)
                game=sim.Sim(base.level,base.world,base.units,2026)
                actor=getattr(game,birth)(0,'littlebeetle',0)
                self.assertEqual(actor.speed,10.)
        from bugbits import web_data
        from bugbits.web_bridge import WebBridge
        base=ordinary_game(speed=14.5)
        inputs=('nongather',2026,web_data.level_to_dict(base.level),
                web_data.world_to_dict(base.world),
                {'littlebeetle':web_data.unit_to_dict(base.units['littlebeetle'])},
                {'buyable':['littlebeetle']})
        bridge=WebBridge();opened=bridge.init(*inputs)
        bridge.submit({'type':'buy','commandId':'lb-buy','sessionId':opened['sessionId'],
                       'unit':'littlebeetle','lane':0})
        bridge.advance(1)
        actor=bridge.snapshot()['bugs'][0]
        audit=bridge.audit_state()['bugs'][0]
        self.assertEqual(actor['direction'],[1.,0.,0.])
        self.assertEqual(audit['speed'],14.5)
        self.assertEqual(audit['motion']['mass'],1.5)
        self.assertEqual(audit['motion']['position'],actor['pos'])
        bridge.reset(*inputs)
        self.assertEqual(bridge.snapshot()['bugs'],[])
        slow=ordinary_game(speed=14.5);fast=ordinary_game(speed=14.75)
        slow.buy(0,'littlebeetle',0);fast.buy(0,'littlebeetle',0)
        self.assertNotEqual(slow.state_hash(),fast.state_hash())

    def test_selected_terminal_base_text_displays_seven_seconds_without_wait(self):
        game=ordinary_game(target=(1.,0.,0.),end=(1000.,0.,0.))
        actor=game.buy(0,'littlebeetle',0)
        game.run(4)  # transition, select B, arrive B, select terminal E.
        self.assertEqual(actor.route_target,'E')
        self.assertFalse(actor.route_returning)
        self.assertEqual(actor.dialogue_text,'BUGCHAT_BASE_LITTLEBEETLE')
        self.assertEqual(actor.dialogue_delay,0.)
        self.assertEqual(actor.dialogue_duration,7.)
        self.assertEqual(actor.dialogue_wait,0.)
        game.run(139)
        self.assertEqual(actor.dialogue_text,'BUGCHAT_BASE_LITTLEBEETLE')
        self.assertFalse(actor.dead)
        game.step()
        self.assertEqual(actor.dialogue_text,'')
        self.assertFalse([e for e in game.events if e[1]=='dialogue_wait'])
        self.assertGreater(actor.pos(game)[0],1.)

    def test_terminal_business_hits_hive_once_without_progress_or_gather_return(self):
        game=ordinary_game(target=(20.,0.,0.),end=(40.,0.,0.))
        actor=game.buy(0,'littlebeetle',0)
        initial_hp=game.hives[1].hp
        for _ in range(120):
            game.step()
            if actor.dead:
                break
        self.assertTrue(actor.dead)
        self.assertEqual(actor.hp,0)
        self.assertEqual(actor.route_current,'E')
        self.assertFalse(actor.route_returning)
        self.assertEqual(actor.progress_sub,0)  # No synthetic legacy arrival.
        self.assertEqual(game.hives[1].hp,initial_hp-1)
        self.assertLess(actor.pos(game)[0],40.)  # strict20 logical arrival, no snap.
        hits=[e for e in game.events if e[1]=='hive_damage']
        self.assertEqual(len(hits),1)
        game.run(10)
        self.assertEqual([e for e in game.events if e[1]=='hive_damage'],hits)

    def test_zero_acceleration_keeps_buy_and_spawn_at_constructor_position(self):
        for birth in ('buy','spawn_free'):
            with self.subTest(birth=birth):
                game=ordinary_game(acceleration=0)
                actor=getattr(game,birth)(0,'littlebeetle',0)
                self.assertIsNotNone(actor)
                game.run(4)
                self.assertEqual(actor.pos(game),(0.,0.,0.))
                self.assertFalse(actor.can_gather)
                self.assertFalse(actor.route_returning)


if __name__=='__main__':unittest.main()
