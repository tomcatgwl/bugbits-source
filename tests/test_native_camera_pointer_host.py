"""Real host DOM input reaches the Bridge before the next world update."""
import json
from pathlib import Path
import subprocess
import unittest

from bugbits.web_bridge import bridge_call

ROOT = Path(__file__).resolve().parents[1]

HOST = r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const messages=[],listeners={},elements={},timers=new Set();let timerId=0;
let rect={left:100,top:200,width:640,height:480};
function element(){return {hidden:false,style:{setProperty(){}},
 addEventListener(){},getBoundingClientRect:()=>rect};}
const document={getElementById:id=>elements[id]||(elements[id]=element()),
 addEventListener(type,callback){listeners[type]=callback;}};
class Worker {postMessage(message){messages.push(JSON.parse(JSON.stringify(message)));}}
const window={devicePixelRatio:1};
const scope=vm.createContext({document,window,Worker,URLSearchParams,
 location:{search:''},performance:{now:()=>0},
 setTimeout:()=>{const id=++timerId;timers.add(id);return id;},clearTimeout:id=>timers.delete(id),
 requestAnimationFrame:()=>1,cancelAnimationFrame(){},console});
vm.runInContext(input.host,scope);
vm.runInContext(`state.ready=true;state.sessionId=${JSON.stringify(input.sessionId)};
 state.generation=1;state.phase='running';state.paused=false;`,scope);
const move=(x,y,type='mouse')=>document && listeners.pointermove({clientX:x,clientY:y,pointerType:type});
'''


class NativeCameraPointerHost(unittest.TestCase):
    def run_host(self, behavior, bridge, **extra):
        result = subprocess.run(['node', '-e', HOST + behavior], cwd=ROOT,
            input=json.dumps({'host': (ROOT / 'web/host.js').read_text(),
                              'sessionId': bridge.snapshot()['sessionId'], **extra}),
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_mouse_over_game_viewport_is_sampled_before_next_tick(self):
        from test_native_camera_driver import NativeCameraDriver
        bridge, _ = NativeCameraDriver().opened()
        messages = self.run_host(r'''
assert.equal(typeof listeners.pointermove,'function','production init installs DOM input');
move(420,440);
vm.runInContext('clock.step(50)',scope);
assert.deepEqual(messages.map(m=>m.op),['camera_input','advance']);
assert.deepEqual(messages[0].payload.positionClient,[512,384]);
assert.deepEqual(messages[0].payload.sizeClient,[1024,768]);
assert.equal(messages[0].payload.source,'gameviewport-to-client1024x768-adapter-v1');
assert.equal(messages[0].payload.sequence,1);
console.log(JSON.stringify(messages));
''', bridge)
        for message in messages:
            receipt = json.loads(bridge_call(bridge, message['op'], json.dumps(message['payload'])))
            self.assertTrue(receipt['ok'], receipt)
        snapshot = bridge.snapshot()
        self.assertEqual(snapshot['tick'], 1)
        self.assertEqual(snapshot['nativeCamera']['inputXY'], [800., 600.])
        self.assertEqual(snapshot['nativeCamera']['sampledInputSequence'], 1)

    def test_css_resize_and_dpr_preserve_last_point_until_a_new_mouse_event(self):
        from test_native_camera_driver import NativeCameraDriver
        bridge, _ = NativeCameraDriver().opened()
        messages = self.run_host(r'''
