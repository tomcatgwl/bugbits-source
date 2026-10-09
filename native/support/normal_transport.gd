# SPDX-License-Identifier: MIT
# Prediction for ArrayMesh normal storage; input must be finite and nonzero.
extends RefCounted

static func decoded_normal(normal: Vector3) -> Vector3:
	assert(normal.is_finite() and normal.length_squared()>0)
	# Vector2 multiplication retains the engine's float32 scaling step.
	var scaled: Vector2 = normal.octahedron_encode()*65535.0
	var stored := Vector2(float(int(clampf(scaled.x,0,65535)))/65535.0,float(int(clampf(scaled.y,0,65535)))/65535.0)
	return Vector3.octahedron_decode(stored)
