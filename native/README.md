# Independent native byte kernels

These original GDScript implementations accept caller-owned byte arrays. They
contain no game images, geometry, captured frames, memory dumps, executable bytes,
or original game data. They are covered by the repository's MIT license.

- `kernels/temporal_blur.gd`: bounded, stateful three-channel temporal blending
  and separable spatial filtering. Input uses tight four-byte pixels; output alpha
  is 255. The next history is the filtered output, with copied state ownership.
- `kernels/pixel_center_copy.gd`: fixed 1024×768 to 128×128 pixel-center linear
  downsampling on encoded bytes. It preserves channel order and processes alpha
  independently; it does not convert color spaces.

No original game assets are needed for the synthetic tests. With a Godot 4
executable available, run from the repository root:

```sh
godot --headless --path native --script res://tests/test_kernels.gd
```

The runner checks integer truncation, state ownership, invalid inputs, borders,
an independently specified impulse response, channel handling and sample
coordinates. A deliberate incorrect expectation must produce a nonzero exit:

```sh
godot --headless --path native --script res://tests/test_kernels.gd -- --negative-expected
```

These tests cover byte processing only. They do not verify the original game's
complete rendering, animation, occlusion, timing or gameplay. The full native
prototype and private original-runtime evidence are not included.
