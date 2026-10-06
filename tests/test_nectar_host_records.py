"""Named flower join and snapshot-only nectar animation; no original clock claim."""
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]


class NectarHostTests(unittest.TestCase):
    def test_empty_path_does_not_hide_named_attachment_and_repeat_is_stable(self):
        body="""
const assert=require('assert'),fs=require('fs'),vm=require('vm');
const render={meshAssets:{nectarSprites:{contract:'bind-flower-nectar-v1',texture:'core',glowTexture:'glow'},props:{flower_a:{attachments:{nektar:{}}}}}};
const ctx=vm.createContext({render,TICK_HZ:20}),source=fs.readFileSync('web/host.js','utf8');
vm.runInContext(source.slice(source.indexOf('function meshNectarRecords('),source.indexOf('// Mesh nectar adapter end')),ctx);
const entity={scope:'nectar-fields-f32-v1',id:1,bornTick:0,alive:true,size:.09999999403953552,glowSize:.14921462535858154,coreAngle:.03141592815518379,glowAngle:-.015707964077591896};
const props=[{id:'flower:f',assetId:'flower_a'}],snapshot={tick:2,nectarLifecycle:{scope:'nectar-identity-substeps-v1'},nectarEntities:[entity],pathNectar:[],flowers:[{name:'f',nectar:1,nectarId:1}]};
const a=ctx.meshNectarRecords(snapshot,props);assert.strictEqual(a.length,2);
assert.strictEqual(a[0].width,.09999999403953552);assert.strictEqual(a[0].angleRadians,.03141592815518379);
assert.strictEqual(a[0].attachment.propId,'flower:f');assert(!('positionYup' in a[0]));
assert.deepStrictEqual(Array.from(a[1].rgbaBytes),[255,255,192,255]);
assert.strictEqual(JSON.stringify(ctx.meshNectarRecords(snapshot,props)),JSON.stringify(a));
assert.strictEqual(ctx.meshNectarRecords({...snapshot,flowers:[{name:'f',nectar:0}]},props).length,0);
assert.strictEqual(ctx.meshNectarRecords({...snapshot,tick:100},props)[0].width,a[0].width);
assert.strictEqual(ctx.meshNectarRecords({...snapshot,tick:0,nectarEntities:[{...entity,size:0,glowSize:0,coreAngle:0,glowAngle:0}]},props)[0].width,0);
assert.throws(()=>ctx.meshNectarRecords({...snapshot,nectarEntities:[]},props));
assert.strictEqual(ctx.meshNectarRecords(snapshot,[]).length,0);
assert.throws(()=>ctx.meshNectarRecords({...snapshot,tick:NaN},props));
render.meshAssets.props.flower_a.attachments={};assert.strictEqual(ctx.meshNectarRecords(snapshot,props).length,0);
delete render.meshAssets.nectarSprites;assert.strictEqual(ctx.meshNectarRecords(snapshot,props).length,0);
"""
        result=subprocess.run(['node','-e',body],cwd=ROOT,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
