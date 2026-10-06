"""Original packed vertex color and script-to-group identity must not be dropped."""
import copy
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from bugbits import unitdb,web_geometry
from bugbits.assets import v3d
from bugbits.render import bake


class UnitDiffuseMaterialTests(unittest.TestCase):
    def node(self,body):
        result=subprocess.run(['node','-e',body],cwd=ROOT,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_argb_rgba_bytes_and_conditional_ant_material_are_distinct(self):
        self.node("""
const assert=require('assert'),api=require('./web/mesh_scene.js'),mat=require('./web/presentation_material.js');
assert.deepStrictEqual(Array.from(api.diffuseBytes([0x80123456,0xffabcdef])),[0x12,0x34,0x56,0x80,0xab,0xcd,0xef,0xff]);
for(const bad of [[true],[-1],[0x100000000],[NaN],new Array(1)])assert.throws(()=>api.diffuseBytes(bad));
const unit={unitId:'ant',modelSHA:'7296121d8f72f588d1591acfdafa7e48fad599322a26fc2ac467673a5bf61067',groups:[{unitMaterial:{name:'SYSTEM/lightedbright',groupIndex:0,source:'scripts/bugs/ant.vsc',sourceSHA256:'35fcdadaeff1db148abc9e4495caf6fdbd3e7d8c397ded47be6cb5269b35f4ad',bindingScope:'script-unit-material-v1'}}]};
const state=mat.unitGroup(unit,0);assert(state&&state.color1);
assert.strictEqual(state.ambientScale,1);assert.strictEqual(state.factor,2);assert.strictEqual(state.alphaRef,1/255);assert.strictEqual(state.alphaBlend,false);
assert.deepStrictEqual(state.passes,[{cull:3,dstBlend:6,zWrite:1}]);
assert.strictEqual(state.fogStart,139.92567443847656);assert.strictEqual(state.fogEnd,735.642822265625);
assert.notDeepStrictEqual(state,mat.group('flower_a',0));
for(const bad of [{...unit,unitId:'bee'},{...unit,modelSHA:'0'.repeat(64)},{...unit,groups:[{unitMaterial:{...unit.groups[0].unitMaterial,name:'SYSTEM/other'}}]}])assert.strictEqual(mat.unitGroup(bad,0),null);
assert.strictEqual(mat.unitGroup(unit,1),null);assert.strictEqual(mat.group('ant',0),null);
""")

    def test_js_contract_rejects_partial_diffuse_and_wrong_material_identity(self):
        self.node("""
const assert=require('assert'),api=require('./web/mesh_scene.js');
const I=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1],clips={};
for(const key of ['walk','idle','normal_attack','hurt','special_attack','special_move'])clips[key]={kind:'missing',fallbackClip:null,frames:[]};
const unit={unitId:'ant',modelSource:'models/ant.v3d',modelSHA:'a'.repeat(64),diffuseARGB:[0xffffffff,0xff0000ff,0x80123456],diffuseScope:'raw-bind-diffuse-v1',positions:[0,0,2,1,0,2,0,1,2],normals:[0,0,1,0,0,1,0,0,1],uvs:[0,0,1,0,0,1],groups:[{indices:[0,1,2],texture:null,unitMaterial:{name:'SYSTEM/lightedbright',groupIndex:0,source:'scripts/bugs/ant.vsc',sourceSHA256:'b'.repeat(64),bindingScope:'script-unit-material-v1'}}],anchor:[0,0,0],rootMatrix:I,rootPolicy:'engineering-fixed-S-v1',coordinatePolicy:'raw-to-engine-yup-Q-v1',anchorPolicy:'raw-bind-ground-pivot-v1',frameBasis:'raw-model-v1',rootApplied:false,scaleApplied:false,scaleFactor:1,clips};
const scene={schema:'engine-mesh-v1',posePolicy:'engine-pose-v1',unitMaterialContract:'script-diffuse-unit-v1',units:{ant:unit},worlds:{},textures:{}};
api.validateAssets(scene);
for(const mutate of [s=>s.units.ant.diffuseARGB.pop(),s=>s.units.ant.diffuseARGB[0]=true,s=>s.units.ant.diffuseARGB=new Array(3),s=>s.units.ant.unitId='bee',s=>s.units.ant.groups[0].unitMaterial.groupIndex=1,s=>s.units.ant.groups[0].unitMaterial.source='scripts/bugs/bee.vsc',s=>delete s.units.ant.groups[0].unitMaterial,s=>delete s.unitMaterialContract,s=>{s.units={};s.unitMaterialContract='unsupported';}]){const bad=structuredClone(scene);mutate(bad);assert.throws(()=>api.validateAssets(bad));}
""")
    def test_packed_color_keeps_nonwhite_argb_bytes_and_rejects_truncation(self):
        identity=(1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1)
        data=struct.pack('<2I',1,3)+b'ant'+struct.pack('<16fiiI',*identity,-1,1,2)
        for color in (0x80123456,0xffabcdef):
            data+=struct.pack('<6fI2f',0,0,0,0,0,1,color,0,0)
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as directory:
            path=Path(directory)/'color.v3d';path.write_bytes(data)
            self.assertEqual(v3d.vertex_diffuse(path),(0x80123456,0xffabcdef))
            path.write_bytes(data[:-1])
            with self.assertRaises(ValueError):v3d.vertex_diffuse(path)

    def test_real_ant_whole_pool_and_two_group_bee_declarations_survive_export(self):
        for uid,groups in [('ant',1),('bee',2)]:
            with self.subTest(uid=uid),tempfile.TemporaryDirectory(dir=ROOT/'tmp') as directory:
                result=web_geometry.export_geometry_assets((uid,),(),out_dir=directory,
                    pose_policy='engine-pose-v1',sample_hz=1,min_frames=2,max_frames=2)
                scene=json.loads((Path(directory)/result['file']).read_text());u=scene['units'][uid]
                self.assertEqual(scene['unitMaterialContract'],'script-diffuse-unit-v1')
                model=bake._resolve_model(unitdb.load_unit(uid).model,'.v3d')
                colors=v3d.vertex_diffuse(model)
                self.assertEqual(u['diffuseARGB'],list(colors))
                self.assertEqual(u['diffuseScope'],'raw-bind-diffuse-v1')
                self.assertEqual(scene['inputHashes'][u['modelSource']],u['modelSHA'])
                self.assertEqual(len(u['groups']),groups)
                spec=unitdb.load_unit(uid)
                for i,g in enumerate(u['groups']):
                    binding=g['unitMaterial']
                    self.assertEqual(binding['groupIndex'],i)
                    self.assertEqual(binding['name'],spec.props.get('Material'+str(i),[None])[0])
                    self.assertEqual(binding['source'],'scripts/bugs/'+uid+'.vsc')
                    self.assertEqual(binding['sourceSHA256'],web_geometry._sha(ROOT/'analyze/extracted/ccdzz/data'/binding['source']))
                if uid=='ant':self.assertEqual(colors,(0xffffffff,)*808)
                for change in ('short','boolean','badgroup','missing','missingname'):
                    bad=copy.deepcopy(scene)
                    if change=='short':bad['units'][uid]['diffuseARGB'].pop()
                    elif change=='boolean':bad['units'][uid]['diffuseARGB'][0]=True
                    elif change=='badgroup':bad['units'][uid]['groups'][0]['unitMaterial']['groupIndex']=1
                    elif change=='missing':del bad['units'][uid]['groups'][0]['unitMaterial']
                    else:del bad['units'][uid]['groups'][0]['unitMaterial']['name']
                    with self.assertRaises(ValueError):web_geometry.validate_geometry(bad)
                bad=copy.deepcopy(scene);bad['units']={};bad['unitMaterialContract']='unsupported'
                with self.assertRaises(ValueError):web_geometry.validate_geometry(bad)
                web_geometry.validate_geometry_sources(scene,scene['inputHashes'],require_all_units=False)
                bad=copy.deepcopy(scene);bad['units'][uid]['groups'][0]['unitMaterial']['sourceSHA256']='0'*64
                with self.assertRaises(ValueError):web_geometry.validate_geometry_sources(bad,bad['inputHashes'],require_all_units=False)
