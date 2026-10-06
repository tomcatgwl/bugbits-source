"""Real pickup lifecycle and independent current-position carry recurrence."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from bugbits import unitdb,web_geometry,web_bridge
from bugbits.sim import combat
from test_sim_gather import make_sim,make_ready_sim,advance_bridge,world_with


class CarriedNectarTests(unittest.TestCase):
    def node(self,code):
        r=subprocess.run(['node','-e',code],cwd=ROOT,capture_output=True,text=True,timeout=20)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)

    def test_real_pickup_records_bounded_trajectory_without_changing_deposit(self):
        s=make_ready_sim(world_with([('F',(110,0,0))]));start_tick=s.tick;b=s.buy(0,'ant',0)
        s.run(31);self.assertEqual(b.carry_pickup_tick,-1)
        s.step();self.assertEqual(b.carry_pickup_tick,start_tick+32)
        self.assertEqual(b.carry_source_pos,(110,0,0));self.assertEqual(b.carry_positions,())
        self.assertEqual([e[0] for e in s.events if e[1]=='nectar_pickup'],[start_tick+32])
        s.step();self.assertEqual(len(b.carry_positions),1)
        self.assertAlmostEqual(b.carry_positions[0][0],34.1)
        old=s.state_hash();b.carry_positions=((34.1,1,0),);self.assertNotEqual(old,s.state_hash())
        b.carry_positions=((34.1,0,0),);s.run(30)
        self.assertEqual(s.tick,start_tick+63);self.assertEqual(len(b.carry_positions),10);self.assertEqual(s.nectar[0],10)
        s.step();self.assertEqual(s.nectar[0],13)
        self.assertEqual(b.carry_pickup_tick,-1);self.assertEqual(b.carry_positions,());self.assertIsNone(b.carry_source_pos)
        self.assertEqual([e[0] for e in s.events if e[1]=='deposit'],[start_tick+64])
        self.assertEqual([e[2] for e in s.events if e[1]=='nectar_release'],[(b.bug_id,'deposit')])

    def test_death_clears_carry_history_and_keeps_one_existing_drop(self):
        s=make_ready_sim(world_with([('F',(110,0,0))]));start_tick=s.tick;b=s.buy(0,'ant',0);s.run(33)
        self.assertEqual(b.carry_pickup_tick,start_tick+32)
        death_position=b.pos(s);identity=b.carried_nectar_id
        entity=s.nectar_entities[identity];nectar_position=entity.pos
        visual=(entity.size,entity.core_angle,entity.glow_angle);count=len(s.nectar_entities)
        combat._kill(s,b)
        self.assertEqual(b.carry_pickup_tick,-1);self.assertEqual(b.carry_positions,());self.assertIsNone(b.carry_source_pos)
        # Original 4A87DF reuses bug+4C8 and 49BD85 starts from nectar's own position.
        self.assertEqual(len(s.path_nectar),1);self.assertEqual(s.path_nectar[0].pos,nectar_position)
        self.assertEqual(s.path_nectar[0].nectar_id,identity)
        self.assertIs(s.nectar_entities[identity],entity);self.assertEqual(len(s.nectar_entities),count)
        self.assertEqual(entity.flight_start,nectar_position);self.assertEqual(entity.flight_duration,2)
        self.assertEqual((entity.size,entity.core_angle,entity.glow_angle),visual)
        self.assertIsNone(b.carried_nectar_id)
        self.assertAlmostEqual(death_position[0],34.1)
        self.assertEqual([e[2] for e in s.events if e[1]=='nectar_release'],[(b.bug_id,'death')])

    def test_stationary_wait_ticks_are_sampled_and_no_wallet_deposit_clears(self):
        s=make_ready_sim(world_with([('F',(110,0,0))]));b=s.buy(0,'ant',0);s.run(32)
        b.dialogue_wait_until=s.tick+4;position=b.pos(s);s.run(3)
        self.assertEqual(b.carry_positions,(position,)*3)
        s.step();self.assertNotEqual(b.carry_positions[-1],position)
        # The actual enemy/no-wallet branch must clear even without a deposit event.
        b.side=1;s._enemy_has_wallet=False;s._deposit(b)
        self.assertEqual(b.carry_pickup_tick,-1);self.assertEqual(b.carry_positions,())
        self.assertIsNone(b.carry_source_pos)
        self.assertEqual([e[2] for e in s.events if e[1]=='nectar_release'],[(b.bug_id,'deposit-no-wallet')])

    def test_natural_path_pickup_and_next_flower_cycle_replace_history(self):
        world=world_with([]);s=make_sim(world);s.level.props['NectarOnPaths']=['1']
        from bugbits.sim import Sim
        path_sim=Sim(s.level,world,s.units,seed=42);bug=path_sim.buy(0,'ant',0)
        self.assertEqual(len(path_sim.path_nectar),1);source=path_sim.path_nectar[0].pos
        for _ in range(200):
            path_sim.step()
            if bug.carrying:break
        self.assertTrue(bug.carrying);self.assertEqual(bug.target,('item',0))
        self.assertTrue(path_sim.path_nectar[0].taken);self.assertEqual(bug.carry_source_pos,source)
        self.assertEqual(bug.carry_positions,())
        # A second real regeneration/patrol cycle must reset, rather than reuse, the first history.
        s=make_ready_sim(world_with([('F',(110,0,0))]));bug=s.buy(0,'ant',0);s.run(42)
        self.assertEqual(len(bug.carry_positions),10);first=bug.carry_pickup_tick
        for _ in range(1000):
            s.step()
            if bug.carry_pickup_tick>first:break
        self.assertGreater(bug.carry_pickup_tick,first);self.assertEqual(bug.carry_positions,())
        self.assertEqual(bug.carry_source_pos,(110,0,0))

    def test_radius_source_and_carrier_contract_survive_real_export(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as directory:
            record=web_geometry.export_geometry_assets(('ant',),(),out_dir=directory,pose_policy='engine-pose-v1',sample_hz=1,min_frames=2,max_frames=2)
            scene=json.loads((Path(directory)/record['file']).read_text());u=scene['units']['ant']
            self.assertEqual(scene['nectarCarryContract'],'same-bug-radius-trajectory-v1')
            self.assertEqual(u['radius'],5);self.assertEqual(u['radius'],unitdb.load_unit('ant').radius)
            self.assertEqual(u['radiusSource'],'scripts/bugs/ant.vsc')
            self.assertEqual(u['radiusSourceSHA256'],scene['inputHashes'][u['radiusSource']])
            for value in (-1,True,float('nan')):
                bad=copy.deepcopy(scene);bad['units']['ant']['radius']=value
                with self.assertRaises(ValueError):web_geometry.validate_geometry(bad)

    def test_current_position_recurrence_bounded_history_and_radius_once(self):
        self.node("""
