"""Terrain source closure at the agreed parser, fingerprint and export seams.

Small real V3D/VTX files only; no baking, browser, vendor download or original
asset changes. Export's expensive stages are fail-if-reached sentinels, not
fake renderers claiming a valid output package.
"""
import os
from pathlib import Path
import hashlib
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bugbits import web_build, worlddb
from bugbits.assets import v3d, vtx
from bugbits.render import bake


def world_bytes():
    """Independent 128B material tails: two names, a repeat, an untextured mesh."""
    meshes = (("ground", ("mat_a", "mat_b")),
              ("repeat", ("mat_b",)), ("plain", (None,)))
    blob = bytearray(struct.pack("<I", len(meshes)))
    matrix = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
    for name, names in meshes:
        blob += struct.pack("<I", len(name)) + name.encode("ascii")
        blob += struct.pack("<16fiII", *matrix, -1, 0, 3)
        for point in ((0, 0, 0), (1, 0, 0), (0, 0, 1)):
            blob += struct.pack("<3f3fI2f", *point, 0, 1, 0, 0xFFFFFFFF, 0, 0)
        blob += struct.pack("<I", len(names))
        for texture in names:
            blob += struct.pack("<I3H", 3, 0, 1, 2)
            tail = ((texture.encode("ascii") if texture else b"") + b"\0")
            blob += tail + b"\0" * (128 - len(tail))
    return bytes(blob)


class TerrainProvenanceTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "tmp").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="terrain-provenance-", dir=ROOT / "tmp")
        self.game = Path(self.temp.name)
        self.data = self.game / "data"
        for directory in ("models/worlds", "textures", "scripts", "worlds"):
            (self.data / directory).mkdir(parents=True)
        self.model = self.data / "models/worlds/world_fixture.v3d"
        self.model.write_bytes(world_bytes())
        (self.data / 'worlds/world_fixture.vsc').write_text(
            'SpawnEntity World STATIC\n> World\n'
            'sp Model worlds/world_fixture\nsp Position 7 13 -2\n'
            'sp Direction 1 0 0\n<\n')
        for name in ("mat_a", "mat_b"):
            (self.data / f"textures/{name}.vtx").write_bytes(
                struct.pack("<4I", 2, 2, 2, 2) + bytes((10, 20, 30, 255)) * 4)
        (self.data / "scripts/lang4.vln").write_bytes(b"")
        (self.data / "scripts/lang4_chars.vsc").write_text("")
        self.environment = patch.dict(os.environ, {"BUGBITS_DATA": str(self.game)})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.addCleanup(self.temp.cleanup)

    def test_export_rejects_missing_second_material_before_expensive_work(self):
        (self.data / "textures/mat_b.vtx").unlink()
        world = worlddb.WorldData({}, [], [], "world_fixture", [], [], 0)
        with patch.object(web_build, "survey", return_value=([], {"world_fixture": world}, ["ant"])), \
             patch.object(web_build.unitdb, "load_unit", return_value=object()), \
             patch.object(web_build, "render_unit_clips", side_effect=AssertionError("expensive unit stage reached")) as units, \
             patch.object(bake, "bake_terrain", side_effect=AssertionError("expensive terrain stage reached")) as terrain, \
             patch.object(web_build, "_vendor_pyodide", side_effect=AssertionError("vendor stage reached")) as vendor:
            with self.assertRaisesRegex(FileNotFoundError, r"world_fixture.*ground.*group.?1.*mat_b\.vtx"):
                web_build.export(str(self.game / "output"), "slice", ["fixture"], str(self.game))
            units.assert_not_called()
            terrain.assert_not_called()
            vendor.assert_not_called()

    def test_all_materials_are_hashed_and_effective_second_texel_changes_build_id(self):
        paths = bake.terrain_source_paths("world_fixture")
        expected = {"models/worlds/world_fixture.v3d", "worlds/world_fixture.vsc",
                    "textures/mat_a.vtx", "textures/mat_b.vtx"}
        self.assertEqual({Path(p).relative_to(self.data).as_posix() for p in paths}, expected)
        self.assertEqual(len(paths), 4)  # One owner VSC; duplicate/None VTX unchanged.
        original_hashes, original_id = web_build.input_fingerprint(paths, "slice")
        original_hashes = dict(original_hashes)
        self.assertEqual(set(original_hashes), expected)
        texture = self.data / "textures/mat_b.vtx"
        original = texture.read_bytes()
        self.assertEqual(original_hashes["textures/mat_b.vtx"], hashlib.sha256(original).hexdigest())
        self.assertEqual(vtx.parse_vtx(str(texture))[4].getpixel((0, 0)), (30, 20, 10, 255))
        changed = bytearray(original)
        changed[16] = 11  # First valid BGRA pixel's B channel, not alpha/footer/padding.
        texture.write_bytes(changed)
        self.assertEqual(vtx.parse_vtx(str(texture))[4].getpixel((0, 0)), (30, 20, 11, 255))
        changed_hashes, changed_id = web_build.input_fingerprint(
            bake.terrain_source_paths("world_fixture"), "slice")
        changed_hashes = dict(changed_hashes)
        self.assertNotEqual(changed_hashes["textures/mat_b.vtx"], original_hashes["textures/mat_b.vtx"])
        self.assertEqual(changed_hashes["textures/mat_a.vtx"], original_hashes["textures/mat_a.vtx"])
        self.assertEqual(changed_hashes["models/worlds/world_fixture.v3d"], original_hashes["models/worlds/world_fixture.v3d"])
        self.assertNotEqual(changed_id, original_id)
        texture.write_bytes(original)
        restored_hashes, restored_id = web_build.input_fingerprint(paths, "slice")
        self.assertEqual(dict(restored_hashes), original_hashes)
        self.assertEqual(restored_id, original_id)

    def test_owner_position_changes_terrain_source_identity(self):
        paths = bake.terrain_source_paths('world_fixture')
        before, before_id = web_build.input_fingerprint(paths, 'slice')
        owner = self.data / 'worlds/world_fixture.vsc'
        owner.write_text(owner.read_text().replace('sp Position 7 13 -2',
                                                  'sp Position 17 13 -2'))
        after, after_id = web_build.input_fingerprint(paths, 'slice')
        before, after = dict(before), dict(after)
        self.assertNotEqual(before['worlds/world_fixture.vsc'],
                            after['worlds/world_fixture.vsc'])
        self.assertNotEqual(before_id, after_id)
        for name in ('models/worlds/world_fixture.v3d', 'textures/mat_a.vtx',
                     'textures/mat_b.vtx'):
            self.assertEqual(before[name], after[name])

    def test_model_reference_tracks_actual_model_and_material_sources(self):
        other=self.data/'models/worlds/world_other.v3d'
        other.write_bytes(self.model.read_bytes().replace(b'mat_a\0',b'mat_c\0'))
        material=self.data/'textures/mat_c.vtx'
        material.write_bytes((self.data/'textures/mat_a.vtx').read_bytes())
        owner=self.data/'worlds/world_fixture.vsc'
        owner.write_text(owner.read_text().replace('worlds/world_fixture','worlds/world_other'))
        paths=bake.terrain_source_paths('world_fixture')
        self.assertIn(str(other),paths)
        self.assertIn(str(material),paths)
        self.assertNotIn(str(self.model),paths)
        before,before_id=web_build.input_fingerprint(paths,'slice')
        changed=bytearray(material.read_bytes()); changed[16]=91
        material.write_bytes(changed)
        after,after_id=web_build.input_fingerprint(paths,'slice')
        self.assertNotEqual(dict(before)['textures/mat_c.vtx'],dict(after)['textures/mat_c.vtx'])
        self.assertNotEqual(before_id,after_id)

    def test_group_fallback_and_empty_named_group_preserve_render_consumption(self):
        indices = (0, 1, 2)
        legacy = v3d.WorldMesh("legacy", "", (), (), 2, 3, indices, "mat_a")
        self.assertEqual(bake.terrain_material_groups(legacy), [(indices, "mat_a")])
        legacy.group_indices = (indices,)  # Incomplete legacy groups still fall back.
        legacy.group_tex_names = ("unused",)
        self.assertEqual(bake.terrain_material_groups(legacy), [(indices, "mat_a")])
        empty = v3d.WorldMesh("empty", "", (), (), 1, 0, (), None,
                              ((),), ("mat_b",))
        self.assertEqual(bake.terrain_material_groups(empty), [((), "mat_b")])

    def test_existing_invalid_texture_is_not_silently_filtered_from_sources(self):
        texture = self.data / "textures/mat_b.vtx"
        texture.write_bytes(b"bad")
        paths = bake.terrain_source_paths("world_fixture")
        self.assertIn(str(texture), paths)
        hashes, _ = web_build.input_fingerprint(paths, "slice")
        self.assertEqual(dict(hashes)["textures/mat_b.vtx"], hashlib.sha256(b"bad").hexdigest())
        with self.assertRaises(vtx.VtxError):
            vtx.parse_vtx(str(texture))

    def test_actual_nine_world_closure_contains_every_material(self):
        real_game = ROOT / "analyze/extracted/ccdzz"
        expected_counts = (8, 12, 12, 7, 7, 8, 10, 13, 11)
        expected_world02 = {
            "clod_a", "dandelion_a", "grass_a", "grass_b", "grass_c", "grass_seed_a",
            "nefelejcs_a", "pebbles_a", "shamrock_a", "shamrock_b",
            "world_02_ground_a", "world_02_ground_b",
        }
        all_textures = set()
        with patch.dict(os.environ, {"BUGBITS_DATA": str(real_game)}):
            for number, count in enumerate(expected_counts, 1):
                world = f"world_{number:02d}"
                paths = bake.terrain_source_paths(world)
                textures = {Path(p).stem for p in paths if p.endswith(".vtx")}
                with self.subTest(world=world):
                    self.assertEqual(len(textures), count)
                    self.assertEqual(len(paths), count + 2)
                    self.assertIn(str(real_game / f"data/models/worlds/{world}.v3d"), paths)
                    if number == 2:
                        self.assertEqual(textures, expected_world02)
                all_textures.update(textures)
        self.assertEqual(len(all_textures), 46)


if __name__ == "__main__":
    unittest.main()
