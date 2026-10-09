# SPDX-License-Identifier: MIT
extends SceneTree

var checks: int = 0
var failures: int = 0

func check(ok: bool, label: String):
	checks += 1
	if not ok:
		failures += 1
		printerr(label)

func _init():
	var api = load("res://support/controlled_pose_buffer.gd")
	var source: Array = []
	source.resize(Mesh.ARRAY_MAX)
	source[Mesh.ARRAY_VERTEX] = PackedVector3Array([Vector3(0,0,0),Vector3(2,0,0),Vector3(0,3,0)])
	source[Mesh.ARRAY_NORMAL] = PackedVector3Array([Vector3.UP,Vector3.UP,Vector3.UP])
	source[Mesh.ARRAY_TEX_UV] = PackedVector2Array([Vector2.ZERO,Vector2.RIGHT,Vector2.DOWN])
	source[Mesh.ARRAY_COLOR] = PackedColorArray([Color.RED,Color.GREEN,Color.BLUE])
	source[Mesh.ARRAY_INDEX] = PackedInt32Array([0,1,2])
	var positions := PackedVector3Array([Vector3(1,2,3),Vector3(3,2,3),Vector3(1,5,3)])
	var normals := PackedVector3Array([Vector3.RIGHT,Vector3.RIGHT,Vector3.RIGHT])
	var result: Array = api.replace_pool_arrays(source,positions,normals)
	check(result.size()==Mesh.ARRAY_MAX,"accepted correct vertex count")
	check(result[Mesh.ARRAY_VERTEX]==positions and result[Mesh.ARRAY_NORMAL]==normals,"pose vectors replaced")
	for i in range(Mesh.ARRAY_MAX):
		if i!=Mesh.ARRAY_VERTEX and i!=Mesh.ARRAY_NORMAL:
			check(result[i]==source[i],"attribute retained %s" % i)
	positions[0]=Vector3(99,99,99)
	normals[0]=Vector3(99,99,99)
	check(result[Mesh.ARRAY_VERTEX][0]==Vector3(1,2,3),"position input is privately copied")
	check(result[Mesh.ARRAY_NORMAL][0]==Vector3.RIGHT,"normal input is privately copied")
	check(source[Mesh.ARRAY_VERTEX][0]==Vector3.ZERO,"original surface remains unchanged")
	check(api.replace_pool_arrays([],positions,normals).is_empty(),"invalid surface shape rejected")
	check(api.replace_pool_arrays(source,PackedVector3Array([Vector3.ZERO]),normals).is_empty(),"position count mismatch rejected")
	check(api.replace_pool_arrays(source,positions,PackedVector3Array()).is_empty(),"normal count mismatch rejected")
	positions[0]=Vector3(NAN,0,0)
	check(api.replace_pool_arrays(source,positions,normals).is_empty(),"NaN position rejected")
	positions[0]=Vector3.ZERO
	normals[0]=Vector3(0,INF,0)
	check(api.replace_pool_arrays(source,positions,normals).is_empty(),"infinite normal rejected")
	print(JSON.stringify({"status":"PASS" if failures==0 else "FAIL","checks":checks,"failures":failures}))
	quit(0 if failures==0 else 1)
