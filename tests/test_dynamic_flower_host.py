"""Host consumes snapshot phase and cached physical source, without frame clock."""
from pathlib import Path
import subprocess
import unittest
ROOT=Path(__file__).resolve().parents[1]


class DynamicFlowerHostTests(unittest.TestCase):
    def test_phase_and_cached_sprite_ignore_current_node_and_freeze_carry(self):
        body=r'''
const assert=require('assert'),fs=require('fs'),vm=require('vm'),api=require('./web/mesh_scene.js');
const I=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];
const asset={animationScope:'normal-flower-node-keys-v1',animationRig:{rigSHA256:'a'.repeat(64),duration:1},attachments:{nektar:{positionRaw:[999,999,999]}}};
const instance={name:'f',flowerType:1,assetId:'flower_a',positionYup:[0,0,0],scaleFactor:2.5,ownerMatrix:I,parentMatrix:I,transformScope:'engineering-bind-owner-v1',transformPolicy:'engine-prop-v1'};
const render={meshAssets:{props:{flower_a:asset},worlds:{w:{propInstances:[instance]}},nectarSprites:{contract:'bind-flower-nectar-v1',texture:'core',glowTexture:'glow'},nectarCarryContract:'same-bug-radius-trajectory-v1',units:{ant:{radius:5}}}};
const state={world:'w',levelId:'level_01'},ctx=vm.createContext({render,state,TICK_HZ:20,BugBitsMeshScene:api});
const src=fs.readFileSync('web/host.js','utf8');vm.runInContext(src.slice(src.indexOf('function meshPropRecords('),src.indexOf('// Mesh nectar adapter end')),ctx);
const flower={name:'f',type:1,pos:[0,0,0],nectar:1,nectarId:7,cycle:{scope:'normal-flower-animation-edge-f32-v1',phase:1,duration:1},pose:{scope:'cached-world-pose-20hz-v1',phase:1,cachedPositionYup:[11,12,13],generation:4,rigSHA256:'a'.repeat(64)}};
const entity={scope:'nectar-fields-f32-v1',id:7,bornTick:0,alive:true,size:5,glowSize:7,coreAngle:.1,glowAngle:.2,positionYup:[4,5,6]};
const snapshot={tick:4,flowers:[flower],nectarLifecycle:{scope:'nectar-identity-substeps-v1'},nectarEntities:[entity],pathNectar:[],bugs:[]};
const props=ctx.meshPropRecords(snapshot);assert.strictEqual(props[0].animationPhase,1);
const sprites=ctx.meshNectarRecords(snapshot,props);assert.deepStrictEqual(Array.from(sprites[0].positionYup),[4,5,6]);assert(!sprites[0].attachment);assert.strictEqual(sprites[0].placementPolicy,'snapshot-cached-flower-position-v1');
assert.strictEqual(JSON.stringify(ctx.meshNectarRecords(snapshot,props)),JSON.stringify(sprites));
const carry={scope:'pickup-trajectory-20hz-v1',tick:4,nectarId:7,positions:[],source:{kind:'flower',name:'f',index:0,positionYup:[4,5,6],positionScope:'snapshot-cached-flower-position-v1'}};
const carrying={...snapshot,flowers:[{...flower,nectar:0}],bugs:[{id:1,unit:'ant',carrying:1,dead:false,pos:[80,0,0],carryingNectar:carry}]};
const c=ctx.meshNectarRecords(carrying,props);assert.deepStrictEqual(Array.from(c[0].positionYup),[4,5,6]);assert.strictEqual(c[0].pickupPositionScope,'snapshot-cached-flower-position-v1');
asset.attachments.nektar.positionRaw=[-999,-999,-999];assert.deepStrictEqual(Array.from(ctx.meshNectarRecords(carrying,props)[0].positionYup),[4,5,6]);
assert.throws(()=>ctx.meshPropRecords({...snapshot,flowers:[{...flower,cycle:undefined}]}));
assert.throws(()=>ctx.meshPropRecords({...snapshot,flowers:[{...flower,cycle:{...flower.cycle,phase:NaN}}]}));
'''
        result=subprocess.run(['node','-e',body],cwd=ROOT,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
