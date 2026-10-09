# SPDX-License-Identifier: MIT
extends RefCounted
# Four independent encoded color bytes; channel order is preserved (BGRA/RGBA).
# Fixed 1024x768 -> 128x128, pixel-center LINEAR copy, no fitted parameters.
func copy(source: PackedByteArray) -> PackedByteArray:
	if source.size() != 1024 * 768 * 4:
		return PackedByteArray()
	var output := PackedByteArray()
	output.resize(128 * 128 * 4)
	for y in range(128):
		for x in range(128):
			var top_left: int = ((6 * y + 2) * 1024 + 8 * x + 3) * 4
			var top_right: int = top_left + 4
			var bottom_left: int = top_left + 4096
			var bottom_right: int = bottom_left + 4
			var dest: int = (y * 128 + x) * 4
			for channel in range(4):
				output[dest + channel] = (int(source[top_left + channel]) + int(source[top_right + channel]) + int(source[bottom_left + channel]) + int(source[bottom_right + channel]) + 2) >> 2
	return output
