# SPDX-License-Identifier: MIT
extends RefCounted
## Independent stateful integer temporal and spatial byte filter.
## BGRA bytes, tight rows. No textures, image sampling, rendering or dt adjustment.

const MAX_SIDE: int = 128
const MAX_PIXELS: int = 128 * 128

var width: int = 0
var height: int = 0
var last_error: String = ""
var _history: PackedByteArray = PackedByteArray()


func configure(new_width: int, new_height: int) -> bool:
	if new_width <= 0 or new_height <= 0:
		last_error = "dimensions must be positive"
		return false
	if new_width > MAX_SIDE or new_height > MAX_SIDE or new_width * new_height > MAX_PIXELS:
		last_error = "dimensions exceed 128 by 128"
		return false
	width = new_width
	height = new_height
	_history = PackedByteArray()
	_history.resize(width * height * 4)
	_history.fill(0)
	last_error = ""
	return true


func set_history(bytes: PackedByteArray) -> bool:
	# Explicit state injection for an independent oracle or a caller-owned checkpoint.
	if width == 0 or height == 0 or bytes.size() != width * height * 4:
		last_error = "history must contain exactly width * height * 4 bytes"
		return false
	_history = bytes.duplicate()
	last_error = ""
	return true


func get_history() -> PackedByteArray:
	return _history.duplicate()


func step(source: PackedByteArray) -> PackedByteArray:
	var count: int = width * height * 4
	if width == 0 or height == 0 or source.size() != count or _history.size() != count:
		last_error = "source and history must be configured tight BGRA arrays"
		return PackedByteArray()
	# Three distinct snapshots prevent in-place stencil updates and preserve borders.
	var temporal: PackedByteArray = PackedByteArray()
	temporal.resize(count)
	for pixel in range(width * height):
		var start: int = pixel * 4
		for channel in range(3):
			var index: int = start + channel
			# Maximum 8160. All operands are nonnegative bytes; shift is floor /32.
			var accumulated: int = (_history[index] << 5) - _history[index] + source[index]
			temporal[index] = accumulated >> 5
		temporal[start + 3] = 255

	var horizontal: PackedByteArray = temporal.duplicate()
	for y in range(height):
		for x in range(1, width - 1):
			var start: int = (y * width + x) * 4
			for channel in range(3):
				var index: int = start + channel
				var weighted: int = temporal[index - 4] + (temporal[index] << 1) + temporal[index + 4]
				horizontal[index] = weighted >> 2

	var final_output: PackedByteArray = horizontal.duplicate()
	var row_bytes: int = width * 4
	for y in range(1, height - 1):
		for x in range(width):
			var start: int = (y * width + x) * 4
			for channel in range(3):
				var index: int = start + channel
				var weighted: int = horizontal[index - row_bytes] + (horizontal[index] << 1) + horizontal[index + row_bytes]
				final_output[index] = weighted >> 2
	# The next update uses the spatially filtered output, not the temporal snapshot.
	_history = final_output.duplicate()
	last_error = ""
	return final_output
