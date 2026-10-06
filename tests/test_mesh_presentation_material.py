"""Public material/light/owner interface literal checks; GPU tests cover actual draws."""
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]

class MaterialInterfaceTests(unittest.TestCase):
    def test_original_literals_and_invalid_same_tick_states(self):
        source=r'''
const assert=require('assert'),api=require('./web/presentation_material.js');
const state={version:'setlight-state-v1',scope:'fixed-20hz-static-setlight-v1',tick:0,requestTick:0,source:'level',sourceTokens:['0','ffffa0d0','20303060','ffa0a0ff','.7','10','0','0','180'],current:{colors:[0xffffa0d0,0x20303060,0xffa0a0ff],scalars:[.7,180],anglesDegrees:[10,0,0]},duration:0,requestedDuration:0,transitionElapsed:0,transitionActive:false};
state.target=JSON.parse(JSON.stringify(state.current));
const snapshot={tick:0,presentation:{lightState:state}},light=api.frameLight(snapshot),near=(actual,expected)=>assert.ok(actual.every((x,i)=>Math.abs(x-expected[i])<1e-7));
near(light.light,[.2196078431372549,.2196078431372549,.35]);
near(light.direction,[.984807753012208,.1736481769517666,0]);
assert.deepStrictEqual(light.ambientBytes,[48,48,96]);
state.current={colors:[0xffc0c0ff,0x20242420,0xffffffff],scalars:[1,200],anglesDegrees:[40,0,-30]};
near(api.frameLight(snapshot).direction,[.6634139481689384,.6427876096865394,-.383022221559489]);
near(api.frameLight(snapshot).light,[.5,.5,.5]);
near(api.owner([-.533944726,-.8455193639,0]),[-.8455193786318751,0,.533944735303166,0,0,1,0,0,-.533944735303166,0,-.8455193786318751,0,0,0,0,1]);
for(const d of [[0,0,0],[0,0,1],[NaN,1,0]])assert.throws(()=>api.owner(d));
assert.throws(()=>api.frameLight({...snapshot,tick:1}));
const sparse=JSON.parse(JSON.stringify(snapshot));sparse.presentation.lightState.current.scalars=new Array(2);assert.throws(()=>api.frameLight(sparse));
const huge=JSON.parse(JSON.stringify(snapshot));huge.presentation.lightState.current.scalars[0]=1e308;assert.throws(()=>api.frameLight(huge));
for(const mutate of [s=>s.current.colors[0]=-1,s=>s.current.scalars[0]=NaN,s=>s.current.anglesDegrees[1]=20,s=>s.duration=-1,s=>s.requestTick=2,s=>s.sourceTokens[1]='']){
const bad=JSON.parse(JSON.stringify(snapshot));mutate(bad.presentation.lightState);assert.throws(()=>api.frameLight(bad));}
assert.equal(api.group('other',0),null);
console.log('PASS original light/owner literals and malformed snapshot rejection');
'''
        result=subprocess.run(['node','-e',source],cwd=ROOT,text=True,capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

if __name__=='__main__':unittest.main()
