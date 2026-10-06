"""R56 independent VSC/loaded-coordinate/schema contracts, no rendering."""
import copy
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bugbits import web_data, worlddb
from bugbits.assets import data_dir, v3d

LEGACY = "legacy-grid-v1"
LOADED = "loaded-yup-v1"
I = (1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.)
VSC = """SpawnEntity World STATIC
SpawnEntity Start START
SpawnEntity wp WAYPOINT
SpawnEntity flower FLOWER
SpawnEntity light LIGHT
> World
sp Model worlds/sample
sp Position 7 13 -2
sp Direction 1 0 0
sp ScaleFactor 1
<
> Start
sp Position 7 13 -2
sp Direction 2 3 5
sp SideID 0
sp Index 0
ConnectTo wp
<
> wp
sp Position 10 17 -2
sp Direction 1 0 0
sp Water 0
<
> flower
sp Position 3 4 5
sp Direction 0 0 -1
sp FlowerType 2
<
> light
sp Position 11 23 5
sp Direction 1 2 3
<
"""


class LoadedWorldData(unittest.TestCase):
    def setUp(self):
        temp_root = ROOT / "tmp/linux"
        temp_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="r56-world-", dir=temp_root)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "worlds/sample.vsc"
        self.path.parent.mkdir()
        self.path.write_text(VSC)
        self.mesh = v3d.WorldMesh("ground", 0xFFFFFFFF, I,
                                 [((11., 23., 5.), (0., 1., 0.), (0., 0.)),
                                  ((-2., 7., 4.), (0., 1., 0.), (1., 0.)),
                                  ((1., 3., -6.), (0., 1., 0.), (0., 1.))],
                                 1, 3, [0, 1, 2], None)

    def parse(self, basis=LOADED):
        with patch.object(v3d, "parse_world_meshes", return_value=[self.mesh]):
            return worlddb.parse_world(str(self.path), basis=basis)

    def test_entity_positions_directions_once_and_owner_metadata(self):
        w = self.parse()
        self.assertEqual(w.basis_version, LOADED)
        self.assertEqual(w.starts[0].grid_pos, (-13., 2., 7.))
        self.assertEqual(w.starts[0].direction, (-3., -5., 2.))
        self.assertEqual(w.waypoints[0].grid_pos, (-17., 2., 10.))
        self.assertEqual(w.flowers[0].grid_pos, (-4., -5., 3.))
        self.assertEqual(w.flowers[0].direction, (0., 1., 0.))
        self.assertEqual(w.lights[0].grid_pos, (-23., -5., 11.))
        self.assertEqual(w.lights[0].direction, (-2., -3., 1.))
        self.assertEqual(w.static_position, (7., 13., -2.))
        self.assertEqual(w.static_direction, (1., 0., 0.))
        self.assertEqual(w.static_scale, 1.)
        self.assertEqual(w.adjacency, {"Start": {"wp"}, "wp": {"Start"}})
        self.assertEqual(w.edges, 1)

    def test_terrain_bounds_loaded_owner_translation_independent_literals(self):
        # Hand-derived Q(W(S(p))+T), actual source phi float32 near -pi/2.
        # Three ideal points (-2,25,12),(-15,9,11),(-12,5,1).
        bounds = self.parse().terrain
        for actual, expected in zip(bounds, (-15., -2., 5., 25., 1., 12.)):
            self.assertAlmostEqual(actual, expected, delta=2e-6)
        self.assertEqual(self.mesh.verts[0][0], (11., 23., 5.))
        self.assertEqual(self.mesh.matrix, I)

    def test_loaded_json_roundtrip_and_version_conflicts(self):
        w = self.parse()
        d = web_data.world_to_dict(w)
        self.assertEqual(d["worldBasisVersion"], LOADED)
        self.assertEqual(d["staticPosition"], [7., 13., -2.])
        self.assertEqual(web_data.restore_world(json.loads(json.dumps(d))), w)
        for transform in (lambda x: x.pop("worldBasisVersion"),
                          lambda x: x.update(worldBasisVersion="unknown"),
                          lambda x: x.update(worldBasisVersion=LEGACY)):
            bad = copy.deepcopy(d)
            transform(bad)
            with self.assertRaises(ValueError):
                web_data.restore_world(bad)

    def test_legacy_explicit_and_unversioned_historical_json_migration(self):
        w = self.parse(LEGACY)
        self.assertEqual(w.starts[0].grid_pos, (13., -2., 7.))
        self.assertEqual(w.starts[0].direction, (2., 3., 5.))
        d = web_data.world_to_dict(w)
        self.assertEqual(d["worldBasisVersion"], LEGACY)
        self.assertEqual(web_data.restore_world(d), w)
        for key in ("worldBasisVersion", "staticPosition", "staticDirection", "staticScale",
                    "loadedBasisAssumptions"):
            d.pop(key, None)
        migrated = web_data.restore_world(d)
        self.assertEqual(migrated.basis_version, LEGACY)
        self.assertEqual(migrated.starts[0].grid_pos, (13., -2., 7.))

    def test_unsupported_basis_owner_and_node_are_rejected(self):
        with self.assertRaises(ValueError):
            self.parse("future-basis")
        for change in ("sp Direction 0 1 0", "sp ScaleFactor 2"):
            original = "sp Direction 1 0 0" if "Direction" in change else "sp ScaleFactor 1"
            self.path.write_text(VSC.replace(original, change, 1))
            with self.assertRaises(ValueError):
                self.parse()
        self.path.write_text(VSC)
        changed = list(I)
        changed[12] = 7.
        self.mesh.matrix = tuple(changed)
        with self.assertRaises(ValueError):
            self.parse()

    def test_real_world02_literal_graph_and_distance(self):
        path = data_dir("worlds", "world_02.vsc")
        loaded = worlddb.parse_world(path, basis=LOADED)
        legacy = worlddb.parse_world(path, basis=LEGACY)
        s = loaded.start(0, 0)
        for actual, expected in zip(s.grid_pos, (-93.529, -3.739, -344.543)):
            self.assertAlmostEqual(actual, expected, delta=.002)
        self.assertEqual(loaded.adjacency, legacy.adjacency)
        self.assertEqual(loaded.components(), legacy.components())
        self.assertEqual(len(loaded.waypoints), 122)
        self.assertEqual(loaded.edges, 124)
        self.assertAlmostEqual(math.dist(loaded.starts[0].grid_pos, loaded.starts[1].grid_pos),
                               math.dist(legacy.starts[0].grid_pos, legacy.starts[1].grid_pos))

    def test_default_migration_is_named_and_nonidentity_world_never_falls_back(self):
        self.assertEqual(worlddb.parse_world(data_dir("worlds", "world_02.vsc")).basis_version, LOADED)
        self.assertEqual(worlddb.parse_world(data_dir("worlds", "world_03.vsc")).basis_version, LOADED)
        self.assertEqual(worlddb.parse_world(data_dir("worlds", "world_04.vsc")).basis_version, LEGACY)
        with self.assertRaises(ValueError):
            worlddb.parse_world(data_dir("worlds", "world_04.vsc"), basis=LOADED)

    def test_restore_loaded_rejects_invalid_metadata_and_coordinate_packets(self):
        good = web_data.world_to_dict(self.parse())
        cases = [("staticScale", True), ("staticScale", "1"),
                 ("staticPosition", [7, 13, -2, 99]),
                 ("staticPosition", [float("nan"), 13, -2]),
                 ("staticPosition", [7, float("inf"), -2]),
                 ("staticPosition", ["7", 13, -2]),
                 ("staticDirection", [1, 0, 0, 17]),
                 ("staticDirection", [True, False, False]),
                 ("loadedBasisAssumptions", ["skin-matrix-identity", ["upstream-parent-identity"]]),
                 ("loadedBasisAssumptions", "skin-matrix-identity"),
                 ("loadedBasisAssumptions", ["skin-matrix-identity", "upstream-parent-identity", "unknown"]),
                 ("loadedBasisAssumptions", ["skin-matrix-identity", "upstream-parent-identity", "skin-matrix-identity"]),
                 ("terrain", [0, 1, 0, 1, 0, 1, 2]),
                 ("terrain", [0, 1, 0, float("inf"), 0, 1]),
                 ("terrain", [0, True, 0, 1, 0, 1])]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                bad = copy.deepcopy(good)
                bad[key] = value
                with self.assertRaises(ValueError):
                    web_data.restore_world(bad)
        for collection in ("starts", "waypoints", "flowers", "lights"):
            for field, bad_value in (("pos", [0, 1, 2, 3]), ("dir", [1, 0, float("nan")]),
                                     ("pos", [True, 0, 0]), ("dir", ["1", 0, 0])):
                with self.subTest(collection=collection, field=field, value=bad_value):
                    bad = copy.deepcopy(good)
                    bad[collection][0][field] = bad_value
                    with self.assertRaises(ValueError):
                        web_data.restore_world(bad)

    def test_export_loaded_rejects_invalid_metadata_and_coordinates(self):
        good = self.parse()
        for field, value in (("static_scale", True), ("static_scale", "1"),
                             ("static_position", (float("nan"), 13, -2)),
                             ("static_direction", (1, 0, 0, 17)),
                             ("static_direction", (True, False, False)),
                             ("basis_assumptions", ("skin-matrix-identity", True)),
                             ("terrain", (0, 1, 0, 1, 0, 1, 2))):
            with self.subTest(field=field):
                bad = copy.deepcopy(good)
                setattr(bad, field, value)
                with self.assertRaises(ValueError):
                    web_data.world_to_dict(bad)
        for collection in ("starts", "waypoints", "flowers", "lights"):
            bad = copy.deepcopy(good)
            getattr(bad, collection)[0].grid_pos = (0, float("inf"), 0)
            with self.subTest(collection=collection):
                with self.assertRaises(ValueError):
                    web_data.world_to_dict(bad)