const assert=require('assert'),api=require('./web/mesh_scene.js');
const c={scope:'pickup-trajectory-20hz-v1',tick:40,positions:[[10,0,0],[20,0,0]]};
const p=api.nectarCarryPosition(c,[0,0,0],[20,0,0],5,42);
assert(Math.abs(p[0]-4.8)<1e-6);assert(Math.abs(p[1]-1.4)<1e-6);assert.strictEqual(p[2],0);
const seed={...c,positions:[]};assert.deepStrictEqual(api.nectarCarryPosition(seed,[1,2,3],[9,8,7],11,40),[1,2,3]);
const mature={...c,positions:Array.from({length:10},(_,i)=>[i,0,0])};
assert.deepStrictEqual(api.nectarCarryPosition(mature,[1,2,3],[30,7,2],11,51),[30,18,2]);
assert.strictEqual(JSON.stringify(c),JSON.stringify({scope:'pickup-trajectory-20hz-v1',tick:40,positions:[[10,0,0],[20,0,0]]}));
for(const bad of [{...c,positions:[]},{...c,positions:new Array(2)},{...c,tick:43},{...c,scope:'RAF-clock'}])assert.throws(()=>api.nectarCarryPosition(bad,[0,0,0],[20,0,0],5,42));
""")

    def test_bridge_batch_snapshot_deep_copy_and_reset(self):
        world=world_with([('F',(110,0,0))]);s=make_sim(world)
        bridge=web_bridge.WebBridge();info=bridge.from_objects(s.level,world,s.units,42,{'buyable':['ant']})
        advance_bridge(bridge,368)  # Natural birth with legal public batches.
        start_tick=bridge.snapshot()['tick']
        self.assertTrue(bridge.submit({'sessionId':info['sessionId'],'commandId':'real-ant','type':'buy','targetTick':start_tick+1,'unit':'ant','lane':0})['queued'])
        for _ in range(6):self.assertEqual(bridge.advance(5)['advanced'],5)
        self.assertEqual(bridge.advance(4)['advanced'],4)
        snapshot=bridge.snapshot();bug=snapshot['bugs'][0];carry=bug['carryingNectar']
        self.assertEqual(carry['scope'],'pickup-trajectory-20hz-v1')
        self.assertEqual(len(carry['positions']),start_tick+34-carry['tick'])
        self.assertEqual(carry['source']['name'],'F');self.assertEqual(carry['source']['positionYup'],[110,0,0])
        carry['positions'][0][0]=999;carry['source']['positionYup'][0]=999
        fresh=bridge.snapshot()['bugs'][0]['carryingNectar']
        self.assertNotEqual(fresh['positions'][0][0],999);self.assertEqual(fresh['source']['positionYup'][0],110)
        self.assertEqual(bridge.audit_state()['bugs'][0]['carryPositions'],fresh['positions'])
        for _ in range(6):self.assertEqual(bridge.advance(5)['advanced'],5)
        bridge.advance(1);self.assertIsNone(bridge.snapshot()['bugs'][0]['carryingNectar'])
        old=bridge.snapshot()['sessionId'];bridge.dispose()
        new=bridge.from_objects(s.level,world,s.units,42,{'buyable':['ant']})
        self.assertNotEqual(new['sessionId'],old);self.assertEqual(bridge.snapshot()['bugs'],[])

    def test_host_carry_starts_at_effective_bind_point_and_path_uses_real_position(self):
        self.node("""
