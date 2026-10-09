# SPDX-License-Identifier: MIT
# Replace a validated vertex pool while retaining all other surface attributes.
extends RefCounted

static func replace_pool_arrays(source: Array, positions: PackedVector3Array, normals: PackedVector3Array) -> Array:
	if source.size() != Mesh.ARRAY_MAX or not source[Mesh.ARRAY_VERTEX] is PackedVector3Array:
		return []
	var count: int = source[Mesh.ARRAY_VERTEX].size()
	if count == 0 or positions.size() != count or normals.size() != count:
		return []
	for i in range(count):
		if not positions[i].is_finite() or not normals[i].is_finite():
			return []
	var result: Array = source.duplicate(true)
	result[Mesh.ARRAY_VERTEX] = positions.duplicate()
	result[Mesh.ARRAY_NORMAL] = normals.duplicate()
	return result
