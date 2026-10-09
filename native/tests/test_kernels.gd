# SPDX-License-Identifier: MIT
extends SceneTree
## Asset-free, manually specified byte and state expectations.

const BLUR = preload("res://kernels/temporal_blur.gd")
const RESIZE = preload("res://kernels/pixel_center_copy.gd")
var checks: int = 0
var failures: Array[String] = []


func _check(name: String, condition: bool) -> void:
	checks += 1
	if not condition:
		failures.append(name)


func _flat(side: int, value: int, alpha: int = 255) -> PackedByteArray:
	var bytes: PackedByteArray = PackedByteArray()
	bytes.resize(side * side * 4)
	bytes.fill(value)
	for pixel in range(side * side):
		bytes[pixel * 4 + 3] = alpha
	return bytes


func _patch(source: PackedByteArray, points: Array, values: Array) -> void:
	for i in range(points.size()):
		var point: Vector2i = points[i]
		for channel in range(4):
			source[(point.y * 1024 + point.x) * 4 + channel] = values[i][channel]


func _run() -> void:
	var arguments: PackedStringArray = OS.get_cmdline_user_args()
	_check("reject unknown test options", arguments.is_empty() or arguments == PackedStringArray(["--negative-expected"]))
	var kernel = BLUR.new()
	_check("reject unconfigured input", kernel.step(PackedByteArray([1, 2, 3, 4])).is_empty())
	_check("configure constant field", kernel.configure(3, 3))
	var source: PackedByteArray = _flat(3, 32, 0)
	var source_before: PackedByteArray = source.duplicate()
	_check("constant first temporal floor and forced alpha", kernel.step(source) == _flat(3, 1))
	_check("caller input unchanged", source == source_before)
	_check("second update retains filtered history", kernel.step(_flat(3, 255, 2)) == _flat(3, 8))
	var history: PackedByteArray = kernel.get_history()
	history.fill(0)
	_check("returned history cannot mutate internal state", kernel.get_history() == _flat(3, 8))
	var input_history: PackedByteArray = _flat(3, 255, 17)
	_check("accept valid checkpoint", kernel.set_history(input_history))
	input_history.fill(0)
	_check("checkpoint is copied", kernel.get_history() == _flat(3, 255, 17))
	_check("history and source alpha do not affect RGB", kernel.step(_flat(3, 0, 9)) == _flat(3, 247))
	var saved: PackedByteArray = kernel.get_history()
	_check("reject zero and oversized dimensions", not kernel.configure(0, 3) and not kernel.configure(129, 3))
	_check("reject invalid source and checkpoint lengths", kernel.step(PackedByteArray([1])).is_empty() and not kernel.set_history(PackedByteArray([1])))
	_check("invalid operations preserve current state", kernel.width == 3 and kernel.height == 3 and kernel.get_history() == saved)

	_check("configure impulse", kernel.configure(5, 5))
	var impulse: PackedByteArray = _flat(5, 0, 77)
	for channel in range(3):
		impulse[12 * 4 + channel] = 64
	_check("set impulse checkpoint", kernel.set_history(impulse))
	var expected: PackedByteArray = _flat(5, 0)
	# Hand-computed separable [1,2,1]/4 impulse response; edges remain zero.
	var weights: Array[int] = [4, 8, 4, 8, 16, 8, 4, 8, 4]
	var pixels: Array[int] = [6, 7, 8, 11, 12, 13, 16, 17, 18]
	for i in range(pixels.size()):
		for channel in range(3):
			expected[pixels[i] * 4 + channel] = weights[i]
	_check("separate horizontal and vertical snapshots", kernel.step(impulse) == expected)
	_check("next history is spatially filtered output", kernel.get_history() == expected)

	_check("configure boundary impulse", kernel.configure(5, 5))
	impulse = _flat(5, 0, 0)
	impulse[0] = 255
	expected = _flat(5, 0)
	expected[0] = 7
	expected[4] = 1
	expected[20] = 1
	_check("corner preserves boundaries without wrapping", kernel.step(impulse) == expected)
	_check("configure one pixel", kernel.configure(1, 1))
	expected = PackedByteArray([0, 1, 7, 255])
	if OS.get_cmdline_user_args() == PackedStringArray(["--negative-expected"]):
		expected[0] = 1
	_check("single pixel integer truncation", kernel.step(PackedByteArray([31, 32, 255, 0])) == expected)

	var resize = RESIZE.new()
	_check("copy rejects incorrect byte count", resize.copy(PackedByteArray([1, 2, 3, 4])).is_empty())
	var large: PackedByteArray = PackedByteArray()
	large.resize(1024 * 768 * 4)
	large.fill(0)
	_patch(large, [Vector2i(3, 2), Vector2i(4, 2), Vector2i(3, 3), Vector2i(4, 3)],
		[[0, 255, 0, 0], [1, 255, 100, 0], [1, 254, 200, 255], [0, 254, 255, 255]])
	_patch(large, [Vector2i(299, 272), Vector2i(300, 272), Vector2i(299, 273), Vector2i(300, 273)],
		[[17, 31, 250, 9], [17, 31, 250, 9], [17, 31, 250, 9], [17, 31, 250, 9]])
	_patch(large, [Vector2i(1019, 764), Vector2i(1020, 764), Vector2i(1019, 765), Vector2i(1020, 765)],
		[[255, 0, 1, 254], [255, 0, 1, 254], [255, 0, 1, 254], [255, 0, 1, 254]])
	var copy_before: PackedByteArray = large.duplicate()
	var small: PackedByteArray = resize.copy(large)
	_check("copy dimensions", small.size() == 128 * 128 * 4)
	_check("top-left rounding and four independent channels", small.slice(0, 4) == PackedByteArray([1, 255, 139, 128]))
	_check("interior pixel-center mapping", small.slice((45 * 128 + 37) * 4, (45 * 128 + 37) * 4 + 4) == PackedByteArray([17, 31, 250, 9]))
	_check("bottom-right pixel-center mapping", small.slice(small.size() - 4) == PackedByteArray([255, 0, 1, 254]))
	_check("unsampled pixels stay zero", small.slice(4, 8) == PackedByteArray([0, 0, 0, 0]))
	_check("copy source unchanged", large == copy_before)
	print(JSON.stringify({"status": "PASS" if failures.is_empty() else "FAIL", "checks": checks, "failures": failures, "assetsRequired": false, "gameFidelityClaimed": false}))
	quit(0 if failures.is_empty() else 1)


func _initialize() -> void:
	call_deferred("_run")