const assert=require('assert'),fs=require('fs'),vm=require('vm'),api=require('./web/mesh_scene.js');
const I=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];
const asset={frameBasis:'raw-model-v1',rootApplied:false,scaleApplied:false,rootPolicy:'engineering-prop-bind-v1',coordinatePolicy:'raw-to-engine-yup-Q-v1',anchorPolicy:'raw-model-origin-v1',rootMatrix:I,attachments:{nektar:{positionRaw:[1,2,3]}}};
const prop={id:'flower:f',assetId:'flower_a',positionYup:[10,20,30],scaleFactor:2,ownerMatrix:I,parentMatrix:I,transformScope:'engineering-bind-owner-v1',transformPolicy:'engine-prop-v1'};
const assets={nectarSprites:{contract:'bind-flower-nectar-v1',texture:'core',glowTexture:'glow'},nectarCarryContract:'same-bug-radius-trajectory-v1',props:{flower_a:asset},units:{ant:{radius:5},bee:{radius:11}},worlds:{world_01:{propVariants:{normal:[{name:'f',directionRaw:[0,1,0]}]}}}};
const render={meshAssets:assets},ctx=vm.createContext({render,state:{world:'world_01'},TICK_HZ:20,BugBitsMeshScene:api});
const source=fs.readFileSync('web/host.js','utf8');vm.runInContext(source.slice(source.indexOf('function meshNectarRecords('),source.indexOf('// Mesh nectar adapter end')),ctx);
const carry={scope:'pickup-trajectory-20hz-v1',nectarId:1,tick:40,positions:[],source:{kind:'flower',index:0,name:'f',positionYup:[10,20,30]}};
const bug={id:7,unit:'ant',pos:[1,2,3],carrying:1,dead:0,carryingNectar:carry};
const nectar=id=>({scope:'nectar-fields-f32-v1',id,bornTick:0,alive:true,size:2,glowSize:3,coreAngle:.5,glowAngle:-.25,flight:{duration:0}});
const snapshot={tick:40,nectarLifecycle:{scope:'nectar-identity-substeps-v1'},nectarEntities:[nectar(1),nectar(2),nectar(3)],flowers:[{name:'f',nectar:0}],pathNectar:[],bugs:[bug]};
const records=ctx.meshNectarRecords(snapshot,[prop]),expected=api.transformPropVertex([1,2,3],asset,api.effectivePropRecord(assets,'world_01',true,prop)).map(Math.fround);
assert.strictEqual(records.length,2);assert.deepStrictEqual(Array.from(records[0].positionYup),expected);
assert.notDeepStrictEqual(expected,carry.source.positionYup);assert.strictEqual(records[0].pickupPositionScope,'current-bind-flower-attachment-v1');
// Omitting submitted props for a pixel audit must retain the physical pickup source.
assert.deepStrictEqual(Array.from(ctx.meshNectarRecords(snapshot,[],[prop])[0].positionYup),expected);
assert.strictEqual(JSON.stringify(records),JSON.stringify(ctx.meshNectarRecords(snapshot,[prop])));
const mature={...carry,positions:Array.from({length:10},()=>[1,2,3])};
const stable={...snapshot,tick:51,bugs:[{...bug,unit:'bee',pos:[30,7,2],carryingNectar:mature}]};
assert.deepStrictEqual(Array.from(ctx.meshNectarRecords(stable,[prop])[0].positionYup),[30,18,2]);
assert.strictEqual(ctx.meshNectarRecords({...snapshot,bugs:[{...bug,dead:1}]},[prop]).length,0);
assert.strictEqual(ctx.meshNectarRecords({...snapshot,bugs:[{...bug,carrying:0}]},[prop]).length,0);
const paths=ctx.meshNectarRecords({...snapshot,bugs:[],pathNectar:[{id:9,nectarId:2,pos:[4,5,6],taken:false},{id:10,nectarId:3,pos:[99,99,99],taken:true}]},[prop]);
assert.strictEqual(paths.length,2);assert.deepStrictEqual(Array.from(paths[0].positionYup),[4,5,6]);assert.strictEqual(paths[0].id,'path-nectar:9');
assert.throws(()=>ctx.meshNectarRecords({...snapshot,bugs:[{...bug,carryingNectar:null}]},[prop]));
""")
