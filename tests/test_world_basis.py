"""Conditional loaded Model basis at the public coordinate seam."""
import sys
import math
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from bugbits.assets import world_basis as basis
from bugbits.assets.v3d import WorldMesh


class LoadedWorldBasis(unittest.TestCase):
    def domain(self):
        return dict(direction=(1, 0, 0), scale=1, node_matrix=basis.IDENTITY,
                    node_parent=-1, skin_matrix=basis.IDENTITY, parent_matrix=basis.IDENTITY)

    def test_loaded_point_matches_independent_asymmetric_literal(self):
        # p S(-quarterturn)->(11,5,-23), W->(5,-11,-23),
        # T(7,13,-2)->(12,2,-25), Q->(-2,25,12).
        point = basis.loaded_model_point((11, 23, 5), (7, 13, -2), **self.domain())
        for actual, expected in zip(point, (-2, 25, 12)):
            self.assertAlmostEqual(actual, expected, delta=3e-6)

    def test_original_position_roundtrip_uses_explicit_canonical_axes(self):
        self.assertEqual(basis.to_yup((11, 23, 5)), (-23, -5, 11))
        self.assertEqual(basis.from_yup((-23, -5, 11)), (11, 23, 5))
        self.assertEqual(basis.from_yup(basis.to_yup((-7, 3, -2))), (-7, 3, -2))

    def test_unsupported_domain_is_rejected(self):
        altered = list(basis.IDENTITY)
        altered[12] = 1
        for key, value in [('direction', (0, 1, 0)), ('scale', 2),
                           ('node_matrix', altered), ('node_parent', 0),
                           ('skin_matrix', altered), ('parent_matrix', altered)]:
            with self.subTest(key=key):
                domain = self.domain()
                domain[key] = value
                with self.assertRaises(ValueError):
                    basis.loaded_model_point((11, 23, 5), (7, 13, -2), **domain)

    def test_nonfinite_and_wrong_dimensions_are_rejected_at_public_seam(self):
        for value in [(1, 2), (1, 2, 3, 4), (1, float('nan'), 3),
                      (1, float('inf'), 3), (1, -float('inf'), 3), None]:
            with self.subTest(value=value):
                for convert in (basis.to_yup, basis.from_yup):
                    with self.assertRaises(ValueError):
                        convert(value)
                with self.assertRaises(ValueError):
                    basis.loaded_model_point(value, (7, 13, -2), **self.domain())
                with self.assertRaises(ValueError):
                    basis.loaded_model_point((11, 23, 5), value, **self.domain())
        for key, value in [('direction', None), ('scale', float('nan')),
                           ('node_matrix', None), ('skin_matrix', (1,)),
                           ('parent_matrix', [float('inf')] * 16), ('node_parent', True)]:
            domain = self.domain()
            domain[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                basis.loaded_model_point((1, 2, 3), (0, 0, 0), **domain)

    def test_vector_has_no_translation_and_retains_original_float32_angle(self):
        vector = basis.loaded_model_vector((0, 1, 0), **self.domain())
        self.assertAlmostEqual(vector[0], 0, delta=1e-15)
        self.assertAlmostEqual(vector[1], 1, delta=1e-14)
        self.assertAlmostEqual(vector[2], -4.371139000186241e-8, delta=1e-15)
        self.assertNotEqual(vector, (0, 1, 0))
        with self.assertRaises(TypeError):
            basis.loaded_model_point((1, 2, 3), (0, 0, 0))
        with self.assertRaises(TypeError):
            basis.loaded_model_vector((1, 2, 3))

    def test_world_mesh_copy_transforms_positions_and_normals_preserving_assets(self):
        verts = [((11, 23, 5), (0, 1, 0), (.25, .75)),
                 ((0, 0, 0), (1, 0, 0), (0, 0)),
                 ((1, 0, 0), (0, 0, 1), (1, 0))]
        mesh = WorldMesh('ground', 0xFFFFFFFF, list(basis.IDENTITY), verts,
                         2, 1, [0, 1, 2], 'world/ground', [[0, 1, 2]], ['world/rock'])
        out = basis.loaded_world_meshes([mesh], (7, 13, -2), direction=(1, 0, 0),
                        scale=1, skin_matrix=basis.IDENTITY, parent_matrix=basis.IDENTITY)
        self.assertEqual(len(out), 1)
        copied = out[0]
        self.assertIsNot(copied, mesh)
        for actual, expected in zip(copied.verts[0][0], (-2, 25, 12)):
            self.assertAlmostEqual(actual, expected, delta=3e-6)
        self.assertAlmostEqual(copied.verts[0][1][2], -4.371139000186241e-8, delta=1e-15)
        self.assertEqual(copied.verts[1][0], (-13, 2, 7))
        self.assertEqual(copied.verts[1][1], (1, 0, 0))
        self.assertEqual(mesh.verts, verts)
        self.assertEqual([v[2] for v in copied.verts], [v[2] for v in verts])
        for field in ('name', 'parent', 'matrix', 'k', 'ic', 'indices',
                      'tex_name', 'group_indices', 'group_tex_names'):
            self.assertEqual(getattr(copied, field), getattr(mesh, field))

    def test_literal_distinguishes_missing_s_order_translation_and_double_basis(self):
        got = basis.loaded_model_point((11, 23, 5), (7, 13, -2), **self.domain())
        # Independent hand-calculated wrong chains in the ideal quarterturn limit.
        for wrong in [(-2, -3, 30), (-18, -9, 30), (11, 23, 5), (-25, -12, -2)]:
            self.assertGreater(sum((a - b) ** 2 for a, b in zip(got, wrong)), 1)

    def test_canonical_basis_is_right_handed_and_preserves_distance(self):
        self.assertEqual(basis.to_yup((1, 0, 0)), (0, 0, 1))
        self.assertEqual(basis.to_yup((0, 1, 0)), (-1, 0, 0))
        self.assertEqual(basis.to_yup((0, 0, 1)), (0, -1, 0))
        # The first two mapped basis vectors cross to the third: +Z x -X = -Y.
        a, b = (11, 23, 5), (-7, 3, -2)
        self.assertAlmostEqual(math.dist(a, b), math.dist(basis.to_yup(a), basis.to_yup(b)))
        transformed = [basis.loaded_model_point(p, (7, 13, -2), **self.domain()) for p in (a, b)]
        self.assertAlmostEqual(math.dist(a, b), math.dist(*transformed), delta=1e-12)
        self.assertEqual(basis.S_ANGLE, -1.5707963705062866)
        self.assertEqual(basis.LEGACY_BASIS_VERSION, 'legacy-grid-v1')
        self.assertEqual(basis.LOADED_BASIS_VERSION, 'loaded-yup-v1')


if __name__ == '__main__':
    unittest.main()