move(420,440);
window.devicePixelRatio=2;rect={left:100,top:200,width:1280,height:960};
assert.equal(messages.length,1,'resize and DPR do not synthesize a mouse event');
vm.runInContext("state.paused=true;state.phase='paused'",scope);
move(420,440);
move(420,440); // Same quantized client point is already submitted.
move(99,440);move(1380,440);move(420,1160);move(NaN,440);move(420,440,'touch');
vm.runInContext("call('snapshot',{})",scope); // A public read flushes the latest paused input.
assert.deepEqual(messages.map(m=>m.op),['camera_input','camera_input','snapshot']);
assert.deepEqual(messages[1].payload.positionClient,[256,192]);
assert.deepEqual(messages[1].payload.sizeClient,[1024,768]);
assert.equal(messages[1].payload.sequence,2);
vm.runInContext("state.phase='loading'",scope);move(200,300);
assert.equal(messages.length,3,'loading has no current viewport input');
console.log(JSON.stringify(messages));
''', bridge)
        for message in messages:
            receipt = json.loads(bridge_call(bridge, message['op'], json.dumps(message['payload'])))
            self.assertTrue(receipt['ok'], receipt)
        self.assertEqual(bridge.snapshot()['tick'], 0)
        self.assertEqual(bridge.snapshot()['nativeCamera']['inputXY'], [0., 0.])
        self.assertEqual(bridge.snapshot()['cameraClientInput']['positionClient'], [256, 192])
        bridge.advance(1)
        self.assertEqual(bridge.snapshot()['nativeCamera']['inputXY'], [400., 300.])

    def test_actual_worker_serializes_input_and_advance_at_python_boundary(self):
        from test_native_camera_driver import NativeCameraDriver
        bridge, _ = NativeCameraDriver().opened()
        js = r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const input=JSON.parse(fs.readFileSync(0,'utf8')),calls=[],replies=[];
const boundary=(op,payload)=>{assert.equal(typeof payload,'string');calls.push({op,payload});
 return JSON.stringify({ok:true,result:{boundaryOnly:true}});};
const scope=vm.createContext({importScripts(){},
 loadPyodide:async()=>({globals:{set(){},get:()=>boundary},runPythonAsync:async()=>{}}),
 fetch:async()=>({ok:true,json:async()=>({'bugbits/web_bridge.py':'boundary fixture'})}),
 postMessage:message=>replies.push(message)});
vm.runInContext(fs.readFileSync('web/worker.js','utf8'),scope);
(async()=>{
 await vm.runInContext('boot()',scope);
 for(const message of input.messages){scope.onmessage({data:message});}
 assert.deepEqual(calls.map(c=>c.op),['camera_input','advance']);
 assert.deepEqual(JSON.parse(calls[0].payload).positionClient,[-20,-30]);
 const responses=replies.filter(r=>r.type==='reply');
 assert.deepEqual(responses.map(r=>r.id),[1,2]);assert(responses.every(r=>r.ok));
 console.log(JSON.stringify(calls));
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
        messages = [dict(id=1, op='camera_input', payload=dict(sessionId=bridge.snapshot()['sessionId'],
                        sequence=1, positionClient=[-20, -30], sizeClient=[1024, 768])),
                    dict(id=2, op='advance', payload=dict(ticks=1))]
        result = subprocess.run(['node', '-e', js], cwd=ROOT, input=json.dumps({'messages': messages}),
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for call in json.loads(result.stdout):
            receipt = json.loads(bridge_call(bridge, call['op'], call['payload']))
            self.assertTrue(receipt['ok'], receipt)
        self.assertEqual(bridge.snapshot()['nativeCamera']['inputXY'], [-31.25, -46.875])

    def test_next_mouse_move_restores_viewport_point_after_newer_public_client_input(self):
        from test_native_camera_driver import NativeCameraDriver
        bridge, _ = NativeCameraDriver().opened()
        messages = self.run_host(r'''
move(420,440);
vm.runInContext("state.lastSnapshot={winner:null,cameraClientInput:{sequence:9,positionClient:[20,30],sizeClient:[2048,1536]}}",scope);
move(420,440);
vm.runInContext("call('snapshot',{})",scope);
assert.equal(messages.length,3,'new authoritative input invalidates old same-point cache');
assert.deepEqual(messages[1].payload.positionClient,[512,384]);
assert.deepEqual(messages[1].payload.sizeClient,[1024,768]);
assert.equal(messages[1].payload.sequence,10);
console.log(JSON.stringify(messages.filter(message=>message.op==='camera_input')));
''', bridge)
        self.assertTrue(json.loads(bridge_call(bridge, messages[0]['op'], json.dumps(messages[0]['payload'])))['ok'])
        self.assertTrue(bridge.camera_input(dict(sessionId=bridge.snapshot()['sessionId'],
            sequence=9, positionClient=[20, 30], sizeClient=[2048, 1536]))['accepted'])
        self.assertTrue(json.loads(bridge_call(bridge, messages[1]['op'], json.dumps(messages[1]['payload'])))['ok'])
        bridge.advance(1)
        self.assertEqual(bridge.snapshot()['nativeCamera']['inputXY'], [800., 600.])

    def test_mouse_burst_retains_latest_point_and_flushes_it_before_world_advance(self):
        from test_native_camera_driver import NativeCameraDriver
        bridge, _ = NativeCameraDriver().opened()
        messages = self.run_host(r'''
