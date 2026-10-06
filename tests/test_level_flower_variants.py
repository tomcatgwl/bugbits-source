"""Public real source flower variants share one world and asset pool."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from bugbits import web_geometry, web_build, level
from bugbits.assets import data_dir


class LevelFlowerVariantTests(unittest.TestCase):
    def test_same_world_normal_and_rescue_preserve_real_transforms(self):
        with tempfile.TemporaryDirectory(dir='tmp') as root:
            result = web_geometry.export_flower_geometry_assets(('world_01',), out_dir=root,
                prop_variants_by_world={'world_01': ('normal', 'rescue')})
            scene = json.loads((Path(root) / result['file']).read_text())
            world = scene['worlds']['world_01']
            self.assertNotIn('propInstances', world)
            self.assertEqual(scene['propVariantContract'], 'level-flower-variants-v1')
            self.assertEqual(set(world['propVariants']), {'normal', 'rescue'})
            a, b = world['propVariants']['normal'], world['propVariants']['rescue']
            self.assertEqual(len(a), 5)
            self.assertEqual([p['name'] for p in a], [p['name'] for p in b])
            self.assertEqual({p['assetId'] for p in a}, {'flower_a'})
            self.assertEqual({p['assetId'] for p in b}, {'flower_a_swap'})
            p = next(p for p in a if p['name'] == 'Flower2')
            self.assertEqual(p['positionYup'], [-83.6097259521, 2.3150925636, -50.7187004089])
            self.assertEqual(p['directionYup'], [-1,0,0])
            for normal, rescue in zip(a, b):
                for field in ('positionYup','directionRaw','ownerMatrix','parentMatrix'):
                    self.assertEqual(normal[field], rescue[field])
                self.assertEqual(normal['scaleFactor'],2.5)
                self.assertEqual(rescue['scaleFactor'],4.0)
            self.assertIn('models/props/flower_a_swap.v3d', result['inputHashes'])
            web_geometry.validate_geometry(scene)
            for mutation in ('contract','legacy','rescue','asset','variant'):
                bad=copy.deepcopy(scene)
                if mutation=='contract':bad['propVariantContract']='unknown'
                if mutation=='legacy':bad['worlds']['world_01']['propInstances']=a
                if mutation=='rescue':bad['worlds']['world_01']['propVariants']['rescue'][0]['rescue']=False
                if mutation=='asset':bad['worlds']['world_01']['propVariants']['rescue'][0]['assetId']='flower_a'
                if mutation=='variant':bad['worlds']['world_01']['propVariants']['other']=a
                with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                    web_geometry.validate_geometry(bad)
            changed=dict(result['inputHashes']);changed['models/props/flower_a_swap.v3d']='0'*64
            with self.assertRaises(ValueError):
                web_geometry.validate_geometry_sources(scene,changed,require_all_units=False)

    def test_invalid_selection_rejected_without_writes(self):
        for options in ({'world_01':('other',)}, {'world_01':('normal','normal')}, {}, {'world_02':('normal',)}):
            with tempfile.TemporaryDirectory(dir='tmp') as root:
                with self.assertRaises(ValueError):
                    web_geometry.export_flower_geometry_assets(('world_01',),out_dir=root,
                        prop_variants_by_world=options)
                self.assertEqual(list(Path(root).iterdir()),[])
        with tempfile.TemporaryDirectory(dir='tmp') as root:
            with self.assertRaises(ValueError):
                web_geometry.export_flower_geometry_assets(('world_01',),out_dir=root,
                    rescue_worlds=(),prop_variants_by_world={'world_01':('normal',)})
            self.assertEqual(list(Path(root).iterdir()),[])

    def test_unverified_type2_rescue_is_rejected_before_expensive_unit_pose(self):
        with tempfile.TemporaryDirectory(dir='tmp') as root:
            # R155: original rescue keeps an existing model, whose identity is
            # unknown; missing flower_b_swap is not an original requirement.
            with patch.object(web_geometry.pose,'skin_at',side_effect=AssertionError('pose started before unsupported prop preflight')):
                with self.assertRaisesRegex(ValueError,'^unverified original type2 rescue model binding$'):
                    web_geometry.export_geometry_assets(('ant',),('world_03',),out_dir=root,
                        pose_policy='engine-pose-v1',prop_variants_by_world={'world_03':('normal','rescue')})
            self.assertEqual(list(Path(root).iterdir()),[])

    def test_builder_selectors_follow_real_level_type_and_reject_cross_variant(self):
        ordinary=level.parse_level(data_dir('scripts','levels','level_01.vsc'))
        rescue=level.parse_level(data_dir('scripts','levels','rescue_01.vsc'))
        self.assertEqual(ordinary.world_name,rescue.world_name)
        variants={'world_01':['normal','rescue']}
        a=web_build.mesh_prop_selector(ordinary.world_name,ordinary.type,variants)
        b=web_build.mesh_prop_selector(rescue.world_name,rescue.type,variants)
        self.assertEqual(a,{'contract':'level-flower-variants-v1','world':'world_01','variant':'normal'})
        self.assertEqual(b['variant'],'rescue')
        scene={'propVariantContract':'level-flower-variants-v1','worlds':{'world_01':{'propVariants':{'normal':[],'rescue':[]}}}}
        manifest={'geometryAssets':{'propVariants':variants},'levels':[
            {'id':'level_01','world':'world_01','type':'gather','deps':{'meshProps':a}},
            {'id':'rescue_01','world':'world_01','type':'rescue','deps':{'meshProps':b}}]}
        web_build.validate_mesh_prop_selectors(manifest,scene)
        for mutation in ('cross','missing','inventory','world'):
            bad=copy.deepcopy(manifest)
            if mutation=='cross':bad['levels'][1]['deps']['meshProps']=a
            if mutation=='missing':del bad['levels'][0]['deps']['meshProps']
            if mutation=='inventory':bad['geometryAssets']['propVariants']['world_01']=['normal']
            if mutation=='world':bad['levels'][0]['deps']['meshProps']['world']='world_02'
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                web_build.validate_mesh_prop_selectors(bad,scene)


if __name__ == '__main__': unittest.main()
