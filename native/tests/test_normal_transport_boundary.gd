# SPDX-License-Identifier: MIT
extends SceneTree

func _init():
	var api = load("res://support/normal_transport.gd")
	var positions := PackedVector3Array()
	var normals := PackedVector3Array()
	for i in range(96):
		positions.append(Vector3(i%3,float(i/3),0))
		normals.append(Vector3.octahedron_decode(Vector2(float((13789+i*5473)%65535)/65535.0,float((29427+i*3421)%65535)/65535.0)))
	var arrays: Array = []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = positions
	arrays[Mesh.ARRAY_NORMAL] = normals
	arrays[Mesh.ARRAY_INDEX] = PackedInt32Array([0,1,2])
	var mesh := ArrayMesh.new()
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES,arrays)
	var actual: PackedVector3Array = mesh.surface_get_arrays(0)[Mesh.ARRAY_NORMAL]
	var force_wrong: bool = OS.get_environment("BUGBITS_FORCE_DOUBLE_SCALE")=="1"
	var maximum: float = 0
	var checks: int = 0
	var failures: int = 0
	for i in range(normals.size()):
		var expected: Vector3 = api.decoded_normal(normals[i])
		if force_wrong:
			var encoded: Vector2 = normals[i].octahedron_encode()
			expected = Vector3.octahedron_decode(Vector2(float(int(encoded.x*65535.0))/65535.0,float(int(encoded.y*65535.0))/65535.0))
		var error: float = actual[i].distance_to(expected)
		maximum = maxf(maximum,error)
		checks += 1
		if error>0.0000001:
			failures += 1
	print(JSON.stringify({"status":"PASS" if failures==0 else "FAIL","checks":checks,"failures":failures,"maximumDistance":maximum,"wrongDoubleScale":force_wrong}))
	quit(0 if failures==0 else 1)