for(let i=0;i<1000;i++){move(100+i%640,200+Math.floor(i/640));}
assert.equal(messages.length,1,'DOM burst has one posted input and one latest pending point');
vm.runInContext('clock.step(50)',scope);
assert.deepEqual(messages.map(m=>m.op),['camera_input','camera_input','advance']);
assert.deepEqual(messages[1].payload.positionClient,[574,1]);
assert.equal(messages[1].payload.sequence,1000);
console.log(JSON.stringify(messages));
''', bridge)
        for message in messages:
            response = json.loads(bridge_call(bridge, message['op'], json.dumps(message['payload'])))
            self.assertTrue(response['ok'], response)
        self.assertEqual(bridge.snapshot()['nativeCamera']['inputXY'], [896.875, 1.5625])
        self.assertEqual(bridge.snapshot()['nativeCamera']['sampledInputSequence'], 1000)

    def test_worker_ack_drains_latest_paused_input_and_clears_request_timers(self):
        from test_native_camera_driver import NativeCameraDriver
        bridge, _ = NativeCameraDriver().opened()
        messages = self.run_host(r'''
(async()=>{
 vm.runInContext("state.paused=true;state.phase='paused'",scope);
 move(420,440);move(260,320);
 assert.equal(messages.length,1);assert.equal(timers.size,1);
 scope.handleReplyNow({data:{type:'reply',id:messages[0].id,ok:true,result:{accepted:true}}});
 await new Promise(setImmediate);
 assert.equal(messages.length,2);assert.equal(timers.size,1);
 assert.deepEqual(messages[1].payload.positionClient,[256,192]);
 scope.handleReplyNow({data:{type:'reply',id:messages[1].id,ok:true,result:{accepted:true}}});
 await new Promise(setImmediate);assert.equal(timers.size,0);
 assert.equal(messages.length,2,'settled paused input does not advance the simulation');
 console.log(JSON.stringify(messages));
})().catch(error=>{console.error(error);process.exitCode=1;});
''', bridge)
        for message in messages:
            receipt = json.loads(bridge_call(bridge, message['op'], json.dumps(message['payload'])))
            self.assertTrue(receipt['ok'], receipt)
        self.assertEqual(bridge.snapshot()['tick'], 0)
        self.assertEqual(bridge.snapshot()['cameraClientInput']['positionClient'], [256, 192])

    def test_reset_flushes_latest_pending_mouse_point_into_persistent_interface(self):
        from test_native_camera_driver import NativeCameraDriver
        bridge, payload = NativeCameraDriver().opened()
        level, world, units, opts = payload
        reset = dict(levelId='level_01', seed=2026, level=level, world=world, units=units, opts=opts)
        messages = self.run_host(r'''
move(420,440);move(260,320);
vm.runInContext('call("reset",JSON.parse('+JSON.stringify(JSON.stringify(input.reset))+'))',scope);
assert.deepEqual(messages.map(m=>m.op),['camera_input','camera_input','reset']);
assert.deepEqual(messages[1].payload.positionClient,[256,192]);
console.log(JSON.stringify(messages));
''', bridge, reset=reset)
        for message in messages:
            receipt = json.loads(bridge_call(bridge, message['op'], json.dumps(message['payload'])))
            self.assertTrue(receipt['ok'], receipt)
        self.assertEqual(bridge.snapshot()['nativeCamera']['inputXY'], [0., 0.])
        self.assertEqual(bridge.snapshot()['cameraClientInput']['positionClient'], [256, 192])
        bridge.advance(1)
        self.assertEqual(bridge.snapshot()['nativeCamera']['inputXY'], [400., 300.])


if __name__ == '__main__':
    unittest.main()
