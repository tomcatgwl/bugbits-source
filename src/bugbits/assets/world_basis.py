"""Explicit conditional loaded-world basis; original runtime remains unknown."""
import struct
import math

IDENTITY = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
LEGACY_BASIS_VERSION = 'legacy-grid-v1'
LOADED_BASIS_VERSION = 'loaded-yup-v1'
S_ANGLE = struct.unpack('<f', bytes.fromhex('db0fc9bf'))[0]


def _finite_tuple(value, count, name):
    try:
        values = tuple(value)
    except TypeError as exc:
        raise ValueError(f'{name} must contain {count} finite numbers') from exc
    if (len(values) != count or any(isinstance(x, bool)
            or not isinstance(x, (int, float)) or not math.isfinite(x) for x in values)):
        raise ValueError(f'{name} must contain {count} finite numbers')
    return values


def _supported_domain(direction, scale, node_matrix, node_parent,
                      skin_matrix, parent_matrix):
    direction = _finite_tuple(direction, 3, 'direction')
    node_matrix = _finite_tuple(node_matrix, 16, 'node_matrix')
    skin_matrix = _finite_tuple(skin_matrix, 16, 'skin_matrix')
    parent_matrix = _finite_tuple(parent_matrix, 16, 'parent_matrix')
    if (direction != (1, 0, 0) or isinstance(scale, bool)
            or not isinstance(scale, (int, float)) or not math.isfinite(scale) or scale != 1
            or node_matrix != IDENTITY or isinstance(node_parent, bool)
            or not isinstance(node_parent, int) or node_parent not in (-1, 0xFFFFFFFF)
            or skin_matrix != IDENTITY or parent_matrix != IDENTITY):
        raise ValueError('loaded basis supports only explicit default direction, '
                         'scale 1, root node and identity node/skin/parent matrices')


def to_yup(point):
    """Original entity components A,B,C to canonical Y-up (-B,-C,A)."""
    a, b, c = _finite_tuple(point, 3, 'point')
    return (-b, -c, a)


def from_yup(point):
    """Inverse of to_yup; no loaded-model transform is implied."""
    x, y, z = _finite_tuple(point, 3, 'point')
    return (z, -x, -y)


def loaded_model_point(point, position, *, direction, scale, node_matrix,
                       node_parent, skin_matrix, parent_matrix):
    """Return Q(W(S(point)) + position) under the explicit supported domain."""
    _supported_domain(direction, scale, node_matrix, node_parent,
                      skin_matrix, parent_matrix)
    a, b, c = _finite_tuple(point, 3, 'point')
    position = _finite_tuple(position, 3, 'position')
    co, si = math.cos(S_ANGLE), math.sin(S_ANGLE)
    original = (co * b - si * c + position[0],
                -a + position[1], si * b + co * c + position[2])
    return to_yup(original)


def loaded_model_vector(vector, *, direction, scale, node_matrix,
                        node_parent, skin_matrix, parent_matrix):
    """Apply the same orthogonal linear chain, without owner translation."""
    return loaded_model_point(vector, (0, 0, 0), direction=direction, scale=scale,
                              node_matrix=node_matrix, node_parent=node_parent,
                              skin_matrix=skin_matrix, parent_matrix=parent_matrix)


def loaded_world_meshes(meshes, position, *, direction, scale,
                        skin_matrix, parent_matrix):
    """Copy raw WorldMesh vertices into loaded Y-up; apply once at the owner seam.

    Node identity and root-parent status are checked per mesh, including empty
    meshes. Normals follow the same orthogonal chain; this does not restore the
    original game's lighting. Indices, material references and UVs are retained.
    """
    from .v3d import WorldMesh

    position = _finite_tuple(position, 3, 'position')
    # Validate caller assumptions even when there are no meshes to transform.
    _supported_domain(direction, scale, IDENTITY, -1, skin_matrix, parent_matrix)
    result = []
    for mesh in meshes:
        domain = dict(direction=direction, scale=scale, node_matrix=mesh.matrix,
                      node_parent=mesh.parent, skin_matrix=skin_matrix,
                      parent_matrix=parent_matrix)
        _supported_domain(**domain)
        verts = [(loaded_model_point(point, position, **domain),
                  loaded_model_vector(normal, **domain), uv)
                 for point, normal, uv in mesh.verts]
        result.append(WorldMesh(mesh.name, mesh.parent, mesh.matrix, verts,
                                mesh.k, mesh.ic, mesh.indices, mesh.tex_name,
                                mesh.group_indices, mesh.group_tex_names))
    return result
