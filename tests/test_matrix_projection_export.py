"""Packaging seams for the shared matrix module and explicit geometry variants."""
import importlib.util
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from bugbits import web_build
from bugbits import web_data, worlddb
from PIL import Image
from bugbits.render.camera import MatrixWorldCamera


class MatrixProjectionExportTests(unittest.TestCase):
    def test_public_package_validator_binds_the_terrain_actually_loaded_by_host(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'tmp') as directory:
            root = Path(directory)
            (root / 'worlds').mkdir()
            world = worlddb.WorldData({}, [], [], 'synthetic', [], [], 0,
                terrain=(-10,10,-1,1,-10,10), basis_version='loaded-yup-v1',
                basis_assumptions=('skin-matrix-identity','upstream-parent-identity'))
            (root / 'worlds/world_02.json').write_text(json.dumps(web_data.world_to_dict(world)))
            for name, value in [('units.json',{}),('texts.json',{}),
                                ('atlas.json',{'clips':{},'sprites':{},'pages':[]})]:
                (root / name).write_text(json.dumps(value))
            Image.new('RGB',(128,64),(200,0,0)).save(root / 'actually_loaded.png')
            Image.new('RGB',(128,64),(0,200,0)).save(root / 'bound_other.png')
            cam = MatrixWorldCamera.from_original(((0,1,0),(0,0,-1),(-1,0,0)),
                (11,23,-5),size_px=64,aspect=2,fov_y=math.pi/2,near=1,far=100)
            record = web_build.matrix_projection_record(cam,
                world_basis_version='loaded-yup-v1',terrain_file='bound_other.png',
                terrain_sha256=web_build.sha256_file(root / 'bound_other.png'))
            files = [{'path':p.relative_to(root).as_posix(),'size':p.stat().st_size,
                      'sha256':web_build.sha256_file(p)} for p in sorted(root.rglob('*')) if p.is_file()]
            manifest = {'schemaVersion':web_data.SCHEMA_VERSION,'buildId':'synthetic-not-formal',
                'artifactDigest':hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest(),
                'profile':'slice','config':web_build.CONFIG,'files':files,'levels':[],
                'capabilities':{},'fallbacks':[],'projection':{'world_02':record['projection']},
                'projectionBindings':{'world_02':record},'terrainFiles':{'world_02':'bound_other.png'},
                'spriteStats':{},'atlasPages':[],'icons':{}}
            (root / 'manifest.json').write_text(json.dumps(manifest))
            self.assertEqual(web_build.validate(str(root)), [])
            manifest['terrainFiles']['world_02'] = 'actually_loaded.png'
            (root / 'manifest.json').write_text(json.dumps(manifest))
            self.assertTrue(any('host terrain' in e for e in web_build.validate(str(root))),
                            'valid binding to another listed image must not validate the host view')
            # A valid legacy image projection cannot occupy the reserved dynamic
            # camera key, even when it has no mesh/native metadata at all.
            manifest['terrainFiles']['world_02'] = 'bound_other.png'
            manifest['cameraPresets'] = {'world_02': {'native_camera': record}}
            (root / 'manifest.json').write_text(json.dumps(manifest))
            errors = web_build.validate(str(root))
            self.assertTrue(any('world_02/native_camera: native binding' in e for e in errors),
                            'native_camera key must validate before presentation dispatch')

    def test_matrix_geometry_variant_keeps_complete_basis_and_binds_terrain(self):
        cam = MatrixWorldCamera.from_original(((0,1,0),(0,0,-1),(-1,0,0)),
                (11,23,-5), size_px=100, aspect=2, fov_y=math.pi/2, near=1, far=100)
        record = web_build.matrix_projection_record(cam,
                world_basis_version='loaded-yup-v1', terrain_file='terrain_world_02_matrix.png',
                terrain_sha256='a'*64)
        self.assertEqual(record['projection']['basis9'], [-1,0,0,0,1,0,0,0,-1])
        self.assertEqual(record['projection']['cameraPosition'], [-23,5,11])
        self.assertEqual(record['presentationScope'], 'geometry-research')
        actual = web_build.validate_matrix_projection_record(record,
                world_basis_version='loaded-yup-v1', terrain_sha256='a'*64).world_to_pixel(-19,3,-9)
        self.assertAlmostEqual(actual[0], 90, places=12)
        self.assertAlmostEqual(actual[1], 55, places=12)
        import copy
        for field, value in [('presentationScope','native-game'),
                             ('worldBasisVersion','legacy-grid-v1'),
                             ('terrainProjectionDigest','b'*64),
                             ('camera',{'distance':180})]:
            bad = copy.deepcopy(record)
            bad[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                web_build.validate_matrix_projection_record(bad,
                    world_basis_version='loaded-yup-v1', terrain_sha256='a'*64)
        with self.assertRaises(ValueError):
            web_build.validate_matrix_projection_record(record,
                    world_basis_version='loaded-yup-v1', terrain_sha256='b'*64)
        for field, value in [('basis9',[1]*9),('cameraPosition',[1,2,3,4]),
                             ('size',True),('cot',float('nan')),('near',100),
                             ('kind','euler')]:
            bad = copy.deepcopy(record)
            bad['projection'][field] = value
            bad['camera'] = copy.deepcopy(bad['projection'])
            with self.subTest(field=field), self.assertRaises(ValueError):
                web_build.validate_matrix_projection_record(bad,
                    world_basis_version='loaded-yup-v1', terrain_sha256='a'*64)
        with self.assertRaises(ValueError):
            web_build.matrix_projection_record(object(),
                world_basis_version='loaded-yup-v1', terrain_file='terrain.png', terrain_sha256='a'*64)

    def test_page_delivery_copies_the_required_shared_module_and_rejects_missing(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'tmp') as directory:
            root = Path(directory)
            (root / 'web').mkdir()
            output = root / 'package'
            output.mkdir()
            for name in ('index.html', 'worker.js', 'host.js', 'NotoSansSC-subset.woff2', 'OFL.txt'):
                shutil.copyfile(ROOT / 'web' / name, root / 'web' / name)
            with patch.object(web_build, '__file__', str(root / 'src/bugbits/web_build.py')):
                with self.assertRaises(FileNotFoundError):
                    web_build._copy_pages(str(output))
                raw = b'globalThis.BugBitsCameraProjection = {};\n'
                (root / 'web/camera_projection.js').write_bytes(raw)
                with self.assertRaises(FileNotFoundError):
                    web_build._copy_pages(str(output))
                mesh_raw=(ROOT/'web/mesh_scene.js').read_bytes()
                (root/'web/mesh_scene.js').write_bytes(mesh_raw)
                with self.assertRaises(FileNotFoundError):
                    web_build._copy_pages(str(output))
                material_raw = (ROOT/'web/presentation_material.js').read_bytes()
                (root/'web/presentation_material.js').write_bytes(material_raw)
                with self.assertRaises(FileNotFoundError):
                    web_build._copy_pages(str(output))
                flower_raw = (ROOT/'web/flower_pose.js').read_bytes()
                (root/'web/flower_pose.js').write_bytes(flower_raw)
                pages = web_build._copy_pages(str(output))
                self.assertIn('camera_projection.js', pages)
                self.assertEqual((output / 'camera_projection.js').read_bytes(), raw)
                self.assertIn('mesh_scene.js',pages)
                self.assertEqual((output/'mesh_scene.js').read_bytes(),mesh_raw)
                self.assertIn('presentation_material.js', pages)
                self.assertEqual((output/'presentation_material.js').read_bytes(), material_raw)
                self.assertIn('flower_pose.js', pages)
                self.assertEqual((output/'flower_pose.js').read_bytes(), flower_raw)
            spec = importlib.util.spec_from_file_location('matrix_preview', ROOT / 'tools/web_preview.py')
            preview = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(preview)
            self.assertIn('camera_projection.js', preview.PAGES)
            self.assertIn('presentation_material.js', preview.PAGES)
            self.assertIn('flower_pose.js', preview.PAGES)


if __name__ == '__main__':
    unittest.main()
