"""Public geometry export: real inputs, UV/groups and complete clip ledger."""
import json
import copy
import tempfile
import unittest
import sys
import struct
import hashlib
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))

from bugbits import web_geometry, web_build
from bugbits.assets import v3d
from bugbits.render import bake


class GeometryExportTests(unittest.TestCase):
    def export(self, units=('ant',), worlds=()):
        root = tempfile.TemporaryDirectory(dir='tmp')
        self.addCleanup(root.cleanup)
        result = web_geometry.export_geometry_assets(units, worlds,
            out_dir=root.name, pose_policy='engine-pose-v1', sample_hz=1,
            min_frames=2, max_frames=2)
        return result, json.loads((Path(root.name)/result['file']).read_text())

    def test_real_ant_uv_and_clip_ledger(self):
        result, scene = self.export()
        unit = scene['units']['ant']
        source, groups, _, _ = v3d.parse_v3d_groups(bake._resolve_model('bugs/ant', '.v3d'))
        self.assertEqual(unit['uvs'], [x for v in source for x in v[2]])
        self.assertEqual(unit['groups'][0]['indices'], list(groups[0][0]))
        self.assertEqual(set(unit['clips']), set(web_geometry.CLIP_KEYS))
        self.assertEqual(unit['clips']['walk']['frames'][0]['positions']['count'], 3*len(source))
        self.assertEqual(unit['scaleFactor'], 1.5)
        self.assertFalse(unit['scaleApplied'])
        self.assertFalse(unit['rootApplied'])
        self.assertEqual(unit['frameBasis'], 'raw-model-v1')
        self.assertGreater(len(result['source_paths']), 3)

    def test_two_material_bee_preserves_both_original_groups(self):
        _, scene = self.export(('bee',))
        unit = scene['units']['bee']
        self.assertEqual(len(unit['groups']), 2)
        self.assertNotEqual(unit['groups'][0]['texture'], unit['groups'][1]['texture'])
        for g in unit['groups']:
            self.assertIn(g['texture'], scene['textures'])

    def test_named_missing_texture_and_animation_fail(self):
        with patch.object(web_geometry, '_texture_path', return_value='/missing.vtx'):
            with self.assertRaises(FileNotFoundError): self.export()
        actual = bake._resolve_model
        with patch.object(bake, '_resolve_model', side_effect=lambda ref, ext: None if ext=='.van' else actual(ref, ext)):
            with self.assertRaises(FileNotFoundError): self.export()

    def test_unknown_policy_rejected_before_write(self):
        with tempfile.TemporaryDirectory(dir='tmp') as root:
            with self.assertRaises(ValueError):
                web_geometry.export_geometry_assets(('ant',), (), out_dir=root,
                                                     pose_policy='original-guessed')
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_all_real_ids_have_six_slots_without_sampling(self):
        ledger = web_geometry.asset_ledger()
        self.assertEqual(len(ledger), 24)
        self.assertTrue(all(set(v['clips'])==set(web_geometry.CLIP_KEYS) for v in ledger.values()))
        self.assertGreater(len({g for v in ledger.values() for g in v['textures']}), 20)

    def test_packet_rejects_bad_mapping_and_missing_texture(self):
        _, scene = self.export()
        broken=copy.deepcopy(scene);broken['units']['ant']['uvs'].pop()
        with self.assertRaises(ValueError): web_geometry.validate_geometry(broken)
        broken=copy.deepcopy(scene);broken['textures'].clear()
        with self.assertRaises(ValueError): web_geometry.validate_geometry(broken)
        for value in (float('nan'),float('inf'),True):
            broken=copy.deepcopy(scene);broken['units']['ant']['positions'][0]=value
            with self.subTest(value=value),self.assertRaises(ValueError): web_geometry.validate_geometry(broken)
        broken=copy.deepcopy(scene);broken['units']['ant']['clips']['walk']['sampleTimes']=[0,0]
        with self.assertRaises(ValueError): web_geometry.validate_geometry(broken)

    def test_static_and_missing_fallback_are_explicit_after_full_table(self):
        from bugbits import unitdb
        spec=unitdb.load_unit('ant');spec.anims.pop('walk');spec.anims.pop('special_move',None)
        original=v3d.parse_v3d_groups
        def no_skin(path):
            verts,groups,skin,recs=original(path)
            return verts,groups,[],recs
        with patch.object(unitdb,'load_unit',return_value=spec),patch.object(v3d,'parse_v3d_groups',side_effect=no_skin):
            _,scene=self.export()
        unit=scene['units']['ant']
        self.assertEqual(unit['clips']['idle']['kind'],'static')
        self.assertEqual(unit['clips']['walk']['kind'],'missing')
        self.assertEqual(unit['clips']['walk']['fallbackClip'],'idle')
        self.assertEqual(unit['clips']['special_move']['fallbackClip'],'idle')

    def test_reordered_real_skin_is_rejected(self):
        original=v3d.parse_v3d_groups
        def reordered(path):
            verts,groups,skin,recs=original(path)
            skin=list(skin);skin[0],skin[1]=skin[1],skin[0]
            return verts,groups,skin,recs
        with patch.object(v3d,'parse_v3d_groups',side_effect=reordered):
            with self.assertRaises(ValueError):self.export()

    def test_real_loaded_world_geometry_matches_producer_basis(self):
        _,scene=self.export((),('world_02',))
        source=bake.terrain_meshes('world_02')
        actual=scene['worlds']['world_02']
        self.assertEqual(actual['basisVersion'],'loaded-yup-v1')
        self.assertEqual(actual['meshes'][0]['positions'],[x for v in source[0].verts for x in v[0]])
        self.assertEqual(len(actual['meshes']),len(source))

    def test_legacy_world_is_not_mislabeled_as_engine_loaded_geometry(self):
        with self.assertRaises(ValueError):self.export((),('world_04',))

    def test_mesh_projection_preserves_engineering_camera_and_binds_scene(self):
        from bugbits.render import camera
        cam=camera.StaticObliqueCamera((-10,10,-10,10),size_px=640,
            pitch_deg=40,yaw_deg=25,aspect=1.6,target=(3,4,5),distance=400)
        record=web_build.mesh_projection_record(cam,world='world_02',
            world_basis_version='loaded-yup-v1',geometry_file='assets/geometry/scene.json',geometry_sha256='a'*64)
        actual=web_build.matrix_projection_camera(record['projection'])
        for point in ((11,23,5),(-7,3,21)):
            self.assertEqual(len(actual.world_to_pixel_depth(*point)),3)
            for a,b in zip(actual.world_to_pixel(*point),cam.world_to_pixel(*point)):self.assertAlmostEqual(a,b)
        self.assertEqual(record['presentationScope'],'engine-mesh-v1')
        self.assertNotIn('terrainFile',record)
        web_build.validate_mesh_projection_record(record,world='world_02',
            world_basis_version='loaded-yup-v1',geometry_sha256='a'*64)
        with self.assertRaises(ValueError):web_build.validate_mesh_projection_record(record,
            world='world_03',world_basis_version='loaded-yup-v1',geometry_sha256='a'*64)

    def test_geometry_source_hash_values_and_real_ids_are_bound(self):
        _,scene=self.export()
        hashes=scene['inputHashes']
        web_geometry.validate_geometry_sources(scene,hashes,require_all_units=False)
        changed=dict(hashes);key=next(iter(changed));changed[key]='0'*64
        with self.assertRaises(ValueError):web_geometry.validate_geometry_sources(scene,changed,require_all_units=False)
        broken=copy.deepcopy(scene);broken['units']['invented']=broken['units'].pop('ant')
        with self.assertRaises(ValueError):web_geometry.validate_geometry_sources(broken,hashes,require_all_units=False)

    def test_binary_frame_bytes_match_gpu_f32_and_reject_mixed_or_bad_ranges(self):
        _,scene=self.export()
        u=scene['units']['ant'];record=u['frameBuffer']
        self.assertEqual(record['format'],'f32le-pose-v1')
        frame=u['clips']['walk']['frames'][0]
        self.assertEqual(frame['positions']['offset'],0)
        self.assertEqual(frame['normals']['offset'],frame['positions']['count']*4)
        raw=struct.pack('<6f',1.25,-2.5,3.75,0,1,0)
        unit={'positions':[0,0,0],'frameBuffer':{'format':'f32le-pose-v1','byteLength':24,'sha256':hashlib.sha256(raw).hexdigest()},
              'clips':{'walk':{'frames':[{'positions':{'offset':0,'count':3},'normals':{'offset':12,'count':3}}]}}}
        actual=web_geometry.decode_frame(unit,unit['clips']['walk']['frames'][0],raw)
        self.assertEqual(actual,{'positions':[1.25,-2.5,3.75],'normals':[0,1,0]})
        for field,value in (('offset',2),('count',4)):
            bad=copy.deepcopy(unit);bad['clips']['walk']['frames'][0]['positions'][field]=value
            with self.assertRaises(ValueError):web_geometry.decode_frame(bad,bad['clips']['walk']['frames'][0],raw)
        with self.assertRaises(ValueError):web_geometry.decode_frame(unit,unit['clips']['walk']['frames'][0],raw[:-1])
        with self.assertRaises(ValueError):web_geometry.decode_frame(unit,unit['clips']['walk']['frames'][0],b'X'+raw[1:])
        for field,value in (('offset',-24),('offset',1),('count',1)):
            selected=copy.deepcopy(unit['clips']['walk']['frames'][0]);selected['positions'][field]=value
            with self.subTest(selected=selected),self.assertRaises(ValueError):web_geometry.decode_frame(unit,selected,raw)
        selected=copy.deepcopy(unit['clips']['walk']['frames'][0]);selected['positions'],selected['normals']=selected['normals'],selected['positions']
        with self.assertRaises(ValueError):web_geometry.decode_frame(unit,selected,raw)
        selected=copy.deepcopy(unit['clips']['walk']['frames'][0]);selected['extra']='unknown'
        with self.assertRaises(ValueError):web_geometry.decode_frame(unit,selected,raw)
        broken=copy.deepcopy(scene);broken['units']['ant']['clips']['walk']['frames'][0]['positions']=[0]*frame['positions']['count']
        with self.assertRaises(ValueError):web_geometry.validate_geometry(broken)

if __name__ == '__main__': unittest.main()
